"""Frog-in-the-pan momentum, continuous winners (India).

Source: Da, Gurun & Warachka (2014), RFS 27(7); Goyal, Jegadeesh & Subrahmanyam, Review
of Finance.

One daily momentum or reversal refinement with published evidence. Its rule and its
library entry (STRATEGIES, at the bottom) are both in this file.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from itertools import pairwise

from eulerlab.backtest.strategy import MarketView, Strategy
from eulerlab.features.panel import PanelRow
from eulerlab.strategies.daily.evidence.common import HOLD, _equal, momentum_12_1
from eulerlab.strategies.daily.india_papers import MONTH, YEAR, PaperStrategy, liquid_universe


def information_discreteness(rows: Sequence[PanelRow]) -> float | None:
    """sign(12-1 return) x (% negative days - % positive days), same window."""
    past = momentum_12_1(rows)
    if past is None:
        return None
    window = [r.close for r in rows[-1 - YEAR : len(rows) - MONTH]]
    moves = [b / a - 1.0 for a, b in pairwise(window) if a > 0]
    if len(moves) < 100:
        return None
    up = sum(1 for m in moves if m > 0) / len(moves)
    down = sum(1 for m in moves if m < 0) / len(moves)
    return math.copysign(1.0, past) * (down - up) if past else 0.0


class FrogInThePan(Strategy):
    """The 30% best 12-1 performers, then the `HOLD` with the most continuous gains."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.rebalance_every = MONTH
        self.lookback = YEAR + 10

    def target_weights(self, view: MarketView) -> dict[str, float]:
        scored = []
        for symbol in liquid_universe(view):
            rows = view.history[symbol]
            past, discrete = momentum_12_1(rows), information_discreteness(rows)
            if past is not None and discrete is not None:
                scored.append((past, discrete, symbol))
        if len(scored) < 3 * HOLD:
            return {}
        scored.sort(key=lambda x: (-x[0], x[2]))
        winners = scored[: max(HOLD, round(0.3 * len(scored)))]
        winners.sort(key=lambda x: (x[1], x[2]))
        return _equal([s for _, _, s in winners[:HOLD]])


STRATEGIES = (
    PaperStrategy(
        "india_frog_in_the_pan",
        "Frog-in-the-pan momentum, continuous winners (India)",
        "da-gurun-warachka-2014-frog-in-the-pan",
        "Da, Gurun & Warachka (2014), RFS 27(7); Goyal, Jegadeesh & Subrahmanyam, Review of Finance",
        "Of the 30% best 12-1 performers, hold the 30 whose gains came most steadily (lowest information discreteness).",
        (
            "ID = sign(12-1 return) x (% negative days - % positive days) over the same "
            "window; low ID = many small gains, the paper's 'continuous information'.",
            "Monthly, equal weight, point-in-time 250 most-traded stocks. Long only.",
        ),
        YEAR + 10,
        lambda: FrogInThePan("india_frog_in_the_pan"),
    ),
)
