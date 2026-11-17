"""Pair: Bharat Forge / Ashok Leyland (India).

Source: Sen (2022), arXiv:2211.07080.

One daily strategy from a paper on Indian equities. Its rule and its library entry
(STRATEGIES, at the bottom) are both in this file.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from eulerlab.backtest.strategy import MarketView, Strategy
from eulerlab.strategies.daily.india_papers.common import YEAR, PaperStrategy


class PairRatio(Strategy):
    """Sen (2022), long-only: hold whichever leg the price ratio says is cheap.

    The ratio a/b is z-scored over the past year. Above +1, a is rich: hold b.
    Below -1, hold a. In between, keep the last side, as the paper's always-in
    rule does. The paper's short leg is dropped.
    """

    rebalance_every = 1
    lookback = YEAR + 5

    def __init__(self, name: str, a: str, b: str) -> None:
        self.name = name
        self.a, self.b = a, b
        self.hold_unchanged = True

    def _side(self, ratios: Sequence[float]) -> str | None:
        """Replay the band crossings over the history in view, with running
        sums so each day's z-score costs O(1)."""
        side: str | None = None
        total = squares = 0.0
        for k, value in enumerate(ratios):
            total += value
            squares += value * value
            if k >= YEAR:
                old = ratios[k - YEAR]
                total -= old
                squares -= old * old
            if k < YEAR - 1:
                continue
            mean = total / YEAR
            variance = (squares - YEAR * mean * mean) / (YEAR - 1)
            if variance <= 0:
                continue
            z = (value - mean) / math.sqrt(variance)
            if z > 1:
                side = self.b
            elif z < -1:
                side = self.a
        return side

    def target_weights(self, view: MarketView) -> dict[str, float]:
        ra, rb = view.history.get(self.a), view.history.get(self.b)
        if not ra or not rb:
            return {}
        by_day = {r.day: r.close for r in rb}
        ratios = [r.close / by_day[r.day] for r in ra[-2 * YEAR :] if by_day.get(r.day)]
        if len(ratios) < YEAR:
            return {}
        side = self._side(ratios)
        return {side: 1.0} if side else {}


STRATEGIES = (
    PaperStrategy(
        "india_pair_bharatforg_ashokley",
        "Pair: Bharat Forge / Ashok Leyland (India)",
        "sen-2022-pair-trading-india",
        "Sen (2022), arXiv:2211.07080",
        "Hold whichever of Bharat Forge and Ashok Leyland the price ratio says is cheap.",
        (
            "Ratio BHARATFORG/ASHOKLEY, z-scored over the past year.",
            "z above +1: hold ASHOKLEY. z below -1: hold BHARATFORG. Otherwise keep the "
            "last side. The paper's short leg is dropped.",
        ),
        YEAR + 5,
        lambda: PairRatio("india_pair_bharatforg_ashokley", "BHARATFORG", "ASHOKLEY"),
        "all",
        ("BHARATFORG", "ASHOKLEY"),
    ),
)
