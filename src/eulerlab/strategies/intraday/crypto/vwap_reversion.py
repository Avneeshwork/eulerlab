"""VWAP reversion.

Source: Widely documented practitioner rule; no academic validation found.

One minute-level crypto signal. Its rule and its library entry (SIGNALS, at the bottom)
are both in this file.
"""

from __future__ import annotations

from collections.abc import Sequence

from eulerlab.intraday.tweezer import Candle, Plan, Rejected
from eulerlab.strategies.intraday.crypto.common import CryptoSignal, _vwap
from eulerlab.strategies.intraday.papers import PaperRules, _plan, _session_bars


def vwap_reversion(window: Sequence[Candle], rules: PaperRules, equity: float) -> Plan | Rejected:
    """Price stretched below session VWAP, faded back toward it."""
    session = _session_bars(window)
    if len(session) < 30:
        return Rejected("warmup")
    level = _vwap(session)
    if level is None:
        return Rejected("no volume", "VWAP without volume is a moving average")

    signal = session[-1]
    stretch = (level - signal.close) / level * 100.0
    if stretch < rules.min_risk_pct:
        return Rejected("not stretched", f"{stretch:.3f}% below VWAP")

    return _plan(
        signal=signal,
        entry=signal.close,
        stop=min(c.low for c in session[-30:]),
        rules=rules,
        equity=equity,
    )


SIGNALS = (
    CryptoSignal(
        "vwap_reversion",
        "VWAP reversion",
        "practitioner",
        "Widely documented practitioner rule; no academic validation found",
        "Untested, which is a measurable state rather than a dismissal",
        (
            "Compute session VWAP from the UTC day's bars.",
            "Require price stretched below it by more than the risk floor.",
            "Enter long, expecting a return toward VWAP.",
            "Stop at the low of the last 30 minutes.",
        ),
        vwap_reversion,
    ),
)
