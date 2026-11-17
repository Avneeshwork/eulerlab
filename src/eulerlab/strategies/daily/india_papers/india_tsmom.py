"""Time-series momentum, long leg (India).

Source: Singh & Walia (2020), Copernican Journal of Finance & Accounting 9(3).

One daily strategy from a paper on Indian equities. Its rule and its library entry
(STRATEGIES, at the bottom) are both in this file.
"""

from __future__ import annotations

from eulerlab.strategies.daily.india_papers.common import (
    MONTH,
    AbsoluteMomentum,
    PaperStrategy,
    momentum,
)

STRATEGIES = (
    PaperStrategy(
        "india_tsmom",
        "Time-series momentum, long leg (India)",
        "singh-2020-time-series-momentum-india",
        "Singh & Walia (2020), Copernican Journal of Finance & Accounting 9(3)",
        "Hold every stock in the point-in-time top 250 whose own return from month t-12 to t-2 is positive.",
        (
            "Signal: return over months t-12 to t-2 (one-month gap). Positive means long.",
            "Hold all positive stocks, equal-weighted, rebalanced monthly. The short leg "
            "(negative stocks) is dropped.",
        ),
        13 * MONTH,
        lambda: AbsoluteMomentum(
            "india_tsmom", momentum(11 * MONTH, MONTH), market_filter=False, lookback=13 * MONTH
        ),
    ),
)
