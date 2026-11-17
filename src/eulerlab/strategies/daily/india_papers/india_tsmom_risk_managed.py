"""Risk-managed time-series momentum (India).

Source: Singh, Walia, Bekiros, Gupta, Kumar & Mishra (2022), JEFAS 27(54).

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
        "india_tsmom_risk_managed",
        "Risk-managed time-series momentum (India)",
        "singh-2022-risk-managed-momentum-india",
        "Singh, Walia, Bekiros, Gupta, Kumar & Mishra (2022), JEFAS 27(54)",
        "Time-series momentum's long leg, in cash after a month when the index fell more than over two years.",
        (
            "Signal: 12-month return with a one-month gap; hold positive stocks, equal-weighted.",
            "Market state: if NIFTYBEES's 1-month move is larger than its 24-month move and "
            "down, hold cash that month (the paper goes short-only; long only here).",
        ),
        25 * MONTH,
        lambda: AbsoluteMomentum(
            "india_tsmom_risk_managed",
            momentum(12 * MONTH, MONTH),
            market_filter=True,
            lookback=25 * MONTH,
        ),
    ),
)
