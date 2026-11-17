"""Liquidity grab reversal.

Source: Mesfin (2026) arXiv:2605.04004 §4.3.

One intraday signal coded from a paper. Its rule and its library entry (SIGNALS, at the
bottom) are both in this file.
"""

from __future__ import annotations

from collections.abc import Sequence

from eulerlab.intraday.tweezer import Candle, Plan, Rejected
from eulerlab.strategies.intraday.papers.common import PaperRules, PaperSignal, _plan, _session_bars


def liquidity_grab_reversal(
    window: Sequence[Candle], rules: PaperRules, equity: float
) -> Plan | Rejected:
    """Price pierces the session low, then closes back inside. Long the reversal.

    Mesfin §4.3 found 6,442 such events and both directions significantly
    negative — fading at t = -14.12, following at t = -13.24. The gross
    directional content is 0.20-0.80 points either way, which cannot clear a
    2-point friction in either direction. He calls it a pure friction-ceiling
    result: the pattern is real and too small to trade.
    """
    session = _session_bars(window)
    if len(session) < rules.grab_lookback + 1:
        return Rejected("warmup", f"{len(session)} session bars")

    prior = session[-(rules.grab_lookback + 1) : -1]
    floor = min(c.low for c in prior)
    signal = session[-1]

    if signal.low >= floor:
        return Rejected("no pierce", "did not take out the session low")
    if signal.close <= floor:
        return Rejected("closed outside", "a grab must close back inside the range")

    return _plan(signal=signal, entry=signal.close, stop=signal.low, rules=rules, equity=equity)


SIGNALS = (
    PaperSignal(
        "liquidity_grab",
        "Liquidity grab reversal",
        "Mesfin (2026) arXiv:2605.04004 §4.3",
        "FAIL — t=-14.12 fading, -13.24 following; real but below the friction ceiling",
        liquidity_grab_reversal,
        tested_on="MNQ (Micro E-Mini Nasdaq 100) futures, 5-minute bars, 947 days 2021-2025",
        recommended_class="futures",
        logic=(
            "Track the lowest low of the previous 20 bars in this session.",
            "Fire when a bar pierces that low but closes back above it.",
            "Stop at the piercing bar's low — the level that was just swept.",
        ),
    ),
)
