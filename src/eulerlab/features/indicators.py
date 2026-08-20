"""Technical indicators: SMA, RSI, ATR, ADX, and candle geometry.

Written by hand rather than taken from `pandas_ta`, for three reasons that all
come from this project's existing rules.

**No new dependency.** `pandas_ta` pulls in pandas and numpy for arithmetic that
is thirty lines. `CLAUDE.md` requires a measurement before a heavyweight
dependency, and there is none.

**Every primitive here is tested.** ADR-027 refuses to let a strategy reference
anything that has no test behind it, because a bug in an indicator is
indistinguishable from a finding. Each function below has a test against a
hand-computed value, not against another library's output.

**Wilder's smoothing is not the same as an exponential moving average**, and
the difference matters. RSI, ATR and ADX are all defined by J. Welles Wilder
with a smoothing factor of `1/n`, whereas a conventional EMA uses `2/(n+1)`.
Substituting one for the other shifts every value and is the single most common
way these indicators disagree between implementations. `_wilder` is separate and
named so that cannot happen silently here.

Every function takes plain sequences and returns a list of the same length,
with `None` where there is not yet enough history. `None` rather than zero or a
back-filled first value: a zero ADX is a real reading that means "no trend",
and a strategy cannot distinguish it from "not computed yet" if both are 0.0.
"""

from __future__ import annotations

from collections.abc import Sequence

Series = list[float | None]


def sma(values: Sequence[float], period: int) -> Series:
    """Simple moving average."""
    if period < 1:
        msg = f"period must be >= 1, got {period}"
        raise ValueError(msg)
    out: Series = [None] * len(values)
    running = 0.0
    for index, value in enumerate(values):
        running += value
        if index >= period:
            running -= values[index - period]
        if index >= period - 1:
            out[index] = running / period
    return out


def _wilder(values: Sequence[float | None], period: int) -> Series:
    """Wilder's smoothing: seed with a simple average, then `prev + (x - prev)/n`.

    Equivalent to an EMA with alpha = 1/n, NOT the 2/(n+1) of a conventional
    EMA. Wilder defined RSI, ATR and ADX this way; using the other constant
    produces plausible-looking numbers that disagree with every published
    reference.
    """
    out: Series = [None] * len(values)
    seed: list[float] = []
    smoothed: float | None = None
    for index, value in enumerate(values):
        if value is None:
            continue
        if smoothed is None:
            seed.append(value)
            if len(seed) == period:
                smoothed = sum(seed) / period
                out[index] = smoothed
        else:
            smoothed += (value - smoothed) / period
            out[index] = smoothed
    return out


def rsi(closes: Sequence[float], period: int = 14) -> Series:
    """Relative Strength Index, Wilder-smoothed.

    `RSI = 100 - 100/(1 + RS)` where `RS` is the ratio of average gain to
    average loss. Returns 100.0 when there are no losses in the window, which
    is the defined limit rather than a division by zero.
    """
    gains: Series = [None] * len(closes)
    losses: Series = [None] * len(closes)
    for index in range(1, len(closes)):
        change = closes[index] - closes[index - 1]
        gains[index] = max(change, 0.0)
        losses[index] = max(-change, 0.0)

    average_gain = _wilder(gains, period)
    average_loss = _wilder(losses, period)

    out: Series = [None] * len(closes)
    for index in range(len(closes)):
        up, down = average_gain[index], average_loss[index]
        if up is None or down is None:
            continue
        if down == 0.0:
            out[index] = 100.0
        else:
            out[index] = 100.0 - 100.0 / (1.0 + up / down)
    return out


def true_range(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float]) -> Series:
    """The greater of today's range and either gap from yesterday's close.

    The gap terms are what distinguish true range from a simple high-low: a
    stock that gaps down and then trades quietly had a violent day, and
    high-low alone would call it calm.
    """
    out: Series = [None] * len(closes)
    for index in range(len(closes)):
        if index == 0:
            out[index] = highs[index] - lows[index]
            continue
        previous = closes[index - 1]
        out[index] = max(
            highs[index] - lows[index],
            abs(highs[index] - previous),
            abs(lows[index] - previous),
        )
    return out


def atr(
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int = 14
) -> Series:
    """Average True Range, Wilder-smoothed."""
    return _wilder(true_range(highs, lows, closes), period)


def adx(
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int = 14
) -> Series:
    """Average Directional Index — trend *strength*, with no direction in it.

    A high ADX says the market is trending; it does not say which way. Reading
    it as bullish is a common and expensive error.

    Directional movement is deliberately exclusive: on a day where both the up
    move and the down move are positive, only the larger counts and the other
    is zero. An implementation that lets both register produces a much
    smoother, much less useful series.
    """
    plus_dm: Series = [None] * len(closes)
    minus_dm: Series = [None] * len(closes)
    for index in range(1, len(closes)):
        up = highs[index] - highs[index - 1]
        down = lows[index - 1] - lows[index]
        plus_dm[index] = up if (up > down and up > 0) else 0.0
        minus_dm[index] = down if (down > up and down > 0) else 0.0

    smooth_tr = _wilder(true_range(highs, lows, closes), period)
    smooth_plus = _wilder(plus_dm, period)
    smooth_minus = _wilder(minus_dm, period)

    dx: Series = [None] * len(closes)
    for index in range(len(closes)):
        tr_value = smooth_tr[index]
        up_value = smooth_plus[index]
        down_value = smooth_minus[index]
        if tr_value is None or up_value is None or down_value is None or tr_value == 0.0:
            continue
        plus_di = 100.0 * up_value / tr_value
        minus_di = 100.0 * down_value / tr_value
        total = plus_di + minus_di
        if total == 0.0:
            dx[index] = 0.0
        else:
            dx[index] = 100.0 * abs(plus_di - minus_di) / total
    return _wilder(dx, period)


# --- candle geometry --------------------------------------------------------


def body_ratio(open_: float, high: float, low: float, close: float) -> float:
    """How much of the bar's range is body rather than wick, in [0, 1].

    Zero when the bar has no range, which is the correct answer for a
    non-trading day and makes every "body must be at least X" test fail rather
    than pass on a fabricated shape.
    """
    span = high - low
    if span <= 0.0:
        return 0.0
    return abs(close - open_) / span


def range_pct(high: float, low: float, close: float) -> float:
    """The bar's range as a percentage of its close."""
    if close <= 0.0:
        return 0.0
    return (high - low) / close * 100.0


def is_bearish(open_: float, close: float) -> bool:
    return close < open_


def is_bullish(open_: float, close: float) -> bool:
    return close > open_
