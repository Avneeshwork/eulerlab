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


# --- options: one underlying, parsed alone --------------------------------------------


def _fo_zip(lines: list[str]) -> bytes:
    import io
    import zipfile

    header = (
        "TradDt,TckrSymb,XpryDt,StrkPric,OptnTp,FinInstrmTp,SttlmPric,ClsPric,"
        "TtlTradgVol,OpnIntrst,UndrlygPric"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("fo.csv", "\n".join([header, *lines]) + "\n")
    return buffer.getvalue()


def test_one_underlying_parsed_alone_equals_filtering_the_whole_file() -> None:
    from eulerlab.options.chain import quotes_from_fo_bhavcopy

    payload = _fo_zip(
        [
            "2026-10-09,NIFTY,2026-10-13,25000,CE,IDO,120.5,121,900,5000,25010",
            "2026-10-09,NIFTY,2026-10-13,25000,PE,IDO,110.0,111,800,4000,25010",
            "2026-10-09,BANKNIFTY,2026-10-28,55000,CE,IDO,300,301,100,900,55010",
            "2026-10-09,NIFTYNXT50,2026-10-28,70000,CE,IDO,200,201,50,400,70010",
            "2026-10-09, nifty ,2026-10-13,25100,CE,IDO,80,81,700,3000,25010",
            "2026-10-09,RELIANCE,2026-10-28,1200,PE,STO,15,16,10,90,1170",
        ]
    )
    everything = list(quotes_from_fo_bhavcopy(payload))
    assert len(everything) == 6
    for name in ("NIFTY", "nifty", "BANKNIFTY", "RELIANCE", "NOPE"):
        expected = [q for q in everything if q.underlying.upper() == name.upper()]
        assert list(quotes_from_fo_bhavcopy(payload, name)) == expected
    # The name is matched on its own cell: NIFTY is not BANKNIFTY or NIFTYNXT50.
    assert {q.underlying.strip().upper() for q in quotes_from_fo_bhavcopy(payload, "NIFTY")} == {
        "NIFTY"
    }


# --- bucket listing: old now, current soon ---------------------------------------------


def test_a_screen_gets_the_old_listing_at_once_and_a_backtest_waits_for_the_new(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import threading
    import time

    from eulerlab.ingest import landing_reader as lr

    release = threading.Event()
    calls: list[str] = []

    def fetch(tree: str, pattern: str) -> tuple[str, ...]:
        calls.append(tree)
        release.wait(5)
        found = ("fo/new.zip",)
        lr._LISTED[(tree, pattern)] = (time.monotonic(), found)
        return found

    monkeypatch.setattr(lr, "_fetch_listing", fetch)
    monkeypatch.setattr(
        lr, "_LISTED", {("fo", "*.zip"): (time.monotonic() - 9999, ("fo/old.zip",))}
    )
    monkeypatch.setattr(lr, "_REFRESHING", set())

    # Two screens in a row: both answered from the old listing, one refresh started.
    assert lr._remote_listing("fo", "*.zip", stale_ok=True) == ("fo/old.zip",)
    assert lr._remote_listing("fo", "*.zip", stale_ok=True) == ("fo/old.zip",)
    release.set()
    for _ in range(100):
        if not lr._REFRESHING:
            break
        time.sleep(0.02)
    assert calls == ["fo"]
    assert lr._remote_listing("fo", "*.zip", stale_ok=True) == ("fo/new.zip",)

    # A caller that did not say stale is fine never gets an expired listing.
    lr._LISTED[("fo", "*.zip")] = (time.monotonic() - 9999, ("fo/old.zip",))
    assert lr._remote_listing("fo", "*.zip") == ("fo/new.zip",)
    # And with nothing cached at all, even a screen has to wait for the first one.
    lr._LISTED.clear()
    assert lr._remote_listing("fo", "*.zip", stale_ok=True) == ("fo/new.zip",)


# --- results: one read per question --------------------------------------------------


def test_summary_reads_a_strategys_runs_once_and_says_the_same(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from eulerlab import results

    runs = [
        results._to_run({"strategy_id": "s", "sharpe": 1.0, "fills": 5, "at": "2026-01-01"}),
        results._to_run(
            {"strategy_id": "s", "sharpe": 2.0, "fills": 5, "at": "2026-01-02", "window_days": 9}
        ),
        results._to_run({"strategy_id": "s", "sharpe": 9.0, "fills": 0, "at": "2026-01-03"}),
    ]
    reads: list[str] = []

    def distinct(workspace: object, strategy_id: str) -> list[results.Run]:
        reads.append(strategy_id)
        return runs

    monkeypatch.setattr(results, "distinct", distinct)
    summary = results.summary(None, "s")  # type: ignore[arg-type]
    assert reads == ["s"]
    assert summary["sharpe"] == 2.0 and summary["runs"] == 2
    # Passing the runs in changes nothing about the answer.
    assert results.latest(None, "s", runs) == results.latest(None, "s")  # type: ignore[arg-type]
    assert results.best(None, "s", runs) == results.best(None, "s")  # type: ignore[arg-type]


# --- options history: the light path says what the full one says ----------------------


def test_the_historys_light_chain_gives_the_same_point_as_the_full_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from eulerlab.api import server
    from eulerlab.ingest import landing_reader
    from eulerlab.options.history import history_point

    lines = []
    for strike, call, put in [
        (24800, 260.0, 45.0),
        (24900, 185.0, 70.0),
        (25000, 122.0, 108.0),
        (25100, 74.0, 160.0),
        (25200, 41.0, 228.0),
    ]:
        lines.append(f"2026-10-09,NIFTY,2026-10-20,{strike},CE,IDO,{call},{call},900,5000,25010")
        lines.append(f"2026-10-09,NIFTY,2026-10-20,{strike},PE,IDO,{put},{put},800,6000,25010")
    lines.append("2026-10-09,BANKNIFTY,2026-10-28,55000,CE,IDO,300,301,100,900,55010")
    payload = _fo_zip(lines)
    monkeypatch.setattr(
        landing_reader, "available", lambda *a, **k: ["fo/2026/10/2026-10-09_udiff.zip"]
    )
    monkeypatch.setattr(landing_reader, "read", lambda *a, **k: payload)

    full = server._chain_payload("NIFTY", "", "", summary=False)
    light = server._chain_payload("NIFTY", "", "", summary=True)
    assert full["ok"] and light["ok"]
    point = history_point(full)
    assert point is not None and point == history_point(light)
    assert point["atm_strike"] == 25000 and point["straddle"] == 230.0
    # The light payload holds the one row; the full one holds them all.
    assert len(light["strikes"]) == 1 and len(full["strikes"]) == 5
    assert "smile" in full and "smile" not in light
    assert server.options_history("NIFTY", days=5)["points"] == [point]
