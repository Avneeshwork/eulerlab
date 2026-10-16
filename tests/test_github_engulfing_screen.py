from __future__ import annotations

from datetime import date

from eulerlab.intraday.github_engulfing_screen import _engulfing, _rsi, _run
from eulerlab.intraday.india_papers import Day
from eulerlab.intraday.inside_bar_screen import Bar


def test_engulfing_requires_opposite_candle_colors_and_body_engulfment() -> None:
    bearish = Bar(5, 101.0, 102.0, 99.0, 100.0, 10.0)
    bullish = Bar(10, 99.0, 103.0, 98.0, 102.0, 20.0)
    assert _engulfing(bearish, bullish) == 1
    bullish_previous = Bar(5, 100.0, 103.0, 99.0, 102.0, 10.0)
    bearish_current = Bar(10, 103.0, 104.0, 98.0, 99.0, 20.0)
    assert _engulfing(bullish_previous, bearish_current) == -1
    assert _engulfing(bearish, Bar(10, 100.5, 102.0, 100.0, 101.0, 20.0)) == 0


def test_rsi_wilder_smoothing_has_no_early_value() -> None:
    result = _rsi([float(20 - i) for i in range(16)], period=14)
    assert result[:14] == [None] * 14
    assert result[14] == 0.0
    assert result[15] == 0.0


def test_fixed_rule_enters_next_bar_and_squares_off() -> None:
    prices = [(120.0 - i, 119.0 - i, 118.5 - i, 119.0 - i) for i in range(19)]
    prices += [(101.0, 101.5, 99.5, 100.0), (99.0, 103.0, 98.0, 102.0)]
    prices += [(102.0, 102.2, 101.8, 102.0)] * (70 - len(prices))
    opens: list[float | None] = [100.0] * 360
    highs: list[float | None] = [100.0] * 360
    lows: list[float | None] = [100.0] * 360
    closes: list[float | None] = [100.0] * 360
    volumes: list[float | None] = [100.0] * 360
    for bar_index, (open_, high, low, close) in enumerate(prices):
        start = 5 + bar_index * 5
        for minute in range(start, start + 5):
            opens[minute], highs[minute], lows[minute], closes[minute] = open_, high, low, close
            volumes[minute] = 1000.0 if bar_index == 20 else 100.0
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
    assert trade["signal_minute"] == 105
    assert trade["entry_minute"] == 110
    assert trade["exit_minute"] == 355
    assert trade["exit_reason"] == "time_exit"
