"""The dashboard's first paint uses the newest prices already seen.

Operator, 2026-10-12: it opened on the last settled day and only then went
live. These tests fix what "newest seen" means and, as importantly, when a
saved price must be ignored.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from eulerlab import last_seen, quotes
from eulerlab.api import panels, server
from eulerlab.features import panel as panel_mod

PANEL_DAY = date(2026, 10, 9)
"""A Friday. The next session is Monday the 12th."""


def _quote(symbol: str, last: float, previous: float, at: str) -> quotes.Quote:
    return quotes.Quote(symbol=symbol, last=last, previous_close=previous, source="zerodha", at=at)


def _minute_file(root: Path, symbol: str, bars: list[tuple[str, float]], name: str) -> None:
    folder = root / symbol
    folder.mkdir(parents=True, exist_ok=True)
    table = pa.table({"ts": [ts for ts, _ in bars], "close": [close for _, close in bars]})
    pq.write_table(table, folder / name)


def test_saved_quotes_come_back_as_returns(tmp_path: Path) -> None:
    path = tmp_path / "q.json"
    at = "2026-10-12T09:22:00+00:00"  # 14:52 IST on the Monday
    last_seen.save({"AAA": _quote("AAA", 110.0, 100.0, at)}, path)
    seen = last_seen.saved(PANEL_DAY, path)
    assert seen.returns == pytest.approx({"AAA": 0.10})
    assert seen.taken_at == at
    assert seen.sources == (last_seen.LIVE,)


def test_quotes_from_the_settled_day_are_ignored(tmp_path: Path) -> None:
    """Taken during a session the panel has since settled: the close is better."""
    path = tmp_path / "q.json"
    last_seen.save({"AAA": _quote("AAA", 110.0, 100.0, "2026-10-09T09:22:00+00:00")}, path)
    assert last_seen.saved(PANEL_DAY, path) == last_seen.Seen()


def test_the_day_is_judged_in_india_not_utc(tmp_path: Path) -> None:
    """19:00 UTC on the 9th is 00:30 on the 10th in India."""
    path = tmp_path / "q.json"
    last_seen.save({"AAA": _quote("AAA", 110.0, 100.0, "2026-10-09T19:00:00+00:00")}, path)
    assert last_seen.saved(PANEL_DAY, path).returns


def test_a_missing_or_broken_file_is_nothing_seen(tmp_path: Path) -> None:
    assert last_seen.saved(PANEL_DAY, tmp_path / "absent.json") == last_seen.Seen()
    broken = tmp_path / "broken.json"
    broken.write_text('{"taken_at": "2026-10-12T09:', encoding="utf-8")
    assert last_seen.saved(PANEL_DAY, broken) == last_seen.Seen()


def test_quotes_without_a_previous_close_are_not_saved(tmp_path: Path) -> None:
    path = tmp_path / "q.json"
    last_seen.save({"AAA": _quote("AAA", 110.0, 0.0, "2026-10-12T09:22:00+00:00")}, path)
    assert not path.exists()


def test_minute_bars_after_the_panel_use_the_panel_close(tmp_path: Path) -> None:
    _minute_file(
        tmp_path,
        "AAA",
        [("2026-10-09T15:29:00+0530", 99.0), ("2026-10-12T11:00:00+0530", 105.0)],
        "2026-10-08_2026-10-12.parquet",
    )
    seen = last_seen.minute_bars(PANEL_DAY, {"AAA": 100.0}, tmp_path)
    # From the panel's 100, not the 99 of Friday's last bar: a last trade is
    # not the exchange's closing price.
    assert seen.returns == pytest.approx({"AAA": 0.05})
    assert seen.taken_at == "2026-10-12T11:00:00+0530"


def test_minute_bars_two_sessions_on_use_the_session_before(tmp_path: Path) -> None:
    _minute_file(
        tmp_path,
        "AAA",
        [("2026-10-12T15:29:00+0530", 200.0), ("2026-10-13T10:00:00+0530", 210.0)],
        "2026-10-09_2026-10-13.parquet",
    )
    seen = last_seen.minute_bars(PANEL_DAY, {"AAA": 100.0}, tmp_path)
    assert seen.returns == pytest.approx({"AAA": 0.05})


def test_minute_files_no_newer_than_the_panel_are_not_opened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _minute_file(
        tmp_path, "AAA", [("2026-10-09T15:29:00+0530", 99.0)], "2026-10-04_2026-10-09.parquet"
    )

    def forbidden(*_: object, **__: object) -> None:
        raise AssertionError("opened a minute file that cannot be newer than the panel")

    monkeypatch.setattr(pq, "read_table", forbidden)
    assert last_seen.minute_bars(PANEL_DAY, {"AAA": 100.0}, tmp_path) == last_seen.Seen()


def test_a_file_named_past_the_panel_but_holding_nothing_newer_adds_nothing(
    tmp_path: Path,
) -> None:
    """The name gives the window asked for, not the bars that came back."""
    _minute_file(
        tmp_path, "AAA", [("2026-10-09T15:29:00+0530", 99.0)], "2026-10-08_2026-10-12.parquet"
    )
    assert last_seen.minute_bars(PANEL_DAY, {"AAA": 100.0}, tmp_path) == last_seen.Seen()


def test_the_newer_source_wins_where_both_price_a_stock(tmp_path: Path) -> None:
    path = tmp_path / "q.json"
    last_seen.save(
        {
            "AAA": _quote("AAA", 110.0, 100.0, "2026-10-12T09:22:00+00:00"),  # 14:52 IST
            "BBB": _quote("BBB", 51.0, 50.0, "2026-10-12T09:22:00+00:00"),
        },
        path,
    )
    minute = tmp_path / "minute"
    _minute_file(
        minute, "AAA", [("2026-10-12T11:00:00+0530", 105.0)], "2026-10-08_2026-10-12.parquet"
    )
    seen = last_seen.newest(PANEL_DAY, {"AAA": 100.0}, path=path, root=minute)
    assert seen.returns == pytest.approx({"AAA": 0.10, "BBB": 0.02})
    assert seen.taken_at == "2026-10-12T09:22:00+00:00"
    assert seen.sources == (last_seen.MINUTE, last_seen.LIVE)


def _panel(monkeypatch: pytest.MonkeyPatch) -> None:
    days = [PANEL_DAY - timedelta(days=i) for i in range(39, -1, -1)]
    rows = [
        panel_mod.PanelRow(day=d, symbol=s, close=100.0, volume=10.0, turnover=1e6, isin=s)
        for d in days
        for s in ("AAA", "BBB")
    ]
    monkeypatch.setattr(panels.PANEL, "rows", lambda days=0: rows)


def test_the_first_paint_shows_what_was_last_seen(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*_: object, **__: object) -> None:
        raise AssertionError("the first paint called a broker")

    monkeypatch.setattr(quotes, "nse_universe", forbidden)
    monkeypatch.setattr(quotes, "live", forbidden)
    _panel(monkeypatch)
    at = "2026-10-12T09:22:00+00:00"
    last_seen.save({"AAA": _quote("AAA", 103.0, 100.0, at), "GONE": _quote("GONE", 5.0, 10.0, at)})
    reply = server.snapshot(live=False)
    fresh = reply["freshness"]
    assert fresh["live"] is False
    assert fresh["last_seen"] is True
    assert fresh["taken_at"] == at
    assert fresh["quoted"] == 1  # GONE is not in the panel, so it is not shown
    assert fresh["panel_date"] == PANEL_DAY.isoformat()
    moves = {t["symbol"]: t["return"] for t in reply["map"]["tiles"]}
    assert moves == pytest.approx({"AAA": 0.03, "BBB": 0.0})
    assert reply["regime"]["advancers"] == 1


def test_the_first_paint_with_nothing_newer_is_the_settled_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _panel(monkeypatch)
    fresh = server.snapshot(live=False)["freshness"]
    assert fresh["last_seen"] is False
    assert fresh["taken_at"] == ""
    assert fresh["reason"] == "settled closes; live prices are loading"


def test_a_live_answer_is_saved_and_a_partial_one_is_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _panel(monkeypatch)
    monkeypatch.setattr(server, "_quotes_band", lambda symbols: {"available": False})
    at = "2026-10-12T09:22:00+00:00"
    answer = {"AAA": _quote("AAA", 103.0, 100.0, at)}

    monkeypatch.setattr(quotes, "nse_universe", lambda symbols: (answer, "TimeoutError: cut short"))
    assert server.snapshot(live=True)["freshness"]["live"] is True
    assert not last_seen.PATH.exists()

    monkeypatch.setattr(quotes, "nse_universe", lambda symbols: (answer, ""))
    server.snapshot(live=True)
    assert json.loads(last_seen.PATH.read_text())["quotes"] == {"AAA": [103.0, 100.0]}
