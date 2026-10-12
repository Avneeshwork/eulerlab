"""The dashboard's fast paths give the same answers as the slow ones they replaced.

Measured 2026-10-12 on the real panel (5.4 million rows): the snapshot's first
paint went from 6-9 s to 0.4 s and the panel read from 51 s to 19 s. These
tests pin the behaviour, not the timing: a speed-up that changes a number is a
bug.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from eulerlab.api import panels
from eulerlab.bitemporal.store import BitemporalStore, Record
from eulerlab.features import alt_panel
from eulerlab.features import panel as panel_mod


def _write(path: Path, rows: list[tuple[str, str, float]]) -> None:
    path.write_text(
        "\n".join(
            json.dumps({"d": d, "s": s, "c": c, "v": 10.0, "t": 100.0, "isin": f"IN{s}"})
            for d, s, c in rows
        )
        + "\n\n",
        encoding="utf-8",
    )


DAYS = [(date(2026, 1, 1) + timedelta(days=i)).isoformat() for i in range(6)]
ROWS = [(d, s, float(i)) for i, d in enumerate(DAYS) for s in ("AAA", "BBB", "CCC")]
ROWS.remove((DAYS[2], "CCC", 2.0))  # one symbol misses one day


def test_read_panel_is_oldest_first_and_sorts_a_file_that_is_not(tmp_path: Path) -> None:
    ordered, shuffled = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    _write(ordered, ROWS)
    _write(shuffled, ROWS[::-1])
    first, second = panel_mod.read_panel(ordered), panel_mod.read_panel(shuffled)
    assert first == second
    assert [(r.day.isoformat(), r.symbol) for r in first] == sorted((d, s) for d, s, _ in ROWS)
    assert first[0].isin == "INAAA" and first[0].open == 0.0
    assert panel_mod.read_panel(tmp_path / "missing.jsonl") == []


@pytest.fixture
def loaded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> panels._Panel:
    path = tmp_path / "panel.jsonl"
    _write(path, ROWS)
    monkeypatch.setattr(panels, "PANEL_PATH", path)
    monkeypatch.setattr(panels, "read_panel", lambda: panel_mod.read_panel(path))
    return panels._Panel()


@pytest.mark.parametrize("days", [0, 1, 2, 3, 6, 7, 400])
def test_the_last_n_days_slice_equals_the_filter_it_replaced(
    loaded: panels._Panel, days: int
) -> None:
    everything = loaded.rows()
    all_days = sorted({r.day for r in everything})
    expected = (
        everything
        if not days or days >= len(all_days)
        else [r for r in everything if r.day >= all_days[-days]]
    )
    assert loaded.rows(days) == expected
    assert loaded.days() == all_days


def test_coverage_counted_at_load_equals_the_full_scan(loaded: panels._Panel) -> None:
    assert loaded.coverage() == alt_panel.coverage(loaded.rows())
    assert loaded.coverage()["thinnest"] == 5 and loaded.coverage()["symbols"] == 3


def test_a_rebuilt_panel_replaces_the_day_index(
    loaded: panels._Panel, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert len(loaded.days()) == 6
    import os

    path = tmp_path / "panel.jsonl"
    _write(path, [*ROWS, ("2026-02-01", "AAA", 9.0)])
    os.utime(path, ns=(path.stat().st_atime_ns, path.stat().st_mtime_ns + 1_000_000_000))
    assert len(loaded.days()) == 7 and loaded.rows(1)[0].close == 9.0
    assert loaded.coverage()["rows"] == len(ROWS) + 1


def test_the_store_keeps_the_order_a_full_sort_gave() -> None:
    base = datetime(2026, 1, 1, tzinfo=UTC)

    def record(key: str, event: int, known: int, value: float) -> Record:
        return Record(
            key=key,
            event_time=base + timedelta(days=event),
            knowledge_time=base + timedelta(days=known),
            value=value,
        )

    arrivals = [
        record("B", 5, 6, 1.0),
        record("A", 3, 9, 2.0),
        record("A", 3, 9, 2.0),
        record("C", 1, 2, 3.0),
        record("A", 1, 4, 4.0),
    ]
    store = BitemporalStore()
    for item in arrivals:
        store.append(item)
    assert store._records == sorted(arrivals)
    assert len(store) == 5


def test_a_settled_snapshot_asks_no_broker(monkeypatch: pytest.MonkeyPatch) -> None:
    """`live=false` is the first paint. It must not wait on anyone."""
    from eulerlab import quotes
    from eulerlab.api import server

    def forbidden(*_: object, **__: object) -> None:
        raise AssertionError("the settled snapshot called a broker")

    monkeypatch.setattr(quotes, "nse_universe", forbidden)
    monkeypatch.setattr(quotes, "live", forbidden)
    days = [date(2026, 1, 1) + timedelta(days=i) for i in range(40)]
    rows = [
        panel_mod.PanelRow(day=d, symbol=s, close=100.0 + i, volume=10.0, turnover=1e6, isin=s)
        for i, d in enumerate(days)
        for s in ("AAA", "BBB")
    ]
    monkeypatch.setattr(panels.PANEL, "rows", lambda days=0: rows)
    reply = server.snapshot(live=False)
    assert reply["ok"] is True
    assert reply["quotes"] == {
        "available": False,
        "reason": "live prices are loading",
        "quotes": {},
    }
