"""Supertrend (10, 2.2), liquid NSE stocks (GitHub rule).

Source: darshandeshmukh11/supertrend-backtester (GitHub, 2026).

One daily rule from a public GitHub repository. Its rule and its library entry
(STRATEGIES, at the bottom) are both in this file.
"""

from __future__ import annotations

from collections.abc import Sequence

from eulerlab.features.panel import PanelRow
from eulerlab.strategies.daily.github.common import STATE_WINDOW, Age, PositionRule
from eulerlab.strategies.daily.india_papers import PaperStrategy


def supertrend_up(rows: Sequence[PanelRow], period: int = 10, multiplier: float = 2.2) -> list[int]:
    """darshandeshmukh11/supertrend-backtester `compute_supertrend`: ATR as the
    simple mean of true range, bands at hl2 +/- multiplier x ATR, the usual
    final-band carry, direction +1 up, -1 down, starting down."""
    bars = [r.ohlc() for r in rows]
    highs, lows, closes = [b[1] for b in bars], [b[2] for b in bars], [b[3] for b in bars]
    true_range = [highs[0] - lows[0]] + [
        max(hi - lo, abs(hi - before), abs(lo - before))
        for hi, lo, before in zip(highs[1:], lows[1:], closes[:-1], strict=True)
    ]
    direction: list[int] = []
    upper = lower = 0.0
    for i in range(len(rows)):
        window = true_range[max(0, i - period + 1) : i + 1]
        atr = sum(window) / len(window)
        mid = (highs[i] + lows[i]) / 2
        basic_upper, basic_lower = mid + multiplier * atr, mid - multiplier * atr
        if i == 0:
            upper, lower = basic_upper, basic_lower
            direction.append(-1)
            continue
        upper = basic_upper if basic_upper < upper or closes[i - 1] > upper else upper
        lower = basic_lower if basic_lower > lower or closes[i - 1] < lower else lower
        if direction[-1] == -1:
            direction.append(1 if closes[i] > upper else -1)
        else:
            direction.append(-1 if closes[i] < lower else 1)
    return direction


def supertrend_rule(rows: Sequence[PanelRow]) -> Age:
    """In from the bar the direction turns up until it turns down."""
    if len(rows) < 20:
        return None
    direction = supertrend_up(rows[-STATE_WINDOW:])
    if direction[-1] != 1:
        return None
    turned = next(i for i in range(len(direction) - 1, 0, -1) if direction[i - 1] != 1)
    return len(direction) - 1 - turned


STRATEGIES = (
    PaperStrategy(
        "nse_github_supertrend_10_22",
        "Supertrend (10, 2.2), liquid NSE stocks (GitHub rule)",
        "github-2026-supertrend-backtester",
        "darshandeshmukh11/supertrend-backtester (GitHub, 2026)",
        "Hold a stock while its Supertrend (ATR 10, multiplier 2.2) points up.",
        (
            "Supertrend as the repository computes it: ATR the simple mean of true range "
            "over 10 days, bands at the bar midpoint +/- 2.2 ATR.",
            "Among the point-in-time 250 most-traded stocks, up to 20 names. The repository "
            "fills at the next open; the engine at the next close.",
        ),
        STATE_WINDOW + 5,
        lambda: PositionRule(
            "nse_github_supertrend_10_22", supertrend_rule, lookback=STATE_WINDOW + 5, slots=20
        ),
    ),
)
