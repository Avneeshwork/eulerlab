"""Volume climax continuation.

Source: Practitioner construction; Mesfin (2026) tested the weaker volume-spike version
on MNQ futures and measured a precise null at t=+0.07.

One minute-level crypto signal. Its rule and its library entry (SIGNALS, at the bottom)
are both in this file.
"""

from __future__ import annotations

from collections.abc import Sequence

from eulerlab.intraday.tweezer import Candle, Plan, Rejected
from eulerlab.strategies.intraday.crypto.common import CryptoSignal
from eulerlab.strategies.intraday.papers import PaperRules, _plan, _volume_z


def volume_climax(window: Sequence[Candle], rules: PaperRules, equity: float) -> Plan | Rejected:
    """An extreme volume bar that closes strong, taken as continuation."""
    if len(window) < rules.volume_lookback + 2:
        return Rejected("warmup")
    z = _volume_z(window, rules.volume_lookback)
    if z is None or z < rules.volume_spike_z * 1.5:
        return Rejected("no climax", f"z={z if z is not None else 'n/a'}")

    signal = window[-1]
    span = signal.high - signal.low
    if span <= 0 or (signal.close - signal.low) / span < 0.7:
        return Rejected("weak close", "a climax bar must close in its upper third")

    return _plan(signal=signal, entry=signal.close, stop=signal.low, rules=rules, equity=equity)


SIGNALS = (
    CryptoSignal(
        "volume_climax",
        "Volume climax continuation",
        "practitioner",
        "Practitioner construction; Mesfin (2026) tested the weaker volume-spike "
        "version on MNQ futures and measured a precise null at t=+0.07",
        "The nearest tested relative failed on 2,119 events",
        (
            "Require a volume z-score above 3.0 against the last 20 bars.",
            "Require the bar to close in its upper third — a strong close, not a wick.",
            "Stop at the climax bar's low.",
        ),
        volume_climax,
    ),
)
