from __future__ import annotations

from datetime import date

from eulerlab.intraday import india_papers as ip
from eulerlab.strategies.studies import supertrend_alignment as screen


def _bar(index: int, close: float, *, volume: float = 10.0) -> screen.Bar:
    return screen.Bar(index * 15, (index + 1) * 15, close, close + 0.2, close - 0.2, close, volume)


def test_supertrend_waits_for_atr_warmup_then_tracks_uptrend() -> None:
    bars = [_bar(index, 100 + index) for index in range(20)]

    state = screen._supertrend(bars)

    assert state[: screen.ATR_PERIOD - 1] == [(0, None)] * (screen.ATR_PERIOD - 1)
    assert state[-1][0] == 1
    assert state[-1][1] is not None
    assert state[-1][1] < bars[-1].close


def test_supertrend_flips_bearish_after_close_breaks_final_lower_band() -> None:
    bars = [_bar(index, 100 + index * 0.5) for index in range(20)]
    bars.extend(_bar(index, price) for index, price in enumerate([95, 90, 85, 80], start=20))

    state = screen._supertrend(bars)

    assert state[-1][0] == -1
    assert state[-1][1] is not None
    assert state[-1][1] > bars[-1].close


def test_volume_filter_requires_cross_above_trailing_mean() -> None:
    bars = [_bar(index, 100, volume=10) for index in range(screen.VOLUME_PERIOD + 1)]
    bars[-1] = _bar(len(bars) - 1, 100, volume=100)

    assert screen._volume_cross(bars, len(bars) - 1)

    bars[-2] = _bar(len(bars) - 2, 100, volume=20)
    assert not screen._volume_cross(bars, len(bars) - 1)


def test_bar_aggregation_excludes_09_15_print_and_keeps_real_volume() -> None:
    values = [100.0] * ip.MINUTES
    opens = tuple(values)
    highs = tuple(value + 1 for value in values)
    lows = tuple(value - 1 for value in values)
    closes = tuple(values)
    volumes = tuple(1.0 for _ in values)
    day = ip.Day(date(2024, 1, 2), opens, highs, lows, closes, volumes, ip.MINUTES - 1)

    bars = screen._bars(day, 15)

    assert bars[0].start == 0
    assert bars[0].end == 15
    assert bars[0].volume == 14
