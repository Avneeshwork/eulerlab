"""Quality momentum.

Source: Jacob, Pradeep and Varma (2022); Sharpe momentum from this platform.

One stock-screener model. Its rule and its library entry (SPECS, at the bottom) are both
in this file.
"""

from __future__ import annotations

from statistics import median

from eulerlab.backtest.strategy import MarketView, Strategy
from eulerlab.strategies.daily.india_papers import (
    MONTH,
    YEAR,
    PaperStrategy,
    sharpe_momentum_over,
)
from eulerlab.strategies.daily.screener.common import LONG, _top, _universe_facts, quality


class QualityMomentum(Strategy):
    """Sharpe momentum among the better half on quality (H-0030)."""

    rebalance_every = MONTH
    lookback = YEAR + 10

    def __init__(self) -> None:
        self.name = "screen_quality_momentum"
        self.score = sharpe_momentum_over(YEAR)

    def target_weights(self, view: MarketView) -> dict[str, float]:
        _, f = _universe_facts(view)
        q = quality(f)
        if len(q) < 40:
            return {}
        good = [s for s in q if q[s] >= median(q.values())]
        scores = {s: v for s in good if (v := self.score(view.history[s])) is not None}
        return _top(scores)


SPECS = (
    (
        PaperStrategy(
            id="screen_quality_momentum",
            title="Quality momentum",
            paper="jacob-pradeep-varma-2022-quality-india",
            citation="Jacob, Pradeep and Varma (2022); Sharpe momentum from this platform",
            summary="Sharpe momentum over a year, among the better half of the liquid 250 on quality; top 20, monthly.",
            logic=(
                "Quality: mean rank of ROE, operating profit over assets, low leverage, payout.",
                "Keep the better half; rank by 12-month return over volatility.",
                "Hold the top 20 equally; rebalance every 21 sessions.",
            ),
            lookback=YEAR + 10,
            build=QualityMomentum,
        ),
        LONG,
    ),
)
