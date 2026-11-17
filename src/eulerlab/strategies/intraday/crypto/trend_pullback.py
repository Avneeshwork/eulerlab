"""Trend pullback to the mean.

Source: The buy-the-dip family; no crypto-specific validation found.

One minute-level crypto signal. Its rule and its library entry (SIGNALS, at the bottom)
are both in this file.
"""

from __future__ import annotations

from collections.abc import Sequence

from eulerlab.intraday.tweezer import Candle, Plan, Rejected
from eulerlab.strategies.intraday.crypto.common import CryptoSignal
from eulerlab.strategies.intraday.papers import PaperRules, _plan, _sma_tail


def trend_pullback(window: Sequence[Candle], rules: PaperRules, equity: float) -> Plan | Rejected:
    """A dip to the moving average inside an uptrend."""
    if len(window) < rules.ou_lookback + 2:
        return Rejected("warmup")
    # Exactly enough history for both readings and no more: the current mean,
    # and the one `expansion_lookback` bars back that it is compared against.
    # A simple moving average depends on a fixed number of closes, so this
    # returns the same numbers the whole-window form did — see `_sma_tail`.
    trend = _sma_tail(window, rules.ou_lookback, back=rules.expansion_lookback + 1)
    level = trend[-1] if trend and trend[-1] is not None else None
    earlier = trend[-rules.expansion_lookback] if len(trend) > rules.expansion_lookback else None
    if level is None or earlier is None or level <= earlier:
        return Rejected("no uptrend")

    signal = window[-1]
    if signal.low > level or signal.close < level:
        return Rejected("no pullback", "needs a dip to the mean that closes back above it")

    return _plan(signal=signal, entry=signal.close, stop=signal.low, rules=rules, equity=equity)


SIGNALS = (
    CryptoSignal(
        "trend_pullback",
        "Trend pullback to the mean",
        "practitioner",
        "The buy-the-dip family; no crypto-specific validation found",
        "Untested",
        (
            "Require the 60-bar mean to be rising over the last 20 bars.",
            "Require this bar to dip to that mean and close back above it.",
            "Stop at the pullback bar's low.",
        ),
        trend_pullback,
    ),
)
