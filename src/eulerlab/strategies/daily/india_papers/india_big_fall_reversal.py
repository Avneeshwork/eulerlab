"""Buy after a 20% monthly fall (India).

Source: Parthasarathy & Sendilvelu (2022), Economic Thought Journal 67(3).

One daily strategy from a paper on Indian equities. Its rule and its library entry
(STRATEGIES, at the bottom) are both in this file.
"""

from __future__ import annotations

from collections.abc import Sequence
from itertools import pairwise

from eulerlab.backtest.strategy import MarketView, Strategy
from eulerlab.features.panel import PanelRow
from eulerlab.strategies.daily.india_papers.common import (
    MONTH,
    PaperStrategy,
    _monthly_closes,
    liquid_universe,
)


class BigFallReversal(Strategy):
    """Parthasarathy & Sendilvelu (2022), long side: hold large stocks for six
    months after a calendar month in which they fell 20% or more, counting an
    event only if there was none in the six months before it."""

    rebalance_every = MONTH

    def __init__(self, *, threshold: float = -0.20, months: int = 6, top: int = 50) -> None:
        self.name = "india_big_fall_reversal"
        self.threshold = threshold
        self.months = months
        self.top = top
        self.lookback = (2 * months + 2) * MONTH

    def _held(self, rows: Sequence[PanelRow]) -> bool:
        closes = _monthly_closes(rows)
        # Monthly returns, oldest first; the last element is the month in progress.
        rets = [b / a - 1.0 for a, b in pairwise(closes[:-1]) if a > 0]
        events: list[bool] = []
        for k, value in enumerate(rets):
            fresh = not any(events[max(0, k - self.months) : k])
            events.append(value <= self.threshold and fresh)
        return any(events[-self.months :])

    def target_weights(self, view: MarketView) -> dict[str, float]:
        chosen = [s for s in liquid_universe(view, self.top) if self._held(view.history[s])]
        if not chosen:
            return {}
        return dict.fromkeys(chosen, 1.0 / max(len(chosen), 5))


STRATEGIES = (
    PaperStrategy(
        "india_big_fall_reversal",
        "Buy after a 20% monthly fall (India)",
        "parthasarathy-2022-large-price-moves-india",
        "Parthasarathy & Sendilvelu (2022), Economic Thought Journal 67(3)",
        "Hold large stocks for six months after a calendar month in which they fell 20% or more.",
        (
            "Universe: the 50 most-traded stocks at each date (the paper uses Nifty 50 members).",
            "Event: a calendar month return of -20% or worse, with no event in the 6 months "
            "before. Hold for 6 months, equal-weighted, at least 5 slots.",
        ),
        14 * MONTH,
        BigFallReversal,
    ),
)
