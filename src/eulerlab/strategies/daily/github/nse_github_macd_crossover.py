"""MACD 12/26/9 crossover, liquid NSE stocks (GitHub rule).

Source: Sunkeerth/macd-crossover-backtest-three-frameworks (GitHub, 2026).

One daily rule from a public GitHub repository. Its rule and its library entry
(STRATEGIES, at the bottom) are both in this file.
"""

from __future__ import annotations

from collections.abc import Sequence

from eulerlab.features.panel import PanelRow
from eulerlab.strategies.daily.github.common import (
    STATE_WINDOW,
    Age,
    PositionRule,
    _closes,
    crossing_rule,
)
from eulerlab.strategies.daily.india_papers import PaperStrategy


def _ema(values: Sequence[float], period: int) -> list[float]:
    """Seeded with the first value, as Sunkeerth's `calculate_ema` is."""
    k = 2.0 / (period + 1)
    out = [values[0]]
    for value in values[1:]:
        out.append(value * k + out[-1] * (1 - k))
    return out


def macd_rule(rows: Sequence[PanelRow]) -> Age:
    """Sunkeerth/macd-crossover-backtest-three-frameworks: MACD(12, 26) crossing
    above its 9-period signal to buy, below to sell. Long only here."""
    closes = _closes(rows)
    if len(closes) < 60:
        return None
    line = [a - b for a, b in zip(_ema(closes, 12), _ema(closes, 26), strict=True)]
    signal = _ema(line, 9)
    return crossing_rule(list(line), list(signal), len(closes))


STRATEGIES = (
    PaperStrategy(
        "nse_github_macd_crossover",
        "MACD 12/26/9 crossover, liquid NSE stocks (GitHub rule)",
        "github-2026-macd-crossover-three-frameworks",
        "Sunkeerth/macd-crossover-backtest-three-frameworks (GitHub, 2026)",
        "Buy when MACD crosses above its signal line; sell when it crosses below.",
        (
            "MACD = EMA(12) - EMA(26) of the close, signal = EMA(9) of MACD, each seeded "
            "with its first value as the repository does. Long only.",
            "Among the point-in-time 250 most-traded stocks, up to 20 names; filled at the "
            "next session's close.",
        ),
        STATE_WINDOW + 5,
        lambda: PositionRule(
            "nse_github_macd_crossover", macd_rule, lookback=STATE_WINDOW + 5, slots=20
        ),
    ),
)
