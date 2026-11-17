"""High 60-month volatility quintile (India).

Source: Pandey & Samanta (2016), IRA-IJMSS 4(1).

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
        "india_high_vol60",
        "High 60-month volatility quintile (India)",
        "pandey-2016-low-volatility-india",
        "Pandey & Samanta (2016), IRA-IJMSS 4(1)",
        "Hold the most volatile fifth of the point-in-time top 250 by 60-month volatility, the quintile the paper found best.",
        (
            "Volatility: standard deviation of monthly log returns over the past 60 months.",
            "Each month, hold the highest-volatility quintile, equal-weighted. The paper "
            "set out to find a low-volatility anomaly and reported the opposite; this "
            "tests what it reported.",
        ),
        61 * MONTH,
        lambda: RankTop(
            "india_high_vol60",
            monthly_volatility(60, 60),
            fraction=0.2,
            highest=True,
            rebalance_every=MONTH,
            lookback=61 * MONTH,
        ),
    ),
)
