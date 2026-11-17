"""Short-term residual reversal, losers (India).

Source: Blitz, Huij, Lansdorp & Verbeek (2013), JFM 16(3).

One daily momentum or reversal refinement with published evidence. Its rule and its
library entry (STRATEGIES, at the bottom) are both in this file.
"""

from __future__ import annotations

import statistics

from eulerlab.backtest.strategy import MarketView, Strategy
from eulerlab.strategies.daily.evidence.common import HOLD, _equal, monthly_returns, residuals
from eulerlab.strategies.daily.india_papers import INDEX_ETF, MONTH, PaperStrategy, liquid_universe


class ResidualReversal(Strategy):
    """Buy the `HOLD` stocks whose last month's residual, over its 36-month s.d., is lowest."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.rebalance_every = MONTH
        self.lookback = 37 * MONTH + 10

    def target_weights(self, view: MarketView) -> dict[str, float]:
        market = monthly_returns(view.history.get(INDEX_ETF) or [], 37)
        if market is None:
            return {}
        scored = []
        for symbol in liquid_universe(view):
            stock = monthly_returns(view.history[symbol], 37)
            found = residuals(stock, market) if stock else None
            if not found:
                continue
            spread = statistics.stdev(found[:-1])
            if spread > 0:
                scored.append((found[-1] / spread, symbol))
        if len(scored) < 3 * HOLD:
            return {}
        scored.sort(key=lambda x: (x[0], x[1]))
        return _equal([s for _, s in scored[:HOLD]])


STRATEGIES = (
    PaperStrategy(
        "india_residual_reversal",
        "Short-term residual reversal, losers (India)",
        "blitz-huij-lansdorp-verbeek-2013-residual-reversal",
        "Blitz, Huij, Lansdorp & Verbeek (2013), JFM 16(3)",
        "Buy the 30 stocks whose last month's market-model residual, over its 36-month s.d., is the most negative.",
        (
            "Residuals from 36 months of a market model on NIFTYBEES; the paper uses three "
            "Fama-French factors.",
            "Monthly, equal weight, point-in-time 250 most-traded. Long only: the loser leg.",
        ),
        37 * MONTH + 10,
        lambda: ResidualReversal("india_residual_reversal"),
    ),
)
