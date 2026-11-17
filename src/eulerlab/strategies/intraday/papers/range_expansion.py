"""Range expansion continuation.

Source: Mesfin (2026) arXiv:2605.04004 §4.2.

One intraday signal coded from a paper. Its rule and its library entry (SIGNALS, at the
bottom) are both in this file.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence

from eulerlab.intraday.tweezer import Candle, Plan, Rejected
from eulerlab.strategies.intraday.papers.common import PaperRules, PaperSignal, _plan


def range_expansion(window: Sequence[Candle], rules: PaperRules, equity: float) -> Plan | Rejected:
    """A bar whose range far exceeds the rolling mean, taken as continuation.

    Mesfin §4.2 is the most interesting failure in the paper: t = -10.96 at
    bar+1. The signal is not merely unprofitable, it is **significantly
    backwards**, and the explanation generalises — the directional burst is
    real but is fully consumed *inside* the expansion bar, so a bar-close
    system entering on the next bar systematically captures the post-exhaustion
    reversal instead. Momentum that lives inside a bar cannot be reached by
    bar-close execution.
    """
    if len(window) < rules.expansion_lookback + 2:
        return Rejected("warmup")
    ranges = [c.high - c.low for c in window[-(rules.expansion_lookback + 1) : -1]]
    mean_range = statistics.fmean(ranges) if ranges else 0.0
    if mean_range <= 0:
        return Rejected("no range history")

    signal = window[-1]
    span = signal.high - signal.low
    if span < rules.expansion_mult * mean_range:
        return Rejected("not an expansion", f"{span / mean_range:.2f}x mean")
    if signal.close <= signal.open:
        return Rejected("expansion is downward", "continuation long needs an up bar")

    return _plan(signal=signal, entry=signal.close, stop=signal.low, rules=rules, equity=equity)


SIGNALS = (
    PaperSignal(
        "range_expansion",
        "Range expansion continuation",
        "Mesfin (2026) arXiv:2605.04004 §4.2",
        "FAIL — t=-10.96, significantly backwards; the move is consumed inside the bar",
        range_expansion,
        tested_on="MNQ (Micro E-Mini Nasdaq 100) futures, 5-minute bars, 947 days 2021-2025",
        recommended_class="futures",
        logic=(
            "Take the mean bar range over the previous 20 bars.",
            "Fire when the signal bar's range exceeds 2.5x that mean and closes up.",
            "Stop at the expansion bar's low.",
            "The paper's finding is that entry lands after the move is already over.",
        ),
    ),
)
