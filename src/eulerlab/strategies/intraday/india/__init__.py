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

from eulerlab.strategies.intraday.india.common import SYMBOL
from eulerlab.strategies.intraday.india.gap_continuation_in import SIGNALS as _gap_continuation_in
from eulerlab.strategies.intraday.india.orb_breakout_in import SIGNALS as _orb_breakout_in
from eulerlab.strategies.intraday.india.orb_in_play_in import SIGNALS as _orb_in_play_in
from eulerlab.strategies.intraday.india.ou_reversion_in import SIGNALS as _ou_reversion_in
from eulerlab.strategies.intraday.papers import PaperSignal

INDIA_SIGNALS: dict[str, PaperSignal] = {
    signal.id: signal
    for signal in (
        *_orb_breakout_in,
        *_gap_continuation_in,
        *_ou_reversion_in,
        *_orb_in_play_in,
    )
}


__all__ = [
    "INDIA_SIGNALS",
    "SYMBOL",
]
