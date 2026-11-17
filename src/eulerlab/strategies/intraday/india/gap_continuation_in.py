"""Gap continuation (NSE).

Source: [adaptation] Mesfin (2026) arXiv:2605.04004 §4.4, re-tested on NSE.

One intraday signal re-declared for NSE. Its rule and its library entry (SIGNALS, at the
bottom) are both in this file.
"""

from __future__ import annotations

from eulerlab.strategies.intraday.papers import PaperSignal, gap_continuation

SIGNALS = (
    PaperSignal(
        "gap_continuation_in",
        "Gap continuation (NSE)",
        "[adaptation] Mesfin (2026) arXiv:2605.04004 §4.4, re-tested on NSE",
        "US-adapted: Sharpe 3.58 on QQQ. An NSE gap prices in a full US session "
        "that closed hours earlier, so this is the least like-for-like of the four.",
        gap_continuation,
        tested_on="NIFTYBEES 1-minute bars — an adaptation, not a replication",
        recommended_class="equity",
        logic=(
            "Measure the gap from the previous session's close.",
            "Require it to exceed the threshold and to hold through the open.",
            "Fire in the direction of the gap.",
            "Identical code to the US signal; only the market and parameters differ.",
        ),
    ),
)
