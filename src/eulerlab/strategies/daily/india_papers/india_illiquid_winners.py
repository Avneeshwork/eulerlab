"""Illiquid winners (India).

Source: Aziz & Ansari (2014), SSRN 2416637.

One daily strategy from a paper on Indian equities. Its rule and its library entry
(STRATEGIES, at the bottom) are both in this file.
"""

from __future__ import annotations

from eulerlab.strategies.daily.india_papers.common import (
    MONTH,
    YEAR,
    DoubleSort,
    PaperStrategy,
    amihud_illiquidity,
    momentum,
)

STRATEGIES = (
    PaperStrategy(
        "india_illiquid_winners",
        "Illiquid winners (India)",
        "aziz-2014-momentum-illiquidity-india",
        "Aziz & Ansari (2014), SSRN 2416637",
        "Among the top 30% by 6-month return, hold the more illiquid half by Amihud's measure.",
        (
            "Winners: top 30% of the point-in-time top 250 by 6-month return.",
            "Of those, hold the half with the highest Amihud illiquidity, equal-weighted, "
            "monthly. Formation and split are assumed: only the abstract was readable.",
        ),
        YEAR + 5,
        lambda: DoubleSort(
            "india_illiquid_winners",
            momentum(6 * MONTH, 0),
            amihud_illiquidity,
            first_fraction=0.3,
            second_fraction=0.5,
            second_low=False,
            rebalance_every=MONTH,
            lookback=YEAR + 5,
        ),
    ),
)
