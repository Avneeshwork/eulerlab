"""The four signals that cleared the bar on US equity, re-declared for NSE.

### Why these are separate strategies and not a US strategy with a flag

`orb_breakout`, `gap_continuation`, `ou_reversion` and `orb_in_play` are the
four signals whose US runs clear the noise bar. Asking whether they also work on
NIFTYBEES is a **new hypothesis**, not a second measurement of the existing one,
and it has to be registered as one.

If the same strategy id carried a US result and an India result, the library
would show one strategy with two Sharpes and no way to say which claim was
being made. Worse, the trial ledger would count one subject where two were
tested, and the deflated-Sharpe correction takes the subject count as its
denominator. Separate ids keep the accounting honest and leave the US entries
untouched.

### What is copied and what is not

The **logic is identical** — the same `detect` function object, not a
reimplementation. A rewritten copy would drift, and then a difference between
the two markets could be a difference in the code rather than in the market.

The **parameters are not assumed to carry over**, which is the whole question.
Each of the four keeps its US-adopted values as a starting point and is swept
separately on NSE data, because a stop of 1.0 ATR on QQQ and a stop of 1.0 ATR
on NIFTYBEES are the same number describing different things.

### What differs between the two markets, and why it might matter

| | QQQ | NIFTYBEES |
|---|---|---|
| Session | 390 minutes | 375 minutes |
| Costs | $29.50 a leg, capped | STT, SEBI turnover, stamp duty, GST — percentage, uncapped |
| Overnight gap | US close to US open | includes the entire US session |

The cost difference is the one to watch. INDmoney's US brokerage is capped at
$25, so a large position pays a flat fee; NSE charges are percentage-based all
the way up, so the same position pays proportionally. A signal that survives on
QQQ because the cap made its friction negligible has no such protection here.

The gap difference matters for `gap_continuation` specifically: an NSE opening
gap prices in a full US session that closed hours earlier, which is a different
phenomenon from a US gap and is a reason the signal might behave differently
rather than a reason to expect it to fail.
"""

from __future__ import annotations

from eulerlab.intraday.papers import (
    PaperSignal,
    gap_continuation,
    opening_range_breakout,
    orb_stock_in_play,
    ou_mean_reversion,
)

SYMBOL = "NIFTYBEES"
"""The NIFTY 50 ETF — the direct NSE analogue of QQQ.

An index tracker rather than a single name, so the comparison is index-to-index.
`RELIANCE` was the platform's old NSE default and is a single large-cap, which
answers a different question than the US runs did."""

INDIA_SIGNALS: dict[str, PaperSignal] = {
    signal.id: signal
    for signal in (
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
}
