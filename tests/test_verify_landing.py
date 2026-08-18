"""verify_landing must tell a pruned file apart from a genuinely lost one."""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import pytest

import eulerlab.ingest.verify_landing as vl
from eulerlab.ingest.landing import Landing


def _land_then_delete_locally(tmp_path: Path) -> tuple[Landing, str, int]:
    """A landed file whose local copy has been removed (as prune-local would)."""
    landing = Landing(tmp_path)
    landing.write(
        trade_date=date(2026, 8, 14),
        segment="cm",
        file_format="udiff",
        url="https://example.invalid/f.zip",
        payload=b"payload",
        rows=1,
        inner_name="f.csv",
    )
    entry = next(iter(landing.entries().values()))
    os.chmod(tmp_path / entry.path, 0o644)
    (tmp_path / entry.path).unlink()
    return landing, entry.path, entry.size_bytes


def _run(root: Path, remote: dict[str, int] | None, monkeypatch: pytest.MonkeyPatch) -> int:
    monkeypatch.setattr(vl, "_remote_sizes", lambda prefix: remote)
    return vl.main([str(root)])


def test_a_pruned_file_confirmed_in_b2_is_not_a_violation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, path, size = _land_then_delete_locally(tmp_path)
    assert _run(tmp_path, {f"nse/{path}": size}, monkeypatch) == 0


def test_a_missing_file_not_in_b2_is_a_real_violation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _land_then_delete_locally(tmp_path)
    assert _run(tmp_path, {}, monkeypatch) == 1  # bucket empty


def test_a_missing_file_at_the_wrong_size_in_b2_is_still_a_violation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, path, size = _land_then_delete_locally(tmp_path)
    assert _run(tmp_path, {f"nse/{path}": size + 1}, monkeypatch) == 1


def test_when_b2_is_unreachable_a_missing_file_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cannot confirm cloud safety -> do not give the file a pass."""
    _land_then_delete_locally(tmp_path)
    assert _run(tmp_path, None, monkeypatch) == 1


def test_an_intact_on_disk_file_still_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    landing = Landing(tmp_path)
    landing.write(
        trade_date=date(2026, 8, 14),
        segment="cm",
        file_format="udiff",
        url="https://example.invalid/f.zip",
        payload=b"payload",
        rows=1,
        inner_name="f.csv",
    )
    assert _run(tmp_path, {}, monkeypatch) == 0


def test_a_tampered_on_disk_file_is_still_caught(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    landing = Landing(tmp_path)
    landing.write(
        trade_date=date(2026, 8, 14),
        segment="cm",
        file_format="udiff",
        url="https://example.invalid/f.zip",
        payload=b"payload",
        rows=1,
        inner_name="f.csv",
    )
    entry = next(iter(landing.entries().values()))
    os.chmod(tmp_path / entry.path, 0o644)
    (tmp_path / entry.path).write_bytes(b"tampered")
    assert _run(tmp_path, {}, monkeypatch) == 1


def test_an_empty_landing_zone_needs_no_b2_check(tmp_path: Path) -> None:
    assert vl.main([str(tmp_path)]) == 0
