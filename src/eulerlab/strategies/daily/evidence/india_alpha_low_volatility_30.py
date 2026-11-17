"""Alpha and low volatility, NSE index rules (India).

Source: NSE Indices (2020), Nifty Alpha Low-Volatility 30 whitepaper.

One daily momentum or reversal refinement with published evidence. Its rule and its
library entry (STRATEGIES, at the bottom) are both in this file.
"""

from __future__ import annotations

import statistics
from itertools import pairwise

from eulerlab.backtest.strategy import MarketView, Strategy
from eulerlab.strategies.daily.evidence.common import HOLD, _equal, _percentiles
from eulerlab.strategies.daily.india_papers import (
    INDEX_ETF,
    MONTH,
    YEAR,
    PaperStrategy,
    liquid_universe,
)


class AlphaLowVolatility(Strategy):
    """NSE Nifty Alpha Low-Volatility 30: the equal-weight blend of alpha and
    low-volatility percentiles over the last year, top 30, every six months.

    Universe: the 150 most-traded (Nifty 100 + Midcap 50 by size; turnover
    stands in, as market caps are not held). Alpha is Jensen's alpha on daily
    returns against NIFTYBEES with the risk-free rate set to zero (MIBOR is not
    held; a constant rate shifts every alpha by about the same amount). Equal
    weights: the index tilts free-float weights, which are not held.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self.rebalance_every = 6 * MONTH
        self.lookback = YEAR + 10

    def target_weights(self, view: MarketView) -> dict[str, float]:
        market_rows = view.history.get(INDEX_ETF) or []
        market = {
            b.day: b.close / a.close - 1.0
            for a, b in pairwise(market_rows[-YEAR - 1 :])
            if a.close > 0
        }
        alpha: dict[str, float] = {}
        calm: dict[str, float] = {}
        for symbol in liquid_universe(view, 150):
            rows = view.history[symbol][-YEAR - 1 :]
            pairs = [
                (b.close / a.close - 1.0, market[b.day])
                for a, b in pairwise(rows)
                if a.close > 0 and b.day in market
            ]
            if len(pairs) < 200:
                continue
            stock, index = [p[0] for p in pairs], [p[1] for p in pairs]
            var_m = statistics.pvariance(index)
            if var_m <= 0:
                continue
            mean_s, mean_m = statistics.fmean(stock), statistics.fmean(index)
            beta = sum((x - mean_s) * (y - mean_m) for x, y in pairs) / (len(pairs) * var_m)
            alpha[symbol] = mean_s - beta * mean_m
            calm[symbol] = -statistics.pstdev(stock)
        if len(alpha) < 2 * HOLD:
            return {}
        a_rank, v_rank = _percentiles(alpha), _percentiles(calm)
        ordered = sorted(alpha, key=lambda s: (-(a_rank[s] + v_rank[s]), s))
        return _equal(ordered[:HOLD])


STRATEGIES = (
    PaperStrategy(
        "india_alpha_low_volatility_30",
        "Alpha and low volatility, NSE index rules (India)",
        "nse-2020-alpha-low-volatility-30",
        "NSE Indices (2020), Nifty Alpha Low-Volatility 30 whitepaper",
        "Every six months, hold the 30 stocks with the best blend of one-year alpha and low volatility.",
        (
            "Alpha: Jensen's alpha on a year of daily returns against NIFTYBEES (risk-free "
            "set to zero); volatility: a year of daily returns. Equal-weight percentile blend.",
            "Universe: the 150 most-traded (the index uses Nifty 100 + Midcap 50 and F&O "
            "eligibility). Equal weights; the index tilts free-float weights.",
        ),
        YEAR + 10,
        lambda: AlphaLowVolatility("india_alpha_low_volatility_30"),
    ),
)
