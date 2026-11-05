"""Research 160: intraday news rules (H-0072 to H-0076)."""

from __future__ import annotations

from datetime import date, datetime

from eulerlab.intraday import india_papers as ip
from eulerlab.intraday import news_screen as news

IST = news.IST

N = 375


def _day(closes: list[float], when: date) -> ip.Day:
    closes = closes + [closes[-1]] * (N - len(closes))
    prices = tuple(closes)
    return ip.Day(when, prices, prices, prices, prices, tuple([100.0] * N), N - 1)


def test_categories_and_times_are_read_from_raw_rows() -> None:
    rows = [
        {"symbol": "A", "desc": "Press Release", "exchdisstime": "04-May-2023 11:02:10"},
        {"symbol": "A", "desc": "Trading Window", "exchdisstime": "04-May-2023 11:03:00"},
        {"symbol": "B", "desc": "Buyback", "exchdisstime": "03-May-2023 18:30:00"},
    ]
    events = news.load_events(rows)
    assert events["A"] == {"press": [datetime(2023, 5, 4, 11, 2, 10, tzinfo=IST)]}
    assert list(events["B"]) == ["buyback"]


def test_a_press_release_with_a_one_percent_move_is_followed() -> None:
    day = date(2023, 5, 4)
    minute = news._minute(datetime(2023, 5, 4, 11, 2, tzinfo=IST))
    closes = [100.0] * minute + [101.5] * 30
    marks = news.marks_for(
        [_day(closes, day)], {"press": [datetime(2023, 5, 4, 11, 2, tzinfo=IST)]}
    )
    fill = marks["press"][day]
    assert fill.direction == 1 and fill.entry_minute == minute + 5


def test_an_overnight_buyback_is_bought_at_the_next_0920_open() -> None:
    days = [_day([100.0] * 10, date(2023, 5, 3)), _day([100.0] * 10, date(2023, 5, 4))]
    marks = news.marks_for(days, {"buyback": [datetime(2023, 5, 3, 18, 30, tzinfo=IST)]})
    fill = marks["buyback"][date(2023, 5, 4)]
    assert fill.entry_minute == news.DAY_START and fill.minute == news.PRE_OPEN


def test_a_dividend_in_hours_is_bought_the_next_minute() -> None:
    day = date(2023, 5, 4)
    marks = news.marks_for(
        [_day([100.0] * 10, day)], {"dividend": [datetime(2023, 5, 4, 10, 0, tzinfo=IST)]}
    )
    assert (
        marks["dividend"][day].entry_minute
        == news._minute(datetime(2023, 5, 4, 10, 0, tzinfo=IST)) + 1
    )
