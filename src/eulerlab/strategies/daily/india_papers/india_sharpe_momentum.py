"""Volatility-adjusted momentum, top 30 (India).

Source: Vijaykumar (2020), SSRN 3614509.

One daily strategy from a paper on Indian equities. Its rule and its library entry
(STRATEGIES, at the bottom) are both in this file.
"""

from __future__ import annotations

from eulerlab.strategies.daily.india_papers.common import (
    LIQUID_TOP,
    MONTH,
    YEAR,
    PaperStrategy,
    RankTop,
    sharpe_momentum,
)

STRATEGIES = (
    PaperStrategy(
        "india_sharpe_momentum",
        "Volatility-adjusted momentum, top 30 (India)",
        "vijaykumar-2020-momentum-india",
        "Vijaykumar (2020), SSRN 3614509",
        "Hold the 30 stocks of the point-in-time top 250 with the best 12-month return per unit of volatility.",
        (
            "Score: 12-month return divided by annualised 12-month daily volatility.",
            "Hold the top 30, equal-weighted, rebalanced monthly. The paper's exact rules "
            "were not readable; this is the volatility-adjusted ranking its summary credits.",
        ),
        YEAR + 5,
        lambda: RankTop(
            "india_sharpe_momentum",
            sharpe_momentum,
            fraction=30 / LIQUID_TOP,
            highest=True,
            rebalance_every=MONTH,
            lookback=YEAR + 5,
        ),
    ),
)
