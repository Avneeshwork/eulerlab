"""`_sma_tail` is an exact bound, not an approximation — this proves it.

A simple moving average at bar `i` depends on exactly `period` closes and
nothing earlier, so in exact arithmetic the bound costs nothing — which
distinguishes it from the ATR bound next door, a real approximation good to
about 1e-9 and documented as one.

In float64 the two forms differ in the last bits, because `sma` keeps a running
sum whose rounding error grows with how many bars it has walked. These tests
assert agreement at that scale rather than bit equality, and one of them pins
down the direction: the **bounded** value is the more accurate one, having
walked seventy-odd bars rather than a hundred thousand.
"""

from __future__ import annotations

import datetime as dt
import random

from eulerlab.features.indicators import sma
from eulerlab.intraday.papers import _closes, _sma_tail
from eulerlab.intraday.tweezer import Candle


def _walk(count: int, seed: int = 5) -> list[Candle]:
    rng = random.Random(seed)
    price = 100.0
    start = dt.datetime(2026, 6, 1, tzinfo=dt.UTC)
    out: list[Candle] = []
    for i in range(count):
        price = max(1.0, price * (1.0 + rng.gauss(0, 0.002)))
        out.append(
            Candle(
                ts=start + dt.timedelta(minutes=i),
                open=price,
                high=price + 0.5,
                low=price - 0.5,
                close=price,
                volume=abs(rng.gauss(1000, 100)),
            )
        )
    return out


def test_last_value_matches_the_whole_window() -> None:
    window = _walk(10_000)
    for period in (5, 14, 20, 60):
        full = sma(_closes(window), period)[-1]
        tail = _sma_tail(window, period)[-1]
        assert full is not None and tail is not None
        assert abs(full - tail) / full < 1e-12, f"period {period}"


def test_a_deeper_tail_matches_across_every_value_it_returns() -> None:
    """`trend_pullback` reads a value 20 bars back as well as the last one."""
    window = _walk(10_000, seed=9)
    period, back = 60, 21
    full = sma(_closes(window), period)
    tail = _sma_tail(window, period, back=back)
    for index in (-1, -20):
        a, b = full[index], tail[index]
        assert a is not None and b is not None
        assert abs(a - b) / a < 1e-12, f"index {index}"


def test_short_windows_are_bit_identical() -> None:
    """Shorter than the tail means the slice is a genuine no-op — same list.

    "Short" is against `period + back`, not against `period`: at 30 bars with a
    20-period mean the tail is still 21 bars and the lists differ in length,
    which is the shape the callers index into rather than compare.
    """
    window = _walk(15)
    assert _sma_tail(window, 20) == sma(_closes(window), 20)


def test_the_returned_tail_is_deep_enough_for_both_readings() -> None:
    """`trend_pullback` indexes `[-1]` and `[-expansion_lookback]`.

    The tail must therefore carry a real value at the deeper index, not a None
    left over from the moving average's own warmup — a None there reads as "no
    uptrend" and would silently switch the signal off.
    """
    window = _walk(10_000)
    ou_lookback, expansion_lookback = 60, 20
    trend = _sma_tail(window, ou_lookback, back=expansion_lookback + 1)
    assert len(trend) > expansion_lookback
    assert trend[-1] is not None
    assert trend[-expansion_lookback] is not None


def test_it_does_not_read_more_history_than_it_needs() -> None:
    """Prepending unrelated history leaves the answer alone.

    Bit-identical here, unlike the comparisons against the whole-window form:
    both sides of this equality walk the same short tail, so neither carries
    the running-sum drift that separates them from `sma` over everything.
    """
    window = _walk(500, seed=1)
    prefix = _walk(5_000, seed=2)
    assert _sma_tail(window, 20)[-1] == _sma_tail([*prefix, *window], 20)[-1]


def test_the_bounded_value_is_the_less_drifted_one() -> None:
    """Which of the two is nearer the truth, computed exactly for comparison.

    The rolling sum in `sma` accumulates error in proportion to the bars it
    walks, so the whole-window figure is the drifted one. Worth pinning down:
    a bound that quietly traded accuracy for speed would be a different and
    much less comfortable change than one that improves both.
    """
    from fractions import Fraction

    window = _walk(120_000, seed=4)
    period = 14
    exact = float(sum(Fraction(c.close) for c in window[-period:]) / period)

    full = sma(_closes(window), period)[-1]
    tail = _sma_tail(window, period)[-1]
    assert full is not None and tail is not None
    assert abs(tail - exact) <= abs(full - exact)
