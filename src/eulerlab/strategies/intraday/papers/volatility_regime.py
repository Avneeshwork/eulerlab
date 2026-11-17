"""Volatility regime reversal.

Source: Mesfin (2026) arXiv:2605.04004 §4.6.

One intraday signal coded from a paper. Its rule and its library entry (SIGNALS, at the
bottom) are both in this file.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence

from eulerlab.intraday.tweezer import Candle, Plan, Rejected
from eulerlab.strategies.intraday.papers.common import PaperRules, PaperSignal, _plan, _session_bars


def volatility_regime_reversal(
    window: Sequence[Candle], rules: PaperRules, equity: float
) -> Plan | Rejected:
    """On an unusually volatile session, fade the move.

    Mesfin §4.6's VVG classifier needs three simultaneous pre-market terciles
    (first-30-minute return, overnight gap, first-bar volume deviation) and
    fires on 4.4% of days. The descriptive findings are real — a 25.6bp
    next-day spread and a 77.6% peak-reversal rate — and **every directional
    strategy built on them failed**, reversal at t = +0.86.

    Coded with a single volatility condition rather than three terciles: the
    tercile construction needs a cross-day distribution the intraday scanner
    does not carry. That is a simplification, and it is stated rather than
    hidden.
    """
    session = _session_bars(window)
    if len(session) < 2 or len(window) < rules.vvg_lookback + 2:
        return Rejected("warmup")

    ranges = [c.high - c.low for c in window[-(rules.vvg_lookback + 1) : -1]]
    mean_range = statistics.fmean(ranges) if ranges else 0.0
    if mean_range <= 0:
        return Rejected("no range history")

    span = max(c.high for c in session) - min(c.low for c in session)
    if span < rules.vvg_range_mult * mean_range * len(session) ** 0.5:
        return Rejected("session not volatile enough")

    signal = session[-1]
    opening = session[0].open
    if signal.close >= opening:
        return Rejected("not down on the session", "the long fade needs a decline to fade")

    return _plan(
        signal=signal,
        entry=signal.close,
        stop=min(c.low for c in session),
        rules=rules,
        equity=equity,
    )


SIGNALS = (
    PaperSignal(
        "volatility_regime",
        "Volatility regime reversal",
        "Mesfin (2026) arXiv:2605.04004 §4.6",
        "FAIL — t=+0.86; the classifier's descriptive findings are real, the trades are not",
        volatility_regime_reversal,
        tested_on="MNQ (Micro E-Mini Nasdaq 100) futures, 5-minute bars, 947 days 2021-2025",
        recommended_class="futures",
        logic=(
            "Measure the session's high-to-low range against the 20-bar mean range.",
            "Fire when the session is unusually wide and price is below its open.",
            "Stop at the session low.",
            "Simplified: the paper's classifier needs three pre-market terciles the scanner does not carry.",
        ),
    ),
)
