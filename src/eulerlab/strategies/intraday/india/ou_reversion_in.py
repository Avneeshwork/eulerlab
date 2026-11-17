"""Ornstein-Uhlenbeck mean reversion (NSE).

Source: [adaptation] Mesfin (2026) arXiv:2605.04004 §4.8, re-tested on NSE.

One intraday signal re-declared for NSE. Its rule and its library entry (SIGNALS, at the
bottom) are both in this file.
"""

from __future__ import annotations

from eulerlab.strategies.intraday.papers import PaperSignal, ou_mean_reversion

SIGNALS = (
    PaperSignal(
        "ou_reversion_in",
        "Ornstein-Uhlenbeck mean reversion (NSE)",
        "[adaptation] Mesfin (2026) arXiv:2605.04004 §4.8, re-tested on NSE",
        "US-adapted: Sharpe 3.25 on QQQ over 58 sessions and 58 fills — the "
        "densest of the four, so the one with most to lose to per-trade costs.",
        ou_mean_reversion,
        tested_on="NIFTYBEES 1-minute bars — an adaptation, not a replication",
        recommended_class="equity",
        logic=(
            "Take the z-score of the close against the previous 60 closes.",
            "Fire when it falls below the threshold.",
            "Stop a fixed number of standard deviations below entry.",
            "Identical code to the US signal; only the market and parameters differ.",
        ),
    ),
)
