"""Gap fill fade.

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


def gap_fill_fade(window: Sequence[Candle], rules: PaperRules, equity: float) -> Plan | Rejected:
    """A down gap, faded on the expectation that it closes during the session.

    Mesfin §4.4 tested three entry times and all failed, t between -0.32 and
    -0.59 — indistinguishable from noise rather than wrong. MNQ gaps simply do
    not reliably fill within the session.
    """
    gap = _gap_pct(window)
    if gap is None:
        return Rejected("no previous session")
    if gap > -rules.gap_min_pct:
        return Rejected("no down gap", f"{gap:.2f}%")

    signal = _session_bars(window)[-1]
    band = _atr_now(window, rules.atr_period)
    if band is None or band <= 0:
        return Rejected("no ATR")
    return _plan(
        signal=signal,
        entry=signal.close,
        stop=signal.close - rules.stop_atr_mult * band,
        rules=rules,
        equity=equity,
    )


SIGNALS = (
    PaperSignal(
        "gap_fill_fade",
        "Gap fill fade",
        "Mesfin (2026) arXiv:2605.04004 §4.4",
        "FAIL — t between -0.32 and -0.59 across three entry times; noise",
        gap_fill_fade,
        tested_on="MNQ (Micro E-Mini Nasdaq 100) futures, 5-minute bars, 947 days 2021-2025",
        recommended_class="futures",
        logic=(
            "Compare today's session open to the previous session's close.",
            "Fire when the gap is down by more than 0.3%, betting it closes.",
            "Stop 1.4 x ATR(14) below entry.",
        ),
    ),
)
