"""Momentum winners, 12-1, top 30% (India).

Source: Agarwalla, Jacob & Varma (2013), IIMA WP 2013-09-05.

One daily strategy from a paper on Indian equities. Its rule and its library entry
(STRATEGIES, at the bottom) are both in this file.
"""

from __future__ import annotations

from eulerlab.strategies.daily.india_papers.common import MONTH, PaperStrategy, RankTop, momentum

STRATEGIES = (
    PaperStrategy(
        "india_wml_12_1",
        "Momentum winners, 12-1, top 30% (India)",
        "agarwalla-2013-four-factor-india",
        "Agarwalla, Jacob & Varma (2013), IIMA WP 2013-09-05",
        "Hold the top 30% of the point-in-time top 250 by return from month t-12 to t-1, rebalanced monthly.",
        (
            "Formation: return from 12 months ago to 1 month ago, skipping the last month.",
            "Each month, hold the top 30%, equal-weighted. The factor's loser short leg "
            "and size split are dropped.",
        ),
        13 * MONTH,
        lambda: RankTop(
            "india_wml_12_1",
            momentum(11 * MONTH, MONTH),
            fraction=0.3,
            highest=True,
            rebalance_every=MONTH,
            lookback=13 * MONTH,
        ),
    ),
)
