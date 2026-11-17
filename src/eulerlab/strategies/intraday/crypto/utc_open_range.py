"""UTC-day opening range breakout.

Source: The opening-range family applied to a market with no open.

One minute-level crypto signal. Its rule and its library entry (SIGNALS, at the bottom)
are both in this file.
"""

from __future__ import annotations

from collections.abc import Sequence

from eulerlab.intraday.tweezer import Candle, Plan, Rejected
from eulerlab.strategies.intraday.crypto.common import CryptoSignal
from eulerlab.strategies.intraday.papers import PaperRules, _plan, _session_bars


def utc_open_range(window: Sequence[Candle], rules: PaperRules, equity: float) -> Plan | Rejected:
    """Break of the first minutes of the UTC day.

    An opening range needs an open, and crypto has none. Midnight UTC is a
    convention borrowed from where the daily bar already breaks — so a result
    here is partly a statement about that convention, which is worth knowing
    before reading it as one about crypto.
    """
    session = _session_bars(window)
    span = max(rules.opening_range_minutes, 15)
    if len(session) <= span:
        return Rejected("warmup")

    opening = session[:span]
    high = max(c.high for c in opening)
    signal = session[-1]
    if signal.close <= high:
        return Rejected("no breakout")

    return _plan(
        signal=signal,
        entry=signal.close,
        stop=min(c.low for c in opening),
        rules=rules,
        equity=equity,
    )


SIGNALS = (
    CryptoSignal(
        "utc_open_range",
        "UTC-day opening range breakout",
        "practitioner",
        "The opening-range family applied to a market with no open",
        "A result here is partly a statement about the midnight-UTC convention",
        (
            "Take the first 15 minutes of the UTC day as the opening range.",
            "Fire when a later bar closes above the range high.",
            "Stop at the opening range low.",
        ),
        utc_open_range,
    ),
)
