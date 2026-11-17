from __future__ import annotations

from datetime import date

from eulerlab.intraday.india_papers import Day
from eulerlab.strategies.studies.github_keltner import _run


def test_keltner_close_break_enters_next_bar_and_flattens_intraday() -> None:
    closes = tuple(100.0 + 0.04 * minute for minute in range(360))
    opens = closes
    highs = tuple(value + 0.03 for value in closes)
    lows = tuple(value - 0.03 for value in closes)
    day = Day(date(2024, 1, 2), opens, highs, lows, closes, (100.0,) * 360, 359)

    result = _run({"RELIANCE": [day]})

    assert result["trades"] == 1
    trade = result["trade_log"][0]
    assert trade["entry_minute"] > 5
    assert trade["exit_minute"] == 355
    assert trade["exit_reason"] == "time_exit"
    assert trade["gross_pnl"] > 0
