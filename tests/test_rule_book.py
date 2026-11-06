"""Paper books for the gated intraday rules (ADR-142)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest

from eulerlab.deploy import rule_book
from eulerlab.intraday import india_papers as ip

N = 375
MON = date(2026, 11, 2)


def _day(when: date, open_first: float, rest: float, *, prev_close: float | None = None) -> ip.Day:
    closes = [open_first] * 5 + [rest] * (N - 5)
    opens = [open_first, *closes[:-1]]
    if prev_close is not None:
        closes = [prev_close] * 5 + [rest] * (N - 5)
        opens = [prev_close, *closes[:-1]]
    return ip.Day(
        when,
        tuple(opens),
        tuple(closes),
        tuple(closes),
        tuple(closes),
        tuple([100.0] * N),
        N - 1,
    )


def test_only_stocks_new_to_the_ban_are_entries() -> None:
    lists = {MON: {"A"}, MON + timedelta(days=1): {"A", "B"}, MON + timedelta(days=2): {"B", "C"}}
    found = rule_book.first_ban_days(lists, after=MON)
    assert found == {MON + timedelta(days=1): ["B"], MON + timedelta(days=2): ["C"]}


def test_ban_shorts_are_sized_into_ten_slots_and_enter_at_0920() -> None:
    day = MON
    load: dict[str, list[Any]] = {"A": [_day(day, 100.0, 95.0)]}
    trades, sessions = rule_book.ban_trades(
        {day: ["A"]}, lambda s: load.get(s, []), 1_000_000.0, auction=False
    )
    (trade,) = trades
    assert trade["direction"] == -1 and trade["minute"] == rule_book.ENTRY
    assert trade["quantity"] == int(100_000 / trade["entry"])
    assert sessions == [day]


def test_the_auction_variant_enters_on_the_0915_print() -> None:
    load = {"A": [_day(MON, 100.0, 95.0)]}
    trades, _ = rule_book.ban_trades({MON: ["A"]}, lambda s: load[s], 1_000_000.0, auction=True)
    (trade,) = trades
    assert trade["minute"] == 0 and trade["entry"] == 100.0 and trade["exit"] == 95.0


def test_at_most_ten_ban_shorts_a_day() -> None:
    names = [f"S{i:02d}" for i in range(12)]
    load = {s: [_day(MON, 100.0, 99.0)] for s in names}
    trades, _ = rule_book.ban_trades({MON: names}, lambda s: load[s], 1_000_000.0, auction=False)
    assert len(trades) == rule_book.SLOTS


def test_overnight_reversal_needs_twenty_sessions_and_a_hundred_names() -> None:
    days = [MON + timedelta(days=i) for i in range(40) if (MON + timedelta(days=i)).weekday() < 5]
    book: dict[str, list[Any]] = {}
    for n in range(110):
        drift = 1.0 + n / 10_000  # higher n: larger overnight gains
        series, price = [], 100.0
        for d in days:
            opened = price * drift
            series.append(_day(d, opened, opened, prev_close=opened))
            price = opened
        book[f"S{n:03d}"] = series
    trades, sessions = rule_book.overnight_trades(book, start=days[0], capital=8_000_000.0)
    first = min(t["day"] for t in trades)
    assert first == days[rule_book.LOOKBACK + 1]  # the first session has no previous close
    today = [t for t in trades if t["day"] == first]
    shorts = {t["symbol"] for t in today if t["direction"] == -1}
    longs = {t["symbol"] for t in today if t["direction"] == 1}
    assert len(shorts) == len(longs) == 11
    assert "S109" in shorts and "S000" in longs
    assert sessions == days


def test_pre_holiday_sessions_come_from_the_nse_list() -> None:
    holidays = frozenset({date(2026, 11, 10), date(2026, 11, 9)})  # Tue; Mon
    assert rule_book.pre_holiday(date(2026, 11, 6), holidays)  # Fri before Mon 9th
    assert not rule_book.pre_holiday(date(2026, 11, 11), holidays)
    days = [_day(date(2026, 11, 6), 250.0, 251.0), _day(date(2026, 11, 11), 250.0, 251.0)]
    trades, _ = rule_book.holiday_trades(
        days, holidays, start=date(2026, 11, 1), capital=1_000_000.0
    )
    (trade,) = trades
    assert trade["symbol"] == rule_book.ETF and trade["direction"] == 1


def test_only_a_promote_or_paper_verdict_may_paper_trade(monkeypatch: pytest.MonkeyPatch) -> None:
    from eulerlab import forward
    from eulerlab.deploy import intraday_book

    monkeypatch.setattr(intraday_book, "holdout_end", lambda: date(2026, 10, 17))
    monkeypatch.setattr(
        forward,
        "verdicts",
        lambda *a, **k: {
            "H-0096": ("PROMOTE", MON),
            "H-0065": ("PAPER", MON),
            "H-0052": ("KILL", MON),
        },
    )
    assert rule_book.blocker("H-0096") == ""
    assert rule_book.blocker("H-0065") == ""
    assert "KILL" in rule_book.blocker("H-0052")
    assert "missing" in rule_book.blocker("H-0098")
    assert "not an intraday rule" in rule_book.blocker("H-0001")


def test_the_runner_routes_rules_to_their_book(monkeypatch: pytest.MonkeyPatch) -> None:
    from eulerlab.deploy import runner

    monkeypatch.setattr(rule_book, "blocker", lambda s: f"checked {s}")
    assert runner.paper_blocker("H-0096") == "checked H-0096"


def test_the_version_lock_covers_the_rule_code() -> None:
    from eulerlab.deploy import version_lock

    texts = version_lock.sources("H-0096")
    assert len(texts) == 3 and "def h0096" in texts[1]


def test_the_auction_variant_exits_when_the_data_ends_at_1514() -> None:
    """These stocks' minute files end at 15:14 (last bar 359); the cover must exist."""
    bars = _day(MON, 100.0, 95.0)
    short = ip.Day(
        MON, bars.open_[:360] + (None,) * 15, bars.high, bars.low, bars.close, bars.volume, 359
    )
    trades, _ = rule_book.ban_trades({MON: ["A"]}, lambda s: [short], 1_000_000.0, auction=True)
    assert len(trades) == 1 and trades[0]["exit"] == 95.0
