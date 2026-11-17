"""Momentum 3-month formation, 6-month hold (India).

Source: Maheshwari & Dhankar (2015), Journal of Commerce and Accounting Research 4(3-4).

One daily strategy from a paper on Indian equities. Its rule and its library entry
(STRATEGIES, at the bottom) are both in this file.
"""

from __future__ import annotations

from eulerlab.strategies.daily.india_papers.common import MONTH, PaperStrategy, RankTop, momentum

STRATEGIES = (
    PaperStrategy(
        "india_momentum_3x6",
        "Momentum 3-month formation, 6-month hold (India)",
        "maheshwari-2015-momentum-seasonality-india",
        "Maheshwari & Dhankar (2015), Journal of Commerce and Accounting Research 4(3-4)",
        "Hold the top decile of the point-in-time top 250 by 3-month return, re-formed every 6 months.",
        (
            "Formation: return over the past 3 months. Hold the top decile for 6 months.",
            "3x6 is the paper's best-reported combination (0.87%/month); only the abstract "
            "could be read, so the decile and weighting are assumed.",
        ),
        4 * MONTH,
        lambda: RankTop(
            "india_momentum_3x6",
            momentum(3 * MONTH, 0),
            fraction=0.1,
            highest=True,
            rebalance_every=6 * MONTH,
            lookback=4 * MONTH,
        ),
    ),
)
