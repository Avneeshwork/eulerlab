"""Funding-window drift.

Source: Delta perpetuals settle funding at 00:00, 08:00 and 16:00 UTC.

One minute-level crypto signal. Its rule and its library entry (SIGNALS, at the bottom)
are both in this file.
"""

from __future__ import annotations

from collections.abc import Sequence

from eulerlab.intraday.tweezer import Candle, Plan, Rejected
from eulerlab.strategies.intraday.crypto.common import CryptoSignal
from eulerlab.strategies.intraday.papers import PaperRules, _atr_now, _plan


def funding_drift(window: Sequence[Candle], rules: PaperRules, equity: float) -> Plan | Rejected:
    """The hour before a perpetual funding stamp.

    Delta's perpetuals settle funding every eight hours at 00:00, 08:00 and
    16:00 UTC. Positioning ahead of the stamp is a documented practitioner
    behaviour, and it is the one signal here whose premise is a *venue
    mechanic* rather than a price pattern.

    **The honest caveat is large.** This platform does not have the funding
    rate — only price — so what is coded is the price drift in that hour, not
    the funding trade itself. A result here says something about the hour, not
    about the mechanic that makes the hour interesting.
    """
    signal = window[-1]
    if signal.ts.hour not in (7, 15, 23):
        return Rejected("not a funding hour", f"{signal.ts.hour:02d}:00 UTC")
    if len(window) < rules.atr_period * 2:
        return Rejected("warmup")
    if signal.close <= signal.open:
        return Rejected("hour not trending up")

    level = _atr_now(window, rules.atr_period)
    if level is None or level <= 0:
        return Rejected("no ATR")

    return _plan(
        signal=signal,
        entry=signal.close,
        stop=signal.close - rules.stop_atr_mult * level,
        rules=rules,
        equity=equity,
    )


SIGNALS = (
    CryptoSignal(
        "funding_drift",
        "Funding-window drift",
        "practitioner",
        "Delta perpetuals settle funding at 00:00, 08:00 and 16:00 UTC",
        "The one signal whose premise is a venue mechanic rather than a price pattern "
        "— and the platform has price only, so what is coded is the hour, not the "
        "mechanic that makes the hour interesting",
        (
            "Fire only in the hour before a funding stamp (07, 15, 23 UTC).",
            "Require the hour to be trending up.",
            "Stop 1.4 x ATR(14) below entry.",
        ),
        funding_drift,
    ),
)
