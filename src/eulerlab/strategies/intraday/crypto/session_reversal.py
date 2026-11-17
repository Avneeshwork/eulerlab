"""UTC-session reversal.

Source: The opposite leg of the same intraday predictability literature.

One minute-level crypto signal. Its rule and its library entry (SIGNALS, at the bottom)
are both in this file.
"""

from __future__ import annotations

from collections.abc import Sequence

from eulerlab.intraday.tweezer import Candle, Plan, Rejected
from eulerlab.strategies.intraday.crypto.common import CryptoSignal
from eulerlab.strategies.intraday.papers import PaperRules, _plan, _session_bars


def session_reversal(window: Sequence[Candle], rules: PaperRules, equity: float) -> Plan | Rejected:
    """The day's move so far, faded.

    The same literature reports reversal at some intraday horizons and momentum
    at others, which is why both are coded. Running only the one that agrees
    with a prior is how a library becomes an argument.
    """
    session = _session_bars(window)
    if len(session) < 30:
        return Rejected("warmup")

    opening = session[0].open
    signal = session[-1]
    if opening <= 0 or signal.close >= opening:
        return Rejected("not down on the session", "the long fade needs a decline")

    return _plan(
        signal=signal,
        entry=signal.close,
        stop=min(c.low for c in session),
        rules=rules,
        equity=equity,
    )


SIGNALS = (
    CryptoSignal(
        "session_reversal",
        "UTC-session reversal",
        "literature",
        "The opposite leg of the same intraday predictability literature",
        "Coded because the literature reports both; running only the leg that agrees "
        "with a prior is how a library becomes an argument",
        (
            "Take the UTC day's open as the session start.",
            "Require price below it — the day is down so far.",
            "Enter long against the move, expecting reversion.",
            "Stop at the session low.",
        ),
        session_reversal,
    ),
)
