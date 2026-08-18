"""The landing zone's two promises: written once, never modified."""

from __future__ import annotations

import json
import os
import stat
from datetime import date
from pathlib import Path

import pytest

from eulerlab.ingest.landing import Landing, ManifestEntry, relative_path, sha256_of

PAYLOAD = b"TradDt,ClsPric\n2026-08-14,100\n"


def _land(root: Path, day: date = date(2026, 8, 14), segment: str = "cm") -> ManifestEntry:
    return Landing(root).write(
        trade_date=day,
        segment=segment,
        file_format="udiff",
        url="https://example.invalid/f.zip",
        payload=PAYLOAD,
        rows=1,
        inner_name="f.csv",
    )


def test_layout_is_partitioned_and_chronologically_sortable() -> None:
    assert relative_path(date(2015, 1, 2), "cm", "legacy") == Path(
        "cm/2015/01/2015-01-02_legacy.zip"
    )


def test_written_bytes_are_exactly_what_was_passed(tmp_path: Path) -> None:
    entry = _land(tmp_path)
    # Not re-compressed, not normalised. Byte-for-byte what the exchange served.
    assert (tmp_path / entry.path).read_bytes() == PAYLOAD
    assert entry.sha256 == sha256_of(PAYLOAD)
    assert entry.size_bytes == len(PAYLOAD)


def test_landed_files_are_read_only(tmp_path: Path) -> None:
    entry = _land(tmp_path)
    mode = (tmp_path / entry.path).stat().st_mode
    assert not mode & stat.S_IWUSR
    assert not mode & stat.S_IWGRP
    assert not mode & stat.S_IWOTH


def test_writing_leaves_no_partial_files_behind(tmp_path: Path) -> None:
    _land(tmp_path)
    assert list(tmp_path.rglob("*.part")) == []


def test_manifest_records_knowledge_time(tmp_path: Path) -> None:
    entry = _land(tmp_path)
    # knowledge_time is when *we* learned it — the bitemporal second axis.
    assert entry.knowledge_time.endswith("+00:00")


def test_manifest_survives_a_reload(tmp_path: Path) -> None:
    _land(tmp_path)
    reloaded = Landing(tmp_path)
    assert reloaded.has(date(2026, 8, 14), "cm")


def test_has_is_false_for_a_date_never_landed(tmp_path: Path) -> None:
    _land(tmp_path)
    assert not Landing(tmp_path).has(date(2026, 8, 15), "cm")
    assert not Landing(tmp_path).has(date(2026, 8, 14), "fo")


def test_a_manifest_row_whose_file_vanished_is_not_treated_as_present(tmp_path: Path) -> None:
    # Otherwise a deleted file becomes a permanent silent gap: the manifest
    # says we have it, so no re-run ever fetches it again.
    entry = _land(tmp_path)
    target = tmp_path / entry.path
    os.chmod(target, 0o644)
    target.unlink()
    assert not Landing(tmp_path).has(date(2026, 8, 14), "cm")


def test_verify_detects_a_modified_file(tmp_path: Path) -> None:
    entry = _land(tmp_path)
    target = tmp_path / entry.path
    os.chmod(target, 0o644)
    target.write_bytes(b"tampered")
    problems = Landing(tmp_path).verify()
    assert len(problems) == 1
    assert "checksum changed" in problems[0]


def test_verify_is_silent_on_an_untouched_zone(tmp_path: Path) -> None:
    _land(tmp_path)
    assert Landing(tmp_path).verify() == []


def test_manifest_is_append_only_jsonl(tmp_path: Path) -> None:
    _land(tmp_path, date(2026, 8, 13))
    _land(tmp_path, date(2026, 8, 14))
    lines = (tmp_path / "manifest.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert [json.loads(line)["trade_date"] for line in lines] == ["2026-08-13", "2026-08-14"]


def test_a_corrupt_manifest_row_fails_loudly(tmp_path: Path) -> None:
    _land(tmp_path)
    with (tmp_path / "manifest.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({**json.loads(_first_line(tmp_path)), "rows": "many"}) + "\n")
    with pytest.raises(TypeError, match="rows"):
        Landing(tmp_path).entries()


def _first_line(root: Path) -> str:
    return (root / "manifest.jsonl").read_text(encoding="utf-8").splitlines()[0]
