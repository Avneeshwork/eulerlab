"""Volume dry-up exhaustion.

Source: Mesfin (2026) arXiv:2605.04004 §4.5.

One intraday signal coded from a paper. Its rule and its library entry (SIGNALS, at the
bottom) are both in this file.
"""

from __future__ import annotations

from collections.abc import Sequence

from eulerlab.features.indicators import sma
from eulerlab.intraday.tweezer import Candle, Plan, Rejected
from eulerlab.strategies.intraday.papers.common import (
    PaperRules,
    PaperSignal,
    _closes,
    _plan,
    _volume_z,
)


def _sma_tail(window: Sequence[Candle], period: int, *, back: int = 1) -> list[float | None]:
    """The last `back` simple moving averages, from exactly enough history.

    Unlike ATR, a simple moving average has a finite window: the value at bar
    `i` depends on exactly `period` closes and nothing before them. So in exact
    arithmetic this returns precisely what the whole-window call returned, and
    the bound costs no accuracy at all.

    In float64 the two differ in the last bits, and it is worth knowing which
    way. `sma` keeps a running sum and subtracts the departing value, so its
    rounding error grows with the number of bars it has walked: at 120,960 bars
    the whole-window value has drifted about 5e-14 relative, at 1,000 bars
    about 1e-16. The **bounded** value is therefore the more accurate of the
    two, not the approximation — it has walked 74 bars instead of 120,960.

    It exists because computing them from the whole window was quadratic.
    `detect` runs once per bar with every bar so far, so `sma(_closes(window),
    n)` built a list of every close and a full moving-average series on each of
    120,960 crypto bars — about 1.5e10 operations for two numbers at the end of
    it. `trend_pullback` did not finish a single parameter set. It was not the last:
    `ou_mean_reversion` was still doing it in its own way until 2026-08-27,
    which is why a 1,244-session NSE request timed out and showed nothing.
    """
    tail = window[-(period + back) :]
    return sma(_closes(tail), period)


def volume_dryup_reversal(
    window: Sequence[Candle], rules: PaperRules, equity: float
) -> Plan | Rejected:
    """Volume drying up after a decline, taken as exhaustion before a turn.

    Mesfin §4.5: t = -0.92 on 1,060 events. Another precise null.
    """
    if len(window) < rules.volume_lookback + 2:
        return Rejected("warmup")
    z = _volume_z(window, rules.volume_lookback)
    if z is None:
        return Rejected("no volume history")
    if z > rules.volume_dryup_z:
        return Rejected("no dry-up", f"z={z:.2f}")

    signal = window[-1]
    trend = _sma_tail(window, rules.volume_lookback)
    level = trend[-1] if trend and trend[-1] is not None else None
    if level is None or signal.close >= level:
        return Rejected("not after a decline", "exhaustion needs price below its mean")

    return _plan(signal=signal, entry=signal.close, stop=signal.low, rules=rules, equity=equity)


SIGNALS = (
    PaperSignal(
        "volume_dryup",
        "Volume dry-up exhaustion",
        "Mesfin (2026) arXiv:2605.04004 §4.5",
        "FAIL — t=-0.92 on 1,060 events",
        volume_dryup_reversal,
        tested_on="MNQ (Micro E-Mini Nasdaq 100) futures, 5-minute bars, 947 days 2021-2025",
        recommended_class="futures",
        logic=(
            "Same z-score, inverted: fire when z falls below -1.0.",
            "Require price below its own 20-bar mean, so it is exhaustion after a fall.",
            "Stop at the signal bar's low.",
        ),
    ),
)
