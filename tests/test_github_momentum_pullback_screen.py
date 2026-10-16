from __future__ import annotations

from datetime import date

from eulerlab.intraday.github_momentum_pullback_screen import _exit, _positive_macd, _signal
from eulerlab.intraday.india_papers import Day


def _day_with_surge_pullback_breakout() -> Day:
    size = 375
    opens: list[float | None] = [None] * size
    highs: list[float | None] = [None] * size
    lows: list[float | None] = [None] * size
    closes = [100.0] * size
    volumes = [100.0] * size
    prices = {
        21: 100.3,
        22: 100.6,
        23: 100.9,
        24: 101.2,
        25: 101.5,
        26: 101.8,
        27: 102.1,
        28: 102.4,
        29: 102.7,
        30: 103.0,
        31: 102.8,
        32: 102.6,
        33: 102.5,
        34: 102.7,
        35: 103.1,
    }
    for minute in range(1, size):
        close = prices.get(minute, 103.1 if minute > 35 else 100.0)
        previous = closes[minute - 1]
        opens[minute] = previous
        closes[minute] = close
        highs[minute] = max(previous, close) + 0.05
        lows[minute] = min(previous, close) - 0.05
    opens[35], highs[35], lows[35], closes[35] = 102.8, 103.2, 102.7, 103.1
    volumes[34] = volumes[35] = 200.0
    return Day(
        day=date(2024, 1, 2),
        open_=tuple(opens),
        high=tuple(highs),
        low=tuple(lows),
        close=tuple(closes),
        volume=tuple(volumes),
        last=374,
    )


def test_source_derived_surge_pullback_breakout_finds_next_open_entry() -> None:
    day = _day_with_surge_pullback_breakout()

    signal = _signal(day, _positive_macd(day.close[: day.last + 1]))

    assert signal is not None
    assert signal["signal_minute"] == 35
    assert signal["entry_minute"] == 36
    assert signal["stop"] < signal["entry"]


def test_same_bar_stop_and_target_is_resolved_conservatively() -> None:
    day = _day_with_surge_pullback_breakout()
    highs = list(day.high)
    lows = list(day.low)
    highs[36], lows[36] = 130.0, 90.0
    day = Day(
        day=day.day,
        open_=day.open_,
        high=tuple(highs),
        low=tuple(lows),
        close=day.close,
        volume=day.volume,
        last=day.last,
    )

    assert _exit(
        day,
        {"entry_minute": 36, "stop": 99.0, "target": 120.0},
    ) == (36, 99.0, "stop_first")
