from __future__ import annotations

from datetime import date, timedelta

from eulerlab.intraday.india_papers import Day
from eulerlab.intraday.screen_common import rsi as _rsi
from eulerlab.strategies.studies.github_rsi2_pullback import RSI_PERIOD, _run, _sma


def _day(when: date, closes: list[float] | None = None) -> Day:
    closes = closes or [90.0] * 70
    opens: list[float | None] = [90.0] * 360
    highs: list[float | None] = [90.5] * 360
    lows: list[float | None] = [89.5] * 360
    minute_closes: list[float | None] = [90.0] * 360
    volumes: list[float | None] = [100.0] * 360
    for index, close in enumerate(closes):
        start = 5 + index * 5
        open_ = closes[index - 1] if index else close
        for minute in range(start, start + 5):
            opens[minute] = open_
            highs[minute] = max(open_, close) + 0.5
            lows[minute] = min(open_, close) - 0.5
            minute_closes[minute] = close
    last_close = closes[-1]
    for minute in range(355, 360):
        opens[minute] = last_close
        highs[minute] = last_close + 0.5
        lows[minute] = last_close - 0.5
        minute_closes[minute] = last_close
    return Day(
        when,
        tuple(opens),
        tuple(highs),
        tuple(lows),
        tuple(value if value is not None else 90.0 for value in minute_closes),
        tuple(value if value is not None else 0.0 for value in volumes),
        359,
    )


def test_rsi2_warmup_and_sma_values() -> None:
    rsi = _rsi([10.0, 9.0, 8.0, 7.0], RSI_PERIOD)
    assert rsi[:2] == [None, None]
    assert rsi[2] == 0.0 and rsi[3] == 0.0
    assert _sma([1.0, 2.0, 3.0, 4.0], 3) == [None, None, 2.0, 3.0]


def test_connors_rsi2_adaptation_enters_and_exits_on_next_bar() -> None:
    start = date(2023, 12, 1)
    data = [_day(start + timedelta(days=index)) for index in range(3)]
    session_closes = [100.0, 99.0, 98.0, 97.0, 96.0, 95.0, 94.0, 93.0, 92.0, 100.0]
    session_closes += [100.0] * 60
    data.append(_day(date(2024, 1, 2), session_closes))

    result = _run({"RELIANCE": data})

    assert result["trades"] == 1
    trade = result["trade_log"][0]
    assert trade["side"] == "long"
    assert trade["signal_minute"] == 35
    assert trade["entry_minute"] == 40
    assert trade["exit_minute"] == 55
    assert trade["exit_reason"] == "fast_sma_exit_next_open"
