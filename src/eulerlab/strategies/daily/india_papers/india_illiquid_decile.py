"""Most illiquid decile, Amihud (India).

Source: Kundlia & Verma (2021), Asian Economic and Financial Review 11(6).

One daily strategy from a paper on Indian equities. Its rule and its library entry
(STRATEGIES, at the bottom) are both in this file.
"""

from __future__ import annotations

from eulerlab.strategies.daily.india_papers.common import (
    YEAR,
    PaperStrategy,
    RankTop,
    amihud_illiquidity,
)

STRATEGIES = (
    PaperStrategy(
        "india_illiquid_decile",
        "Most illiquid decile, Amihud (India)",
        "kundlia-2021-illiquidity-premium-india",
        "Kundlia & Verma (2021), Asian Economic and Financial Review 11(6)",
        "Hold the most illiquid tenth of the point-in-time top 250 by Amihud's measure, rebalanced yearly.",
        (
            "Illiquidity: mean |daily return| per rupee traded over the past year, 50+ days.",
            "Once a year, hold the most illiquid decile, equal-weighted. The top 250 is the "
            "liquid end of the market, so this tests the premium where it is tradable.",
        ),
        YEAR + 2,
        lambda: RankTop(
            "india_illiquid_decile",
            amihud_illiquidity,
            fraction=0.1,
            highest=True,
            rebalance_every=YEAR,
            lookback=YEAR + 2,
        ),
    ),
)
