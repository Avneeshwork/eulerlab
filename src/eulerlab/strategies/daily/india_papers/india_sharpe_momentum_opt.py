"""Volatility-adjusted momentum, top 10, every 2 weeks (optimised, India).

Source: Vijaykumar (2020), SSRN 3614509; settings from research 067.

One daily strategy from a paper on Indian equities. Its rule and its library entry
(STRATEGIES, at the bottom) are both in this file.
"""

from __future__ import annotations

from eulerlab.strategies.daily.india_papers.common import (
    LIQUID_TOP,
    YEAR,
    PaperStrategy,
    RankTop,
    sharpe_momentum,
)

STRATEGIES = (
    PaperStrategy(
        "india_sharpe_momentum_opt",
        "Volatility-adjusted momentum, top 10, every 2 weeks (optimised, India)",
        "vijaykumar-2020-momentum-india",
        "Vijaykumar (2020), SSRN 3614509; settings from research 067",
        "Hold the 10 stocks of the point-in-time top 250 with the best 12-month return per "
        "unit of volatility, re-ranked every 2 weeks.",
        (
            "Score: 12-month return divided by annualised 12-month daily volatility.",
            "Hold the top 10, equal-weighted, re-ranked every 10 sessions: the best region "
            "of a 64-setting sweep chosen on 2016-2023 (research 067).",
            "Not the recommended setting: PBO 0.71 and walk-forward re-tuning did not beat "
            "the paper's. Kept so it can be paper-traded beside the original.",
        ),
        YEAR + 5,
        lambda: RankTop(
            "india_sharpe_momentum_opt",
            sharpe_momentum,
            fraction=10 / LIQUID_TOP,
            highest=True,
            rebalance_every=10,
            lookback=YEAR + 5,
        ),
    ),
)
