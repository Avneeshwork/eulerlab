"""Ornstein-Uhlenbeck mean reversion.

Source: Mesfin (2026) arXiv:2605.04004 §4.8.

One intraday signal coded from a paper. Its rule and its library entry (SIGNALS, at the
bottom) are both in this file.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence

from eulerlab.intraday.tweezer import Candle, Plan, Rejected
from eulerlab.strategies.intraday.papers.common import PaperRules, PaperSignal, _closes, _plan


def ou_mean_reversion(
    window: Sequence[Candle], rules: PaperRules, equity: float
) -> Plan | Rejected:
    """Buy when price is far below its rolling mean in standard deviations.

    Mesfin §4.8 tested this on Micro Gold at 1.5sd, 2.0sd and 2.5sd; all failed,
    most with strongly negative t. The 60-minute variant's half-life worked out
    to roughly eight hours — longer than a session, which makes it structurally
    incompatible with intraday execution regardless of its sign.
    """
    if len(window) < rules.ou_lookback + 1:
        return Rejected("warmup")
    # Bound the window *before* extracting, not after. This read
    # `_closes(window)[-(ou_lookback + 1):]`, which built a list of every close
    # since the start of the backtest and then kept the last 21 — once per bar,
    # so O(n) per call and O(n^2) per run. It is the exact hazard `_bounded_sma`
    # above documents, and that docstring named `trend_pullback` as the last
    # signal doing it while this one still was.
    #
    # The two forms are the same values: the last N closes of the whole window
    # are the closes of the last N candles.
    closes = _closes(window[-(rules.ou_lookback + 1) :])
    reference, signal = closes[:-1], window[-1]
    spread = statistics.pstdev(reference)
    if spread <= 0:
        return Rejected("no dispersion")
    z = (signal.close - statistics.fmean(reference)) / spread
    if z > rules.ou_entry_z:
        return Rejected("not stretched", f"z={z:.2f}")

    return _plan(
        signal=signal,
        entry=signal.close,
        stop=signal.close - spread * 1.5,
        rules=rules,
        equity=equity,
    )


SIGNALS = (
    PaperSignal(
        "ou_reversion",
        "Ornstein-Uhlenbeck mean reversion",
        "Mesfin (2026) arXiv:2605.04004 §4.8",
        "FAIL — t=-2.19 at 2.0sd; half-life longer than a session at 60-minute resolution",
        ou_mean_reversion,
        tested_on="MNQ (Micro E-Mini Nasdaq 100) futures, 5-minute bars, 947 days 2021-2025",
        recommended_class="futures",
        logic=(
            "Take the z-score of the close against the previous 60 closes.",
            "Fire when it falls below -2.0 standard deviations.",
            "Stop 1.5 standard deviations below entry.",
        ),
    ),
)
