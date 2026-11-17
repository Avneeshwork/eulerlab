"""Weekly momentum, top decile (India).

Source: Sapate (2017), SSRN 3065621.

One daily strategy from a paper on Indian equities. Its rule and its library entry
(STRATEGIES, at the bottom) are both in this file.
"""

from __future__ import annotations

from eulerlab.strategies.daily.india_papers.common import MONTH, PaperStrategy, RankTop, momentum

STRATEGIES = (
    PaperStrategy(
        "india_weekly_momentum",
        "Weekly momentum, top decile (India)",
        "sapate-2017-weekly-momentum-india",
        "Sapate (2017), SSRN 3065621",
        "Hold last week's top decile of the point-in-time top 250 for one week.",
        (
            "Score: return over the past 5 trading days. Hold the top decile for 5 days.",
            "Assumed: the paper's abstract states no formation or holding length.",
        ),
        2 * MONTH,
        lambda: RankTop(
            "india_weekly_momentum",
            momentum(5, 0),
            fraction=0.1,
            highest=True,
            rebalance_every=5,
            lookback=2 * MONTH,
        ),
    ),
)
