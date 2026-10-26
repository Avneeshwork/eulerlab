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
from typing import Any

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
    monkeypatch.setattr(server, "_HISTORY_POINTS", {})

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


def test_a_history_day_is_parsed_once_and_a_failed_day_is_tried_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A landed bhavcopy never changes, so its point is kept. A day whose chain
    could not be read (a fetch that failed) must not be remembered as empty."""
    from eulerlab.api import server

    calls: list[str] = []
    point = {"day": "2026-10-09", "straddle": 230.0}

    def chain(underlying: str, day: str, expiry: str, *, summary: bool) -> dict[str, Any]:
        calls.append(day)
        return {"ok": day == "2026-10-09", "point": point}

    monkeypatch.setattr(server, "_HISTORY_POINTS", {})
    monkeypatch.setattr(server, "_chain_payload", chain)
    monkeypatch.setattr(
        server, "options_days", lambda limit=400: {"days": ["2026-10-12", "2026-10-09"]}
    )
    monkeypatch.setattr(
        "eulerlab.options.history.history_point",
        lambda payload: payload["point"] if payload["ok"] else None,
    )

    first = server.options_history("NIFTY", days=2)
    second = server.options_history("nifty", days=2)

    assert first["points"] == second["points"] == [point]
    assert first["skipped"] == second["skipped"] == ["2026-10-12"]
    assert calls == ["2026-10-09", "2026-10-12", "2026-10-12"], "only the failed day is re-read"


def test_a_row_read_from_the_file_is_the_row_the_constructor_makes(tmp_path: Path) -> None:
    """`read_panel` builds rows without `__init__`; this holds it to `__init__`."""
    import dataclasses

    path = tmp_path / "p.jsonl"
    path.write_text(
        json.dumps(
            {
                "d": "2026-01-05",
                "s": "AAA",
                "c": 10.5,
                "v": 7.0,
                "t": 73.5,
                "i": "INE1",
                "o": 10.0,
                "h": 11.0,
                "l": 9.5,
            }
        )
        + "\n"
        + json.dumps({"d": "2026-01-06", "s": "AAA", "c": 11.0, "v": 1.0, "t": 11.0})
        + "\n",
        encoding="utf-8",
    )
    first, second = panel_mod.read_panel(path)
    made = panel_mod.PanelRow(
        day=date(2026, 1, 5),
        symbol="AAA",
        close=10.5,
        volume=7.0,
        turnover=73.5,
        isin="INE1",
        open=10.0,
        high=11.0,
        low=9.5,
    )
    assert first == made and hash(first) == hash(made) and repr(first) == repr(made)
    # A line without the optional columns gets the dataclass's own defaults.
    assert second == panel_mod.PanelRow(
        day=date(2026, 1, 6), symbol="AAA", close=11.0, volume=1.0, turnover=11.0
    )
    # Slotted (no per-row dict), and every field the dataclass declares is set.
    names = [f.name for f in dataclasses.fields(panel_mod.PanelRow)]
    assert not hasattr(first, "__dict__")
    assert all(hasattr(first, name) for name in names)
    with pytest.raises(dataclasses.FrozenInstanceError):
        first.close = 1.0  # type: ignore[misc]


def test_only_the_days_whose_symbols_are_out_of_order_are_sorted(tmp_path: Path) -> None:
    """Days in order, symbols shuffled inside two of them: the same rows as a full sort."""
    mixed = [
        (DAYS[0], "AAA", 1.0), (DAYS[0], "BBB", 1.0), (DAYS[0], "CCC", 1.0),
        (DAYS[1], "CCC", 2.0), (DAYS[1], "AAA", 2.0), (DAYS[1], "BBB", 2.0),
        (DAYS[2], "AAA", 3.0),
        (DAYS[3], "BBB", 4.0), (DAYS[3], "AAA", 4.0),
    ]  # fmt: skip
    path = tmp_path / "mixed.jsonl"
    _write(path, mixed)
    rows = panel_mod.read_panel(path)
    assert [(r.day.isoformat(), r.symbol) for r in rows] == sorted((d, s) for d, s, _ in mixed)


def test_the_row_helpers_agree_with_their_plain_definitions(tmp_path: Path) -> None:
    path = tmp_path / "p.jsonl"
    _write(path, ROWS)
    rows = panel_mod.read_panel(path)
    backwards = rows[::-1]
    for given in (rows, backwards, []):
        assert panel_mod.trading_days(given) == sorted({r.day for r in given})
        histories = panel_mod.by_symbol(given)
        assert set(histories) == {r.symbol for r in given}
        for symbol, history in histories.items():
            assert history == sorted((r for r in given if r.symbol == symbol), key=lambda r: r.day)


# --- results mirror: nothing to fetch means nothing fetched ---------------------------


class _Bucket:
    def __init__(self, objects: dict[str, bytes]) -> None:
        self.objects = dict(objects)
        self.gets: list[str] = []
        self.lists = 0

    def list_sizes(self, prefix: str) -> dict[str, int]:
        self.lists += 1
        return {k: len(v) for k, v in self.objects.items() if k.startswith(prefix)}

    def list_md5(self, prefix: str) -> dict[str, str]:
        import hashlib

        self.lists += 1
        return {
            k: hashlib.md5(v, usedforsecurity=False).hexdigest()
            for k, v in self.objects.items()
            if k.startswith(prefix)
        }

    def get(self, key: str) -> bytes:
        self.gets.append(key)
        return self.objects[key]

    def put(self, key: str, payload: bytes, sha256: str) -> None:
        self.objects[key] = payload

    def head_sha256(self, key: str) -> str | None:
        return None


def test_the_mirror_downloads_only_files_that_differ(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from eulerlab import cloud_results
    from eulerlab import workspace as workspace_mod

    monkeypatch.setattr(workspace_mod, "ROOT", tmp_path)
    workspace = workspace_mod.Workspace(id="t", name="T")
    results = workspace.results
    results.mkdir(parents=True)
    prefix = f"{cloud_results.RESULTS_PREFIX}{workspace.id}/"
    same = '{"strategy_id": "a", "at": "2026-01-01", "sharpe": 1.0}\n'
    ours = '{"strategy_id": "b", "at": "2026-01-01", "sharpe": 1.0}\n'
    theirs = ours + '{"strategy_id": "b", "at": "2026-01-02", "sharpe": 2.0}\n'
    (results / "a.jsonl").write_text(same, encoding="utf-8")
    (results / "b.jsonl").write_text(ours, encoding="utf-8")
    bucket = _Bucket(
        {
            f"{prefix}a.jsonl": same.encode(),
            f"{prefix}b.jsonl": theirs.encode(),
            f"{prefix}c.jsonl": same.encode(),
        }
    )
    outcome = cloud_results.mirror(workspace, bucket)
    # a is identical and is left alone; b grew there; c is not here at all.
    assert sorted(bucket.gets) == [f"{prefix}b.jsonl", f"{prefix}c.jsonl"]
    assert bucket.lists == 1 and outcome.pulled == 2 and not outcome.failed
    assert len((results / "b.jsonl").read_text(encoding="utf-8").splitlines()) == 2
    assert (results / "c.jsonl").exists()

    # Asked for everything, it downloads everything.
    bucket.gets.clear()
    cloud_results.mirror(workspace, bucket, full=True)
    assert len(bucket.gets) == 3


def test_two_files_of_equal_size_and_different_content_are_not_called_the_same(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The hole a size test has: each machine appended a different row of one length."""
    from eulerlab import cloud_results
    from eulerlab import workspace as workspace_mod

    monkeypatch.setattr(workspace_mod, "ROOT", tmp_path)
    workspace = workspace_mod.Workspace(id="t", name="T")
    workspace.results.mkdir(parents=True)
    prefix = f"{cloud_results.RESULTS_PREFIX}{workspace.id}/"
    here = '{"configuration": "x", "at": "2026-01-01", "sharpe": 1.0}\n'
    there = '{"configuration": "y", "at": "2026-01-02", "sharpe": 2.0}\n'
    assert len(here) == len(there)
    (workspace.results / "s.jsonl").write_text(here, encoding="utf-8")
    bucket = _Bucket({f"{prefix}s.jsonl": there.encode()})

    outcome = cloud_results.mirror(workspace, bucket)
    merged = (workspace.results / "s.jsonl").read_text(encoding="utf-8")
    # Both rows are now on both sides.
    assert bucket.gets == [f"{prefix}s.jsonl"] and outcome.pulled == 1 and outcome.pushed == 1
    assert '"x"' in merged and '"y"' in merged
    assert bucket.objects[f"{prefix}s.jsonl"].decode() == merged

    # A store that cannot give hashes is never trusted to say "the same".
    class _NoHashes(_Bucket):
        list_md5 = None  # type: ignore[assignment]

    plain = _NoHashes({f"{prefix}s.jsonl": merged.encode()})
    cloud_results.pull(workspace, plain)
    assert plain.gets == [f"{prefix}s.jsonl"]


