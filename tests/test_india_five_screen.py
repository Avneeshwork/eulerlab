"""The five research-112 rules on hand-built sessions: what triggers, where it fills."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta

from eulerlab.intraday import cross_section as cs
from eulerlab.intraday import delivery_spike_screen as delivery
from eulerlab.intraday import earnings_reaction_screen as earnings
from eulerlab.intraday import expiry_pinning_screen as pinning
from eulerlab.intraday import nr7_breakout_screen as nr7
from eulerlab.intraday import overnight_reversal_screen as overnight
from eulerlab.intraday.india_papers import MINUTES, Day


def _day(when: date, price: Callable[[int], float] = lambda m: 100.0, spread: float = 0.5) -> Day:
    closes = tuple(price(m) for m in range(MINUTES))
    return Day(
        when,
        closes,
        tuple(c + spread for c in closes),
        tuple(c - spread for c in closes),
        closes,
        (1000.0,) * MINUTES,
        MINUTES - 1,
    )


def _flat(when: date, level: float) -> Day:
    return _day(when, lambda _: level)


def _days(count: int, start: date = date(2024, 1, 1)) -> list[date]:
    out: list[date] = []
    day = start
    while len(out) < count:
        if day.weekday() < 5:
            out.append(day)
        day += timedelta(days=1)
    return out


def test_overnight_buys_the_worst_gap_and_shorts_the_best() -> None:
    first, second = _days(2)
    marks = {}
    for i in range(100):
        gap = (i - 50) / 1000.0  # from -5% to +4.9%
        days = [_day(first), _flat(second, 100.0 * (1 + gap))]
        marks[f"S{i:03d}"] = overnight.extract(f"S{i:03d}", days)
    run = overnight.evaluate(marks, [first, second])
    sides = {row["symbol"]: row["side"] for row in run["trade_log"]}
    assert run["trades"] == 20
    assert sides["S000"] == "long" and sides["S099"] == "short"
    assert all(row["entry_minute"] == cs.ENTRY_OPEN for row in run["trade_log"])


def test_overnight_skips_a_thin_day() -> None:
    first, second = _days(2)
    marks = {f"S{i}": overnight.extract("x", [_day(first), _day(second)]) for i in range(20)}
    assert overnight.evaluate(marks, [first, second])["trades"] == 0


def test_expiries_are_last_thursdays_moved_back_over_holidays() -> None:
    trading = [d for d in _days(80, date(2024, 1, 1)) if d != date(2024, 3, 28)]
    found = pinning.expiries(date(2024, 1, 1), date(2024, 3, 31), trading)
    assert found == [date(2024, 1, 25), date(2024, 2, 29), date(2024, 3, 27)]


def test_pinning_trades_toward_the_strike_and_leaves_after_touching_it() -> None:
    # 99.0 at 13:29, one percent under a 100 strike; reaches it at 14:00.
    day = _day(date(2024, 1, 25), lambda m: 99.0 if m < 285 else 99.6, spread=0.5)
    found = pinning.mark(day, 100.0)
    assert found is not None and found.direction == 1
    assert found.entry_minute == pinning.SIGNAL_MINUTE
    assert found.reason == "touched_strike" and found.exit_minute == 286


def test_pinning_ignores_a_stock_too_near_or_too_far() -> None:
    assert pinning.mark(_day(date(2024, 1, 25), lambda m: 99.9), 100.0) is None
    assert pinning.mark(_day(date(2024, 1, 25), lambda m: 95.0), 100.0) is None


def test_results_follow_a_large_first_five_minutes_only() -> None:
    disclosed = 60  # 10:15
    jump = _day(date(2024, 5, 2), lambda m: 100.0 if m < disclosed else 102.0)
    quiet = _day(date(2024, 5, 2), lambda m: 100.0 if m < disclosed else 100.5)
    found = earnings.mark(jump, disclosed)
    assert found is not None and found.reaction > 0
    assert found.entry_minute == disclosed + earnings.REACTION
    assert earnings.mark(quiet, disclosed) is None


def test_results_outside_hours_and_in_the_unlabelled_half_year_are_dropped() -> None:
    rows = [
        {"symbol": "A", "knowledge_time": "2024-05-02T10:15:30+05:30"},
        {"symbol": "A", "knowledge_time": "2024-05-03T15:00:00+05:30"},
        {"symbol": "B", "knowledge_time": "2022-08-10T11:00:00+05:30"},
    ]
    assert earnings.events(rows) == {"A": {date(2024, 5, 2): 60}}


def test_nr7_needs_the_narrowest_of_seven_then_follows_the_break() -> None:
    sessions = _days(9)
    days = [_day(d, spread=2.0) for d in sessions[:7]]
    days.append(_day(sessions[7], spread=0.2))  # the narrow day
    days.append(_day(sessions[8], lambda m: 100.0 if m < 40 else 101.0, spread=0.2))
    found = nr7.extract("X", days)
    assert list(found) == [sessions[8]]
    assert found[sessions[8]].direction == 1 and found[sessions[8]].entry_minute == 41


def test_nr7_stop_fills_at_the_stop_or_the_worse_open() -> None:
    day = _day(date(2024, 1, 2), lambda m: 100.0 if m < 40 else (101.0 if m < 60 else 98.0))
    found = nr7.mark(day)
    assert found.reason == "stop" and found.exit == 98.0  # gapped through the 99.5 range low


def test_delivery_spike_uses_yesterdays_figure_and_needs_the_open_to_hold() -> None:
    sessions = _days(24)
    percent = dict.fromkeys(sessions[:22], 20.0)
    percent[sessions[22]] = 50.0  # the spike, on a +3% day
    prices = [100.0] * 22 + [103.0, 104.0]
    days = [_flat(d, p) for d, p in zip(sessions, prices, strict=True)]
    found = delivery.extractor({"X": percent})("X", days)
    assert list(found) == [sessions[23]] and found[sessions[23]].traded
    assert delivery.spikes(percent) == {sessions[22]}
