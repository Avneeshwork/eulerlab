"""UTC-session momentum.

Source: Intraday time-series momentum: the first interval of a session predicts the
last. Documented for equities (Gao et al.) and reported for crypto by Wen, Bouri, Xu &
Zhao, Intraday return predictability in the cryptocurrency markets.

One minute-level crypto signal. Its rule and its library entry (SIGNALS, at the bottom)
are both in this file.
"""

from __future__ import annotations

from collections.abc import Sequence

from eulerlab.intraday.tweezer import Candle, Plan, Rejected
from eulerlab.strategies.intraday.crypto.common import CryptoSignal
from eulerlab.strategies.intraday.papers import PaperRules, _atr_now, _plan, _session_bars


def session_momentum(window: Sequence[Candle], rules: PaperRules, equity: float) -> Plan | Rejected:
    """The day's move so far, continued.

    The intraday-momentum literature finds the first interval of a session
    predicts the last. Crypto has no session, so the UTC day stands in — and
    that substitution is the whole reason this is `literature` rather than
    `paper`: the effect is documented, the boundary is a convention.
    """
    session = _session_bars(window)
    if len(session) < 30 or len(window) < rules.atr_period * 2:
        return Rejected("warmup", f"{len(session)} session bars")

    opening = session[0].open
    if opening <= 0 or session[-1].close <= opening:
        return Rejected("not up on the session")

    level = _atr_now(window, rules.atr_period)
    if level is None or level <= 0:
        return Rejected("no ATR")

    signal = session[-1]
    return _plan(
        signal=signal,
        entry=signal.close,
        stop=signal.close - rules.stop_atr_mult * level,
        rules=rules,
        equity=equity,
    )


SIGNALS = (
    CryptoSignal(
        "session_momentum",
        "UTC-session momentum",
        "literature",
        "Intraday time-series momentum: the first interval of a session predicts the "
        "last. Documented for equities (Gao et al.) and reported for crypto by Wen, "
        "Bouri, Xu & Zhao, Intraday return predictability in the cryptocurrency markets",
        "Momentum and reversal both reported at different intraday horizons; the "
        "boundary here is a convention, not the papers' own",
        (
            "Take the UTC day's open as the session start.",
            "Require price above it — the day is up so far.",
            "Enter long at the current close, continuing the move.",
            "Stop 1.4 x ATR(14) below entry.",
        ),
        session_momentum,
    ),
)
