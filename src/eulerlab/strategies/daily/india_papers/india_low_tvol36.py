"""Lowest 36-month volatility quintile (India).

Source: Joshipura & Peswani (2017), Applied Finance Letters 6(1).

One daily strategy from a paper on Indian equities. Its rule and its library entry
(STRATEGIES, at the bottom) are both in this file.
"""

from __future__ import annotations

from eulerlab.strategies.daily.india_papers.common import (
    MONTH,
    PaperStrategy,
    RankTop,
    monthly_volatility,
)

STRATEGIES = (
    PaperStrategy(
        "india_low_tvol36",
        "Lowest 36-month volatility quintile (India)",
        "joshipura-2017-low-risk-india",
        "Joshipura & Peswani (2017), Applied Finance Letters 6(1)",
        "Hold the least volatile fifth of the point-in-time top 250 by 36-month volatility, rebalanced monthly.",
        (
            "Volatility: standard deviation of monthly excess log returns over 36 months, "
            "12 at least.",
            "Each month, hold the lowest quintile, equal-weighted, as the paper does.",
        ),
        37 * MONTH,
        lambda: RankTop(
            "india_low_tvol36",
            monthly_volatility(36, 12),
            fraction=0.2,
            highest=False,
            rebalance_every=MONTH,
            lookback=37 * MONTH,
        ),
    ),
)
