"""VWAP breakout on rising volume.

Source: Widely documented practitioner rule; no academic validation found.

One minute-level crypto signal. Its rule and its library entry (SIGNALS, at the bottom)
are both in this file.
"""

from __future__ import annotations

from collections.abc import Sequence

from eulerlab.intraday.tweezer import Candle, Plan, Rejected
from eulerlab.strategies.intraday.crypto.common import CryptoSignal, _vwap
from eulerlab.strategies.intraday.papers import PaperRules, _plan, _session_bars, _volume_z


def vwap_breakout(window: Sequence[Candle], rules: PaperRules, equity: float) -> Plan | Rejected:
    """A close back above session VWAP on rising volume."""
    session = _session_bars(window)
    if len(session) < 30 or len(window) < rules.volume_lookback + 2:
        return Rejected("warmup")
    level = _vwap(session)
    if level is None:
        return Rejected("no volume")

    signal, previous = session[-1], session[-2]
    if not (previous.close <= level < signal.close):
        return Rejected("no cross", "needs a close crossing up through VWAP")
    z = _volume_z(window, rules.volume_lookback)
    if z is None or z <= 0:
        return Rejected("volume not rising", f"z={z if z is not None else 'n/a'}")

    return _plan(signal=signal, entry=signal.close, stop=level, rules=rules, equity=equity)


SIGNALS = (
    CryptoSignal(
        "vwap_breakout",
        "VWAP breakout on rising volume",
        "practitioner",
        "Widely documented practitioner rule; no academic validation found",
        "Untested",
        (
            "Compute session VWAP from the UTC day's bars.",
            "Require the previous close below it and this close above — a crossing.",
            "Require the volume z-score against the last 20 bars to be positive.",
            "Stop at VWAP itself.",
        ),
        vwap_breakout,
    ),
)
