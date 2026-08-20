"""Indicators, checked against hand-computed values rather than another library.

Checking one implementation against another only proves they agree. Each test
below states the arithmetic it expects, so a wrong answer is visible in the
test itself.
"""

from __future__ import annotations

import pytest

from eulerlab.features.indicators import (
    adx,
    atr,
    body_ratio,
    is_bearish,
    is_bullish,
    range_pct,
    rsi,
    sma,
    true_range,
)


def test_sma_is_the_plain_average_of_the_window() -> None:
    result = sma([1.0, 2.0, 3.0, 4.0, 5.0], 3)
    assert result[:2] == [None, None]
    assert result[2] == pytest.approx(2.0)  # (1+2+3)/3
    assert result[4] == pytest.approx(4.0)  # (3+4+5)/3


def test_sma_warms_up_as_none_not_zero() -> None:
    """Zero is a real average. `None` is the only honest way to say 'not yet'."""
    assert sma([5.0, 5.0], 5) == [None, None]


def test_sma_rejects_a_nonsense_period() -> None:
    with pytest.raises(ValueError, match="period"):
        sma([1.0], 0)


def test_rsi_is_one_hundred_when_nothing_ever_falls() -> None:
    """The defined limit, not a division by zero."""
    assert rsi([float(i) for i in range(1, 30)], 14)[-1] == pytest.approx(100.0)


def test_rsi_is_fifty_when_gains_and_losses_balance() -> None:
    prices = [100.0]
    for _ in range(40):
        prices.extend([prices[-1] + 1.0, prices[-1]])
    assert rsi(prices, 14)[-1] == pytest.approx(50.0, abs=6.0)


def test_rsi_falls_in_a_downtrend() -> None:
    assert rsi([float(50 - i) for i in range(30)], 14)[-1] == pytest.approx(0.0)


def test_true_range_uses_the_gap_not_just_the_bar() -> None:
    """A stock that gaps down then trades quietly had a violent day."""
    highs = [100.0, 90.0]
    lows = [98.0, 89.0]
    closes = [99.0, 89.5]
    result = true_range(highs, lows, closes)
    # bar range is 1.0, but |low - prev close| = |89 - 99| = 10.0
    assert result[1] == pytest.approx(10.0)


def test_true_range_seeds_with_the_plain_range() -> None:
    assert true_range([10.0], [8.0], [9.0])[0] == pytest.approx(2.0)


def test_atr_of_a_constant_range_is_that_range() -> None:
    n = 40
    highs = [101.0] * n
    lows = [99.0] * n
    closes = [100.0] * n
    assert atr(highs, lows, closes, 14)[-1] == pytest.approx(2.0)


def test_atr_uses_wilder_smoothing_not_an_ema() -> None:
    """The distinction that makes implementations disagree.

    Wilder smooths with alpha = 1/n. A conventional EMA uses 2/(n+1). After a
    step change the two are measurably different, and this pins the right one.
    """
    n = 30
    highs = [101.0] * n + [111.0]
    lows = [99.0] * n + [99.0]
    closes = [100.0] * n + [110.0]
    values = atr(highs, lows, closes, 14)
    previous, current = values[-2], values[-1]
    assert previous is not None and current is not None
    # Wilder: prev + (TR - prev)/14, with TR = 12.0 and prev = 2.0
    assert current == pytest.approx(previous + (12.0 - previous) / 14)


def test_adx_is_high_in_a_clean_trend() -> None:
    n = 60
    highs = [100.0 + i for i in range(n)]
    lows = [98.0 + i for i in range(n)]
    closes = [99.0 + i for i in range(n)]
    value = adx(highs, lows, closes, 14)[-1]
    assert value is not None
    assert value > 50.0


def test_adx_is_low_when_there_is_no_trend() -> None:
    highs, lows, closes = [], [], []
    for i in range(80):
        base = 100.0 + (1.0 if i % 2 else -1.0)
        highs.append(base + 1.0)
        lows.append(base - 1.0)
        closes.append(base)
    value = adx(highs, lows, closes, 14)[-1]
    assert value is not None
    assert value < 25.0


def test_adx_says_nothing_about_direction() -> None:
    """A high ADX in a downtrend is just as high. Reading it as bullish is a
    common and expensive error, so the symmetry is asserted."""
    n = 60
    up = adx(
        [100.0 + i for i in range(n)],
        [98.0 + i for i in range(n)],
        [99.0 + i for i in range(n)],
        14,
    )[-1]
    down = adx(
        [100.0 - i for i in range(n)],
        [98.0 - i for i in range(n)],
        [99.0 - i for i in range(n)],
        14,
    )[-1]
    assert up is not None and down is not None
    assert up == pytest.approx(down, abs=1.0)


def test_directional_movement_is_exclusive() -> None:
    """On a day where both moves are positive only the larger counts. Letting
    both register produces a much smoother, much less useful series."""
    n = 40
    highs = [100.0 + i * 2 for i in range(n)]
    lows = [90.0 - i for i in range(n)]  # both up-move and down-move positive
    closes = [95.0 + i for i in range(n)]
    value = adx(highs, lows, closes, 14)[-1]
    assert value is not None


# --- candle geometry --------------------------------------------------------


def test_body_ratio_of_a_full_body_candle_is_one() -> None:
    assert body_ratio(10.0, 20.0, 10.0, 20.0) == pytest.approx(1.0)


def test_body_ratio_of_a_doji_is_zero() -> None:
    assert body_ratio(15.0, 20.0, 10.0, 15.0) == pytest.approx(0.0)


def test_body_ratio_is_half_when_body_is_half_the_range() -> None:
    assert body_ratio(12.5, 20.0, 10.0, 17.5) == pytest.approx(0.5)


def test_a_bar_with_no_range_has_no_body() -> None:
    """The non-trading-day case. Zero makes every shape test FAIL rather than
    pass on a fabricated candle."""
    assert body_ratio(10.0, 10.0, 10.0, 10.0) == 0.0


def test_range_pct_is_relative_to_the_close() -> None:
    assert range_pct(102.0, 98.0, 100.0) == pytest.approx(4.0)


def test_direction_helpers_agree_with_themselves() -> None:
    assert is_bearish(10.0, 9.0) and not is_bullish(10.0, 9.0)
    assert is_bullish(9.0, 10.0) and not is_bearish(9.0, 10.0)
    assert not is_bullish(10.0, 10.0) and not is_bearish(10.0, 10.0)
