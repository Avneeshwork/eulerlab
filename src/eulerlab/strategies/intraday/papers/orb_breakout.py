"""Opening range breakout.

Source: Mesfin (2026) arXiv:2605.04004 §4.1.

One intraday signal coded from a paper. Its rule and its library entry (SIGNALS, at the
bottom) are both in this file.
"""

from __future__ import annotations

from eulerlab.strategies.intraday.papers.common import PaperSignal, opening_range_breakout

SIGNALS = (
    PaperSignal(
        "orb_breakout",
        "Opening range breakout",
        "Mesfin (2026) arXiv:2605.04004 §4.1",
        "FAIL — best long t=1.50; -1.42 in 2022 against +7.04 in 2024",
        opening_range_breakout,
        tested_on="MNQ (Micro E-Mini Nasdaq 100) futures, 5-minute bars, 947 days 2021-2025",
        recommended_class="futures",
        logic=(
            "Take the first 5 minutes of the session as the opening range.",
            "Require it to close above its own open — the paper's long side only.",
            "Fire when a later bar closes above the range high.",
            "Stop at the range high minus 1.4 x ATR(14).",
            "Target 2R and 3R; forced flat at the session close.",
        ),
    ),
)
