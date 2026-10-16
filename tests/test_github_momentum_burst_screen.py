from __future__ import annotations

from datetime import date

from eulerlab.intraday.github_momentum_burst_screen import _atr, _burst, _exit, _run
from eulerlab.intraday.india_papers import Day
from eulerlab.intraday.inside_bar_screen import Bar


def test_atr_warmup_and_three_interval_burst() -> None:
    bars = [Bar(5 * i, 100, 101, 99, 100, 100) for i in range(15)]
    bars.append(Bar(75, 100, 111, 99, 110, 100))
    values = _atr(bars, period=14)
    assert values[:14] == [None] * 14
    assert values[14] is not None
    assert _burst(bars, values, 15) == 1


def test_stop_is_checked_on_entry_bar_and_fills_at_stop() -> None:
    bars = [Bar(10, 100, 102, 98, 101, 10)]
    assert _exit(bars, [2.0], 0, 1, 99.0) == (10, 99.0, "stop")


def test_github_burst_rule_enters_next_bar_and_flattens_at_1500() -> None:
    bar_values = [(100.0, 101.0, 99.0, 100.0)] * 16
    bar_values += [(100.0, 111.0, 99.5, 110.0)]
    bar_values += [(110.2, 111.0, 109.5, 110.0)] * (70 - len(bar_values))
    opens: list[float | None] = [100.0] * 360
    highs: list[float | None] = [100.0] * 360
    lows: list[float | None] = [100.0] * 360
    closes: list[float | None] = [100.0] * 360
    volumes: list[float | None] = [100.0] * 360
    for index, (open_, high, low, close) in enumerate(bar_values):
        start = 5 + index * 5
        for minute in range(start, start + 5):
            opens[minute], highs[minute], lows[minute], closes[minute] = open_, high, low, close
            volumes[minute] = 1000.0 if index == 16 else 100.0
    day = Day(
        date(2024, 1, 2),
        tuple(opens),
        tuple(highs),
        tuple(lows),
        tuple(value if value is not None else 0.0 for value in closes),
        tuple(value if value is not None else 0.0 for value in volumes),
        359,
    )

    result = _run({"RELIANCE": [day]})

    assert result["trades"] == 1
    trade = result["trade_log"][0]
    assert trade["side"] == "long"
    assert trade["signal_minute"] == 85
    assert trade["entry_minute"] == 90
    assert trade["exit_minute"] == 345
    assert trade["exit_reason"] == "time_exit"