def test_repeated_rows_are_dropped_and_the_library_says_the_same(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from eulerlab import results
    from eulerlab import workspace as workspace_mod

    monkeypatch.setattr(workspace_mod, "ROOT", tmp_path)
    workspace = workspace_mod.Workspace(id="t", name="T").ensure()

    def row(at: str, sharpe: float, days: int = 100) -> str:
        return json.dumps(
            {"strategy_id": "s", "sharpe": sharpe, "fills": 5, "window_days": days, "at": at}
        )

    lines = [
        row("2026-01-01T00:00:00", 1.0),
        row("2026-01-01T00:00:01", 1.0),  # the same run, written again a second later
        row("2026-01-01T00:00:02", 1.0),
        row("2026-02-01T00:00:00", 2.0, days=200),  # a different configuration
        row("2026-03-01T00:00:00", 1.5),  # the first configuration, a different result
        "{torn",
    ]
    path = workspace.results / "s.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    before = (results.summary(workspace, "s"), results.best(workspace, "s"))

    assert results.drop_duplicates(workspace) == {"s.jsonl": (3, 2)}
    assert len(path.read_text(encoding="utf-8").splitlines()) == 6  # a dry run by default

    assert results.drop_duplicates(workspace, dry_run=False) == {"s.jsonl": (3, 2)}
    kept = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    # Of the three repeats the latest is kept; rows stay in time order.
    assert [r["at"] for r in kept] == [
        "2026-01-01T00:00:02",
        "2026-02-01T00:00:00",
        "2026-03-01T00:00:00",
    ]
    assert (results.summary(workspace, "s"), results.best(workspace, "s")) == before
    assert results.drop_duplicates(workspace, dry_run=False) == {}


def test_the_data_route_answers_before_the_panel_is_read(monkeypatch: pytest.MonkeyPatch) -> None:
    """After a restart `/api/data` waited 37 s for the panel (2026-10-27)."""
    from eulerlab.api import server

    started: list[bool] = []
    from eulerlab.api.panels import PANEL

    monkeypatch.setattr(PANEL, "loaded", lambda: False)
    monkeypatch.setattr(server, "_load_panel_in_background", lambda: started.append(True))
    monkeypatch.setattr(
        PANEL, "rows", lambda days=0: pytest.fail("the route must not read the panel")
    )
    answer = server.data_status()
    assert answer["panel"] == {"loaded": False, "rows": 0}
    assert started == [True]
    assert "sources" in answer and "universes" in answer
