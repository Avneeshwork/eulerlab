"""Top-down quality momentum.

Source: Moskowitz and Grinblatt (1999); Jacob, Pradeep and Varma (2022); research 182.

One stock-screener model. Its rule and its library entry (SPECS, at the bottom) are both
in this file.
"""

from __future__ import annotations

from statistics import median

from eulerlab.backtest import topdown
from eulerlab.backtest.strategy import MarketView, Strategy
from eulerlab.strategies.daily.india_papers import MONTH, YEAR, PaperStrategy, sharpe_momentum_over
from eulerlab.strategies.daily.screener.common import (
    _TOPDOWN_FUNNEL,
    LONG,
    _capped,
    _universe_facts,
    quality,
)


class TopDownQualityMomentum(Strategy):
    """Top sectors, then strong industries, then quality at or above the median; Sharpe momentum."""

    rebalance_every = MONTH
    lookback = YEAR + 10

    def __init__(self) -> None:
        self.name = "screen_topdown_quality_momentum"
        self.score = sharpe_momentum_over(YEAR)

    def target_weights(self, view: MarketView) -> dict[str, float]:
        names, f = _universe_facts(view)
        q = quality(f)
        if len(q) < 40:
            return {}
        rk = topdown.rank(view, names)
        bar = median(q.values())
        good = [s for s in q if q[s] >= bar and rk.passes(s)]
        scores = {s: v for s in good if (v := self.score(view.history[s])) is not None}
        return _capped(scores, rk.sector_of)


SPECS = (
    (
        PaperStrategy(
            id="screen_topdown_quality_momentum",
            title="Top-down quality momentum",
            paper="moskowitz-grinblatt-1999-industry-momentum",
            citation="Moskowitz and Grinblatt (1999); Jacob, Pradeep and Varma (2022); research 182",
            summary="Top 5 sectors, strong industries, quality at or above the median; top 20 by Sharpe momentum.",
            logic=(
                *_TOPDOWN_FUNNEL,
                "Quality as screen_quality_momentum; rank by 12-month return over volatility.",
                "Top 20, at most 6 from one sector, equal; rebalanced every 21 sessions.",
            ),
            lookback=YEAR + 10,
            build=TopDownQualityMomentum,
        ),
        LONG,
    ),
)
