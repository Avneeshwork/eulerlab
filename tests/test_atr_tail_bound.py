"""ATR is computed from a bounded tail; this checks what that costs in accuracy.

The bound was added because `detect` runs once per bar with every bar so far,
so a whole-history ATR made every signal using it quadratic — `session_momentum`
burned 32 minutes of CPU on 120,960 crypto bars without finishing one parameter
set, and finishes in 51 seconds bounded.

It is a speed bound and only that. These tests exist to pin down what it costs
in accuracy — and one of them exists because the first version of the docstring
also claimed the bound made ATR independent of the study's start date. It does
not, and writing the test is what showed it: whole-history ATR converges to the
identical float64 by roughly 500 bars, so there was never any long-window drift
to remove.
"""

from __future__ import annotations

import datetime as dt
import random

from eulerlab.features.indicators import atr
from eulerlab.intraday.tweezer import Candle
from eulerlab.strategies.intraday.papers import ATR_TAIL_PERIODS, _atr_now


def _walk(count: int, seed: int = 7) -> list[Candle]:
    """A random walk with realistic intrabar ranges."""
    rng = random.Random(seed)
    price = 100.0
    out: list[Candle] = []
    start = dt.datetime(2026, 6, 1, tzinfo=dt.UTC)
    for i in range(count):
        price = max(1.0, price * (1.0 + rng.gauss(0, 0.001)))
        span = abs(rng.gauss(0, 0.4)) + 0.05
        out.append(
            Candle(
                ts=start + dt.timedelta(minutes=i),
                open=price,
                high=price + span,
                low=price - span,
                close=price + rng.gauss(0, span / 2),
                volume=abs(rng.gauss(1000, 200)),
            )
        )
    return out


def _full_atr(window: list[Candle], period: int) -> float | None:
    """Whole-history ATR — the value the bound approximates."""
    series = atr(
        [c.high for c in window],
        [c.low for c in window],
        [c.close for c in window],
        period=period,
    )
    return series[-1] if series and series[-1] is not None else None


def test_bounded_atr_matches_whole_history() -> None:
    """Wilder weights the bar n back by (1-1/period)**n, so the tail dominates.

    At period 14 and a 20-period tail the oldest bar retained carries about
    1e-9 of the result. The two values should agree far more closely than a
    price is quoted.
    """
    window = _walk(5_000)
    period = 14
    bounded = _atr_now(window, period)
    full = _full_atr(window, period)
    assert bounded is not None and full is not None
    assert abs(bounded - full) / full < 1e-6


def test_the_bound_holds_across_period_settings() -> None:
    """The sweep varies parameters, so the guarantee must not be period-specific."""
    window = _walk(5_000, seed=11)
    for period in (7, 14, 21, 30):
        bounded = _atr_now(window, period)
        full = _full_atr(window, period)
        assert bounded is not None and full is not None
        assert abs(bounded - full) / full < 1e-4, f"period {period}"


def test_short_windows_are_unaffected() -> None:
    """A window shorter than the tail is used whole — the slice is a no-op."""
    window = _walk(50)
    assert _atr_now(window, 14) == _full_atr(window, 14)


def test_the_bound_is_not_what_makes_atr_start_independent() -> None:
    """Written to check a claim, and it failed — which is why the claim is gone.

    The bound was described as making ATR independent of where the backtest
    starts. It does not do that, in either direction:

    * Past the tail length, whole-history ATR has **already** converged to the
      same float64 — so there was no long-window drift for the bound to fix.
    * Below the tail length the slice is a no-op, so a short window is computed
      exactly as it was before the bound existed.

    Start date does affect ATR, but only in the first few hundred bars, and
    this bound is not what addresses it.
    """
    long_history = _walk(6_000, seed=3)
    period = 14

    # Past the tail, bounded and unbounded agree exactly - both directions.
    from_long = _atr_now(long_history, period)
    from_short = _atr_now(long_history[-1_000:], period)
    assert from_long == from_short
    assert _full_atr(long_history, period) == _full_atr(long_history[-1_000:], period)

    # Below the tail, the bound changes nothing at all.
    stub = long_history[-60:]
    assert _atr_now(stub, period) == _full_atr(stub, period)


def test_a_genuinely_short_history_does_differ() -> None:
    """Where start date really does move the number, and the bound cannot help.

    Thirty bars in, ATR is about 4% away from its converged value. That is a
    real effect on stop distance and therefore on position size — it is simply
    not one a tail bound can do anything about, since at 30 bars the tail is
    the whole window.
    """
    long_history = _walk(6_000, seed=3)
    converged = _full_atr(long_history, 14)
    early = _full_atr(long_history[-30:], 14)
    assert converged is not None and early is not None
    assert abs(converged - early) / converged > 0.01


def test_tail_is_deep_enough_to_be_worth_asserting() -> None:
    """Guards the constant itself: shrinking it would silently loosen the bound."""
    assert ATR_TAIL_PERIODS >= 10
