"""Opening range breakout (NSE).

Source: [adaptation] Mesfin (2026) arXiv:2605.04004 §4.1, re-tested on NSE.

One intraday signal re-declared for NSE. Its rule and its library entry (SIGNALS, at the
bottom) are both in this file.
"""

from __future__ import annotations

from eulerlab.strategies.intraday.papers import PaperSignal, opening_range_breakout

SIGNALS = (
    PaperSignal(
        "orb_breakout_in",
        "Opening range breakout (NSE)",
        "[adaptation] Mesfin (2026) arXiv:2605.04004 §4.1, re-tested on NSE",
        "US-adapted: Sharpe 3.69 on QQQ over 58 sessions with a 1.0 ATR stop. "
        "Whether that survives NSE costs and a 375-minute session is the question.",
        opening_range_breakout,
        tested_on="NIFTYBEES 1-minute bars — an adaptation, not a replication",
        recommended_class="equity",
        logic=(
            "Take the first 5 minutes of the session as the opening range.",
            "Require it to close above its own open — the paper's long side only.",
            "Fire when a later bar closes above the range high.",
            "Identical code to the US signal; only the market and parameters differ.",
        ),
    ),
)
