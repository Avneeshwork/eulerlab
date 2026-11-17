"""12-month momentum, no skip, top 30 (India).

Source: Vijaykumar (2026), SSRN 7394980.

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
    momentum,
)

STRATEGIES = (
    PaperStrategy(
        "india_momentum_12_noskip",
        "12-month momentum, no skip, top 30 (India)",
        "vijaykumar-2026-which-momentum-india",
        "Vijaykumar (2026), SSRN 7394980",
        "Hold the 30 stocks of the point-in-time top 250 with the best 12-month return, rebalanced monthly.",
        (
            "Score: 12-month return including the last month, one of the two best of the "
            "ten definitions the paper compares.",
            "Top 30, equal-weighted, monthly. The paper's top-50 holding buffer is not "
            "applied: a strategy here cannot see what it already holds.",
        ),
        YEAR + 5,
        lambda: RankTop(
            "india_momentum_12_noskip",
            momentum(YEAR, 0),
            fraction=30 / LIQUID_TOP,
            highest=True,
            rebalance_every=MONTH,
            lookback=YEAR + 5,
        ),
    ),
)
