"""Opening range breakout on a stock in play (NSE).

Source: [adaptation] Zarattini, Barbon & Aziz (2024) SSRN 4729284, re-tested on NSE.

One intraday signal re-declared for NSE. Its rule and its library entry (SIGNALS, at the
bottom) are both in this file.
"""

from __future__ import annotations

from eulerlab.strategies.intraday.papers import PaperSignal, orb_stock_in_play

SIGNALS = (
    PaperSignal(
        "orb_in_play_in",
        "Opening range breakout on a stock in play (NSE)",
        "[adaptation] Zarattini, Barbon & Aziz (2024) SSRN 4729284, re-tested on NSE",
        "US-adapted: Sharpe 3.31 on SPY and 0.12 on QQQ over the same window. "
        "That spread between two US index ETFs is itself a warning about how "
        "much this signal depends on the instrument.",
        orb_stock_in_play,
        tested_on="NIFTYBEES 1-minute bars — an adaptation, not a replication",
        recommended_class="equity",
        logic=(
            "Sum the first 5 minutes' volume for today.",
            "Compare it to the mean first-5-minute volume of the prior sessions.",
            "Refuse unless that ratio clears the threshold — the selection IS the strategy.",
            "Then apply the plain opening range breakout.",
        ),
    ),
)
