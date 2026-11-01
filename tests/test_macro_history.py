"""The macro charts read pruned days from the bucket (HISTORY #52)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eulerlab import macro
from eulerlab.ingest import landing_reader


def test_a_day_pruned_from_disk_is_read_from_the_bucket(monkeypatch: pytest.MonkeyPatch) -> None:
    """On 2026-11-01 the Mac's macro folder was empty after `prune-local`, so
    every macro chart was blank although the bucket held the history."""
    row = {"at": "2026-10-30T10:00:00+00:00", "name": "DOLLAR INDEX", "last": 99.1}
    remote = {"macro/2026-10-30.jsonl": (json.dumps(row) + "\n").encode()}
    monkeypatch.setattr(landing_reader, "available", lambda *a, **k: sorted(remote))
    monkeypatch.setattr(landing_reader, "read", lambda rel, **k: remote[rel])

    assert macro.series("DOLLAR INDEX", days=100_000) == [("2026-10-30T10:00:00+00:00", 99.1)]


def test_another_folder_is_read_from_disk_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*_: object, **__: object) -> None:
        raise AssertionError("a test folder must not reach the bucket")

    monkeypatch.setattr(landing_reader, "available", forbidden)
    row = {"at": "2026-10-30T10:00:00+00:00", "name": "BRENT", "last": 64.0}
    (tmp_path / "2026-10-30.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")

    assert macro.series("BRENT", days=100_000, root=tmp_path) == [
        ("2026-10-30T10:00:00+00:00", 64.0)
    ]


def test_every_series_comes_from_one_pass_and_skips_the_old_test_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Charts page draws all series from one request (HISTORY #52), and the
    Dollar Index row a test used to write into the real history is skipped."""
    from datetime import UTC, datetime

    today = datetime.now(UTC).date().isoformat()
    rows = [
        {
            "at": f"{today}T04:00:00+00:00",
            "symbol": "TVC:DXY",
            "name": "DOLLAR INDEX",
            "last": 99.4,
            "change_pct": 0.1,
        },
        {
            "at": f"{today}T05:00:00+00:00",
            "symbol": "TVC:DXY",
            "name": "DOLLAR INDEX",
            "last": 98.9,
            "change_pct": 0.15,
        },
        {
            "at": f"{today}T03:00:00+00:00",
            "symbol": "TVC:US10Y",
            "name": "US 10Y",
            "last": 4.1,
            "change_pct": 0.0,
        },
    ]
    (tmp_path / f"{today}.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
    )

    found = macro.all_series(days=5, root=tmp_path)
    assert found == {
        "DOLLAR INDEX": [(f"{today}T04:00:00+00:00", 99.4)],
        "US 10Y": [(f"{today}T03:00:00+00:00", 4.1)],
    }
