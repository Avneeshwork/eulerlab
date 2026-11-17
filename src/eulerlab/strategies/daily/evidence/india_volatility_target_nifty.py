"""Volatility-targeted Nifty, rest in cash (India).

Source: Harvey, Hoyle, Korgaonkar, Rattray, Sargaison & Van Hemert (2018), The Impact of
Volatility Targeting, JPM.

One daily momentum or reversal refinement with published evidence. Its rule and its
library entry (STRATEGIES, at the bottom) are both in this file.
"""

from __future__ import annotations

import statistics
from itertools import pairwise

from eulerlab.backtest.strategy import MarketView, Strategy
from eulerlab.strategies.daily.evidence.common import SAFE
from eulerlab.strategies.daily.india_papers import INDEX_ETF, MONTH, YEAR, PaperStrategy


class VolatilityTarget(Strategy):
    """NIFTYBEES scaled by its 3-year over its 1-month daily volatility, capped
    at 1, the rest in LIQUIDBEES; monthly. The target is the index's own
    long-run volatility, so no number is chosen (Harvey et al. 2018 target a
    fixed level)."""

    sizing = "strategy"  # the index/cash split is the strategy (ADR-122)

    def __init__(self, name: str) -> None:
        self.name = name
        self.rebalance_every = MONTH
        self.lookback = 3 * YEAR + 5

    def target_weights(self, view: MarketView) -> dict[str, float]:
        rows = view.history.get(INDEX_ETF) or []
        closes = [r.close for r in rows]
        moves = [b / a - 1.0 for a, b in pairwise(closes) if a > 0]
        if len(moves) < YEAR:
            return {SAFE: 1.0}
        recent, long_run = statistics.pstdev(moves[-MONTH:]), statistics.pstdev(moves)
        weight = min(1.0, long_run / recent) if recent > 0 else 1.0
        return {INDEX_ETF: weight, SAFE: 1.0 - weight} if weight < 1.0 else {INDEX_ETF: 1.0}


STRATEGIES = (
    PaperStrategy(
        "india_volatility_target_nifty",
        "Volatility-targeted Nifty, rest in cash (India)",
        "harvey-et-al-2018-volatility-targeting",
        "Harvey, Hoyle, Korgaonkar, Rattray, Sargaison & Van Hemert (2018), The Impact of Volatility Targeting, JPM",
        "Monthly, hold NIFTYBEES at its 3-year over 1-month volatility (at most 100%), the rest in LIQUIDBEES.",
        (
            "Volatility from daily returns; weight = min(1, 3-year vol / 1-month vol). The "
            "paper targets a fixed level and allows leverage; neither here.",
            "Monthly; LIQUIDBEES stands in for cash.",
        ),
        3 * YEAR + 5,
        lambda: VolatilityTarget("india_volatility_target_nifty"),
        "all",
        (INDEX_ETF, SAFE),
    ),
)
