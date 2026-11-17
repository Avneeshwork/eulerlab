"""Research 113 batch 5: earnings-event strategies (`backtest/events_daily.py`)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from eulerlab.backtest.strategy import MarketView
from eulerlab.features.panel import PanelRow
from eulerlab.strategies.daily import events as ev
from eulerlab.strategies.daily.events import common as ev_common
from eulerlab.strategies.daily.events import india_announcement_drift as drift
from eulerlab.strategies.daily.events import india_earnings_announcement_premium as premium

IST = timezone(timedelta(hours=5, minutes=30))


@pytest.fixture
def known(monkeypatch: pytest.MonkeyPatch) -> dict[str, tuple[datetime, ...]]:
    table: dict[str, tuple[datetime, ...]] = {}
    monkeypatch.setattr(ev_common, "announcements", lambda: table)
    return table


def test_an_announcement_after_the_close_counts_from_the_next_day(
    known: dict[str, tuple[datetime, ...]],
) -> None:
    known["A"] = (datetime(2023, 5, 10, 16, 5, tzinfo=IST),)
    assert ev.known_by("A", date(2023, 5, 10)) == []
    assert ev.known_by("A", date(2023, 5, 11)) == [date(2023, 5, 11)]
    known["B"] = (datetime(2023, 5, 10, 11, 0, tzinfo=IST),)
    assert ev.known_by("B", date(2023, 5, 10)) == [date(2023, 5, 10)]


def _rows(symbol: str, start: date, closes: list[float]) -> list[PanelRow]:
    return [
        PanelRow(day=start + timedelta(days=i), symbol=symbol, close=c, volume=1.0, turnover=1e9)
        for i, c in enumerate(closes)
    ]


def test_a_stock_due_to_report_is_held(
    known: dict[str, tuple[datetime, ...]], monkeypatch: pytest.MonkeyPatch
) -> None:
    today = date(2024, 5, 6)
    known["DUE"] = (datetime(2023, 5, 10, 11, 0, tzinfo=IST),)  # expected 2024-05-08
    known["LATER"] = (datetime(2023, 7, 10, 11, 0, tzinfo=IST),)
    monkeypatch.setattr(premium, "liquid_universe", lambda view: ["DUE", "LATER"])
    view = MarketView(as_of=today, history={})
    held = ev.AnnouncementPremium("x").target_weights(view)
    assert set(held) == {"DUE"}


def test_drift_buys_the_best_reaction(
    known: dict[str, tuple[datetime, ...]], monkeypatch: pytest.MonkeyPatch
) -> None:
    start = date(2024, 1, 1)
    flat = [100.0] * 40
    history = {"NIFTYBEES": _rows("NIFTYBEES", start, flat)}
    names = [f"S{i}" for i in range(10)]
    for i, name in enumerate(names):
        closes = [100.0] * 10 + [100.0 + i] * 30  # reaction of i% on day 10
        history[name] = _rows(name, start, closes)
        known[name] = (datetime(2024, 1, 11, 11, 0, tzinfo=IST),)
    monkeypatch.setattr(drift, "liquid_universe", lambda view: names)
    view = MarketView(as_of=start + timedelta(days=39), history=history)
    held = ev.AnnouncementDrift("x").target_weights(view)
    assert set(held) == {"S9", "S8"}, "the top fifth of ten"


def test_an_explicit_window_is_kept_with_a_year_of_warmup() -> None:
    """2026-10-18: the daily batch ignored --from/--to and ran the whole panel."""
    from eulerlab.api import server

    start = date(2020, 1, 1)
    rows = [
        PanelRow(day=start + timedelta(days=i), symbol="X", close=1.0, volume=1.0, turnover=1.0)
        for i in range(1000)
    ]
    kept = server.windowed(rows, date(2021, 6, 1), date(2021, 12, 31))
    days = [r.day for r in kept]
    assert max(days) == date(2021, 12, 31)
    assert min(days) == date(2021, 6, 1) - timedelta(days=server.WINDOW_WARMUP)
