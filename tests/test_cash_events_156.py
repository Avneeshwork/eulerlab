"""Research 156: drift bursts and calendar days (H-0051 to H-0055)."""

from __future__ import annotations

from datetime import date

from eulerlab.intraday import cash_events_screen as events
from eulerlab.intraday import india_papers as ip

N = 375


def _day(closes: list[float], *, when: date = date(2023, 5, 4), volume: float = 100.0) -> ip.Day:
    closes = closes + [closes[-1]] * (N - len(closes))
    prices = tuple(closes)
    return ip.Day(when, prices, prices, prices, prices, tuple([volume] * N), N - 1)


def test_a_three_percent_fall_inside_thirty_minutes_is_bought_next_minute() -> None:
    closes = [100.0] * 50 + [98.0] * 5 + [96.9] * 10
    fill = events.burst(_day(closes), 0.03)
    assert fill is not None and fill.minute == 55 and fill.entry_minute == 56
    assert fill.direction == 1


def test_a_burst_on_ordinary_volume_is_not_bought() -> None:
    closes = [100.0] * 50 + [96.0] * 10
    # 30 minutes of 100 shares is 3,000, under 3 x a norm of 1,500.
    assert events.burst(_day(closes), 0.03, volume_norm=1_500.0) is None
    assert events.burst(_day(closes), 0.03, volume_norm=100.0) is not None


def test_pre_holiday_sessions_are_those_before_a_missing_weekday() -> None:
    sessions = [
        date(2023, 3, 6),
        date(2023, 3, 8),
        date(2023, 3, 9),
        date(2023, 3, 10),
        date(2023, 3, 13),
    ]
    # 7 March (Tuesday) is missing: 6 March is a pre-holiday session; Friday 10th before Monday is not.
    assert events.pre_holiday_days(sessions) == [date(2023, 3, 6)]


def test_turn_of_month_is_the_last_session_and_the_first_three() -> None:
    sessions = [date(2023, 1, d) for d in (27, 30, 31)] + [date(2023, 2, d) for d in (1, 2, 3, 6)]
    assert events.turn_of_month_days(sessions) == [
        date(2023, 1, 31),
        date(2023, 2, 1),
        date(2023, 2, 2),
        date(2023, 2, 3),
    ]


def test_results_evenings_count_only_after_the_close_on_a_session() -> None:
    rows = [
        {"symbol": "A", "knowledge_time": "2023-05-04T16:05:00+05:30"},
        {"symbol": "B", "knowledge_time": "2023-05-04T13:00:00+05:30"},
        {"symbol": "C", "knowledge_time": "2023-05-06T18:00:00+05:30"},
    ]
    found = events.results_evenings(rows, [date(2023, 5, 4), date(2023, 5, 5)])
    assert found == {"A": {date(2023, 5, 4)}}
