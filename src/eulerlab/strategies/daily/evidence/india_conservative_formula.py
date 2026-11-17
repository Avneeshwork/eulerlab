"""Conservative Formula: low volatility, momentum, dividends (India).

Source: Van Vliet & Blitz (2018); India: 'The Conservative Formula: Evidence from India'
(SSRN 4163613).

One daily momentum or reversal refinement with published evidence. Its rule and its
library entry (STRATEGIES, at the bottom) are both in this file.
"""

from __future__ import annotations

import statistics

from eulerlab.backtest.strategy import MarketView, Strategy
from eulerlab.strategies.daily.evidence.common import (
    HOLD,
    _equal,
    _percentiles,
    dividend_yield,
    momentum_12_1,
    monthly_returns,
)
from eulerlab.strategies.daily.india_papers import MONTH, PaperStrategy, liquid_universe


class ConservativeFormula(Strategy):
    """Van Vliet & Blitz: the lower-volatility half by 36-month volatility, then
    the average of momentum and payout ranks, top `HOLD`, quarterly.

    Payout is the trailing 12-month dividend yield: buybacks are not held here.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self.rebalance_every = 3 * MONTH
        self.lookback = 36 * MONTH + 10

    def target_weights(self, view: MarketView) -> dict[str, float]:
        candidates: list[tuple[float, str]] = []
        for symbol in liquid_universe(view):
            months = monthly_returns(view.history[symbol], 36)
            if months:
                candidates.append((statistics.stdev(months), symbol))
        if len(candidates) < 3 * HOLD:
            return {}
        candidates.sort()
        calm = [s for _, s in candidates[: len(candidates) // 2]]
        momentum = {s: m for s in calm if (m := momentum_12_1(view.history[s])) is not None}
        payout = {s: dividend_yield(s, view.history[s]) for s in momentum}
        mom_rank, pay_rank = _percentiles(momentum), _percentiles(payout)
        score = sorted(momentum, key=lambda s: (-(mom_rank[s] + pay_rank[s]), s))
        return _equal(score[:HOLD])


STRATEGIES = (
    PaperStrategy(
        "india_conservative_formula",
        "Conservative Formula: low volatility, momentum, dividends (India)",
        "van-vliet-blitz-2018-conservative-formula",
        "Van Vliet & Blitz (2018); India: 'The Conservative Formula: Evidence from India' (SSRN 4163613)",
        "Of the calmer half of stocks, hold the 30 with the best combined momentum and dividend-yield ranks; quarterly.",
        (
            "Calm: below-median 36-month volatility of monthly returns. Then the average "
            "percentile of 12-1 momentum and trailing 12-month dividend yield.",
            "The paper's payout adds buybacks, not held here. Quarterly, equal weight, "
            "point-in-time 250 most-traded. The Indian study reports +12.6% a year over the BSE 100.",
        ),
        36 * MONTH + 10,
        lambda: ConservativeFormula("india_conservative_formula"),
    ),
)
