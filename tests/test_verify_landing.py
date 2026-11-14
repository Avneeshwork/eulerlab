"""verify_landing must tell a pruned file apart from a genuinely lost one."""

from __future__ import annotations

import os
import time
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
    monkeypatch.setattr(vl, "_remote_sizes", lambda prefix, segments=(): remote)
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
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Cannot confirm cloud safety -> do not give the file a pass."""
    _land_then_delete_locally(tmp_path)
    assert _run(tmp_path, None, monkeypatch) == 1
    assert "INTEGRITY UNVERIFIED" in capsys.readouterr().out


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


def test_b2_listing_is_interrupted_at_its_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SlowStore:
        def list_sizes(self, prefix: str) -> dict[str, int]:
            time.sleep(1)
            return {}

    monkeypatch.setattr(vl, "REMOTE_LIST_TIMEOUT_S", 0.01)
    with pytest.raises(TimeoutError, match="integrity-check deadline"):
        vl._list_sizes_bounded(SlowStore(), "nse/")  # type: ignore[arg-type]


def test_b2_is_listed_per_segment_each_with_its_own_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-186: the whole `nse/` prefix holds every dataset and no longer lists
    inside one deadline; each landing segment is listed on its own."""
    asked: list[str] = []

    class Store:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def list_sizes(self, prefix: str) -> dict[str, int]:
            asked.append(prefix)
            return {f"{prefix}x": 1}

    monkeypatch.setattr(vl, "S3ObjectStore", Store)
    monkeypatch.setattr(vl, "load_storage_config", lambda path: object())
    monkeypatch.setattr(vl, "STORAGE_CONFIG", Path(__file__))
    sizes = vl._remote_sizes("nse/", ["cm", "fo"])
    assert asked == ["nse/cm/", "nse/fo/"]
    assert sizes == {"nse/cm/x": 1, "nse/fo/x": 1}


def test_nothing_is_listed_when_every_file_is_on_disk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    Landing(tmp_path).write(
        trade_date=date(2026, 8, 14),
        segment="cm",
        file_format="udiff",
        url="https://example.invalid/f.zip",
        payload=b"payload",
        rows=1,
        inner_name="f.csv",
    )

    def refuse(prefix: str, segments: object = ()) -> None:
        raise AssertionError("listed B2 with nothing to confirm")

    monkeypatch.setattr(vl, "_remote_sizes", refuse)
    assert vl.main([str(tmp_path)]) == 0
