"""Three-year losers (India).

Source: Joshipura (2009), NSE research paper.

One daily strategy from a paper on Indian equities. Its rule and its library entry
(STRATEGIES, at the bottom) are both in this file.
"""

from __future__ import annotations

from eulerlab.strategies.daily.india_papers.common import (
    MONTH,
    YEAR,
    PaperStrategy,
    RankTop,
    momentum,
)

STRATEGIES = (
    PaperStrategy(
        "india_contrarian_36m",
        "Three-year losers (India)",
        "joshipura-2009-overreaction-india",
        "Joshipura (2009), NSE research paper",
        "Hold the decile of the point-in-time top 250 with the worst 3-year return, re-formed yearly.",
        (
            "Score: return over the past 36 months. Hold the bottom decile, equal-weighted.",
            "Re-formed every year (the paper's cohorts start 12 months apart and run 36 "
            "months; overlapping cohorts are not modelled). The winner short is dropped.",
        ),
        37 * MONTH,
        lambda: RankTop(
            "india_contrarian_36m",
            momentum(36 * MONTH, 0),
            fraction=0.1,
            highest=False,
            rebalance_every=YEAR,
            lookback=37 * MONTH,
        ),
    ),
)
