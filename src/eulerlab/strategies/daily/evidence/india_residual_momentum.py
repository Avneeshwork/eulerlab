"""Residual momentum, market-model residuals (India).

Source: Blitz, Huij & Martens (2011), JEF 18(3); Blitz, Hanauer & Vidojevic (2020).

One daily momentum or reversal refinement with published evidence. Its rule and its
library entry (STRATEGIES, at the bottom) are both in this file.
"""

from __future__ import annotations

import statistics

from eulerlab.backtest.strategy import MarketView, Strategy
from eulerlab.strategies.daily.evidence.common import HOLD, _equal, monthly_returns, residuals
from eulerlab.strategies.daily.india_papers import INDEX_ETF, MONTH, PaperStrategy, liquid_universe


class ResidualMomentum(Strategy):
    """Rank on months t-12..t-2 of 36-month market-model residuals, over their s.d."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.rebalance_every = MONTH
        self.lookback = 36 * MONTH + 10

    def target_weights(self, view: MarketView) -> dict[str, float]:
        market = monthly_returns(view.history.get(INDEX_ETF) or [], 36)
        if market is None:
            return {}
        scored = []
        for symbol in liquid_universe(view):
            stock = monthly_returns(view.history[symbol], 36)
            found = residuals(stock, market) if stock else None
            if not found:
                continue
            formation = found[-12:-1]
            spread = statistics.stdev(formation)
            if spread > 0:
                scored.append((sum(formation) / spread, symbol))
        if len(scored) < 3 * HOLD:
            return {}
        scored.sort(key=lambda x: (-x[0], x[1]))
        return _equal([s for _, s in scored[:HOLD]])


STRATEGIES = (
    PaperStrategy(
        "india_residual_momentum",
        "Residual momentum, market-model residuals (India)",
        "blitz-huij-martens-2011-residual-momentum",
        "Blitz, Huij & Martens (2011), JEF 18(3); Blitz, Hanauer & Vidojevic (2020)",
        "Hold the 30 stocks with the highest 12-1 residual return over its volatility, residuals from a 36-month market model.",
        (
            "Monthly returns regressed on NIFTYBEES over 36 months; score = sum of residuals "
            "in months t-12..t-2 over their standard deviation.",
            "The paper uses the three Fama-French factors; only the market is available here. "
            "Monthly, equal weight, point-in-time 250 most-traded.",
        ),
        36 * MONTH + 10,
        lambda: ResidualMomentum("india_residual_momentum"),
    ),
)
