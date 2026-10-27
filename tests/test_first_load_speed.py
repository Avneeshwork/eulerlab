"""The faster readers behind the dashboard and the Data tab return what the slow ones did."""

from __future__ import annotations

import json
import os
import time
from datetime import date
from pathlib import Path

import pytest

from eulerlab.features import us_panel


def test_the_us_panel_reads_every_field_and_skips_bad_lines(tmp_path: Path) -> None:
    path = tmp_path / "us_panel.jsonl"
    rows = [
        {"d": "2026-10-23", "s": "AAPL", "c": 230.5, "v": 1000, "o": 229, "h": 231, "l": 228.5},
        {"d": "2026-10-23", "s": "MSFT", "c": 410, "v": 500},
        {"d": "2026-10-26", "s": "AAPL", "c": 232.0, "v": 900, "o": 230, "h": 233, "l": 229},
    ]
    text = "\n".join(json.dumps(r) for r in rows)
    path.write_text(text + '\n\nnot json\n{"d": "2026-10-26"}\n', encoding="utf-8")

    out = us_panel.read(path)

    assert [(r.day, r.symbol, r.close, r.volume, r.open, r.high, r.low) for r in out] == [
        (date(2026, 10, 23), "AAPL", 230.5, 1000.0, 229.0, 231.0, 228.5),
        (date(2026, 10, 23), "MSFT", 410.0, 500.0, 0.0, 0.0, 0.0),
        (date(2026, 10, 26), "AAPL", 232.0, 900.0, 230.0, 233.0, 229.0),
    ]
    assert out[0].turnover == pytest.approx(230.5 * 1000)
    # One shared date and one shared string per distinct value.
    assert out[0].day is out[1].day
    assert out[0].symbol is out[2].symbol


def test_us_rows_stay_frozen(tmp_path: Path) -> None:
    path = tmp_path / "us_panel.jsonl"
    path.write_text(json.dumps({"d": "2026-10-23", "s": "A", "c": 1, "v": 1}) + "\n")
    row = us_panel.read(path)[0]
    with pytest.raises(AttributeError):
        row.close = 2.0  # type: ignore[misc]


def test_a_missing_us_panel_is_empty(tmp_path: Path) -> None:
    assert us_panel.read(tmp_path / "absent.jsonl") == []


def test_landing_counts_walk_nested_folders_and_are_reused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from eulerlab.api import server

    monkeypatch.chdir(tmp_path)
    root = tmp_path / "data/landing/nse"
    (root / "a/b").mkdir(parents=True)
    (root / "one.gz").write_bytes(b"12345")
    (root / "a/b/two.gz").write_bytes(b"123")
    os.utime(root / "a/b/two.gz", (1_761_000_000, 1_761_000_000))
    os.utime(root / "one.gz", (1_700_000_000, 1_700_000_000))

    first = server._landing_source("nse")
    assert first == {
        "name": "nse",
        "present": True,
        "files": 2,
        "bytes": 8,
        "newest": "2025-10-20",
    }

    (root / "three.gz").write_bytes(b"1")
    assert server._landing_source("nse") == first  # reused inside the limit

    monkeypatch.setattr(server, "LANDING_COUNT_TTL", 0.0)
    time.sleep(0.001)
    assert server._landing_source("nse")["files"] == 3


def test_an_absent_landing_source_says_so(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from eulerlab.api import server

    monkeypatch.chdir(tmp_path)
    assert server._landing_source("crypto") == {
        "name": "crypto",
        "present": False,
        "files": 0,
        "newest": None,
    }


def test_the_dashboard_calendar_never_waits_on_the_bucket(monkeypatch: pytest.MonkeyPatch) -> None:
    """The snapshot's calendar band asks for the saved listing; ingests do not."""
    from eulerlab.api import server
    from eulerlab.ingest import landing_reader

    asked: list[bool] = []

    def available(tree: str, pattern: str = "**/*", **kwargs: object) -> list[str]:
        asked.append(bool(kwargs.get("stale_ok")))
        return []

    monkeypatch.setattr(landing_reader, "available", available)
    server._calendar_band()
    from eulerlab.ingest import forexfactory

    forexfactory.read_all()
    assert asked == [True, False]


@pytest.mark.parametrize("block", [7, 64, 300, 1 << 18])
@pytest.mark.parametrize("count", [1, 2, 3, 9])
def test_the_last_sessions_match_a_full_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, block: int, count: int
) -> None:
    """Blocks small enough to cut a day in half must still return whole days."""
    path = tmp_path / "us_panel.jsonl"
    lines = [
        json.dumps({"d": f"2026-10-{day:02d}", "s": symbol, "c": day + n, "v": 1})
        for day in (20, 21, 22, 23, 26)
        for n, symbol in enumerate(("AAPL", "MSFT", "NVDA"))
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    monkeypatch.setattr(us_panel, "TAIL_BLOCK", block)

    everything = us_panel.read(path)
    wanted = sorted({r.day for r in everything})[-count:]
    assert us_panel.last_sessions(count, path) == [r for r in everything if r.day in wanted]


def test_no_sessions_from_a_missing_file(tmp_path: Path) -> None:
    assert us_panel.last_sessions(2, tmp_path / "absent.jsonl") == []
