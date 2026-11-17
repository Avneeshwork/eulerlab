"""Compression breakout.

Source: The volatility-squeeze family; no crypto-specific validation found.

One minute-level crypto signal. Its rule and its library entry (SIGNALS, at the bottom)
are both in this file.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence

from eulerlab.intraday.tweezer import Candle, Plan, Rejected
from eulerlab.strategies.intraday.crypto.common import CryptoSignal
from eulerlab.strategies.intraday.papers import PaperRules, _plan


def range_compression(
    window: Sequence[Candle], rules: PaperRules, equity: float
) -> Plan | Rejected:
    """Break out of an unusually quiet stretch."""
    if len(window) < rules.expansion_lookback * 2:
        return Rejected("warmup")
    recent = window[-rules.expansion_lookback :]
    prior = window[-rules.expansion_lookback * 2 : -rules.expansion_lookback]
    quiet = statistics.fmean(c.high - c.low for c in recent)
    normal = statistics.fmean(c.high - c.low for c in prior)
    if normal <= 0 or quiet > normal * 0.6:
        return Rejected("not compressed", f"{quiet / normal:.2f}x prior range" if normal else "")

    ceiling = max(c.high for c in recent[:-1])
    signal = window[-1]
    if signal.close <= ceiling:
        return Rejected("no breakout")

    return _plan(
        signal=signal,
        entry=signal.close,
        stop=min(c.low for c in recent),
        rules=rules,
        equity=equity,
    )


SIGNALS = (
    CryptoSignal(
        "range_compression",
        "Compression breakout",
        "practitioner",
        "The volatility-squeeze family; no crypto-specific validation found",
        "Untested",
        (
            "Compare the mean bar range of the last 20 bars to the 20 before them.",
            "Require the recent stretch under 60% of prior — genuinely quiet.",
            "Fire on a close above the quiet stretch's high.",
            "Stop at the quiet stretch's low.",
        ),
        range_compression,
    ),
)
