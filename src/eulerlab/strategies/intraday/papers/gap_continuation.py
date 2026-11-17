"""Gap continuation.

Source: Mesfin (2026) arXiv:2605.04004 §4.4.

One intraday signal coded from a paper. Its rule and its library entry (SIGNALS, at the
bottom) are both in this file.
"""

from __future__ import annotations

from collections.abc import Sequence

from eulerlab.intraday.tweezer import Candle, Plan, Rejected
from eulerlab.strategies.intraday.papers.common import (
    PaperRules,
    PaperSignal,
    _atr_now,
    _gap_pct,
    _plan,
    _session_bars,
)


def gap_continuation(window: Sequence[Candle], rules: PaperRules, equity: float) -> Plan | Rejected:
    """An up gap, taken as continuation rather than something to be filled.

    Mesfin §4.4's most interesting result and the one he refused to claim: with
    a Kalman velocity filter the short side reached t = 3.23 at a 68% win rate
    — on **22 trades over three years**, declining from 12 to 6 to 4. He kept
    it as a candidate rather than validating it, which is the right call and
    the reason this is coded without the Kalman filter: that filter is what
    reduced it to 22 observations.
    """
    gap = _gap_pct(window)
    if gap is None:
        return Rejected("no previous session")
    if gap < rules.gap_min_pct:
        return Rejected("no up gap", f"{gap:.2f}%")

    session = _session_bars(window)
    signal = session[-1]
    if signal.close <= session[0].open:
        return Rejected("gap already fading", "continuation needs price above the open")

    band = _atr_now(window, rules.atr_period)
    if band is None or band <= 0:
        return Rejected("no ATR")
    return _plan(
        signal=signal,
        entry=signal.close,
        stop=session[0].open - rules.stop_atr_mult * band,
        rules=rules,
        equity=equity,
    )


SIGNALS = (
    PaperSignal(
        "gap_continuation",
        "Gap continuation",
        "Mesfin (2026) arXiv:2605.04004 §4.4",
        "FAIL on sample size — t=3.23 but only 22 trades in three years, and declining",
        gap_continuation,
        tested_on="MNQ (Micro E-Mini Nasdaq 100) futures, 5-minute bars, 947 days 2021-2025",
        recommended_class="futures",
        logic=(
            "Same gap measure, opposite direction: up by more than 0.3%.",
            "Require price still above the session open — the gap has not faded.",
            "Stop 1.4 x ATR(14) below the session open.",
            "Coded without the paper's Kalman filter, which is what cut it to 22 trades.",
        ),
    ),
)
