"""Volume spike momentum.

Source: Mesfin (2026) arXiv:2605.04004 §4.5.

One intraday signal coded from a paper. Its rule and its library entry (SIGNALS, at the
bottom) are both in this file.
"""

from __future__ import annotations

from collections.abc import Sequence

from eulerlab.intraday.tweezer import Candle, Plan, Rejected
from eulerlab.strategies.intraday.papers.common import PaperRules, PaperSignal, _plan, _volume_z


def volume_spike_momentum(
    window: Sequence[Candle], rules: PaperRules, equity: float
) -> Plan | Rejected:
    """An unusually heavy up bar, taken as informed flow continuing.

    Mesfin §4.5: t = +0.07 on 2,119 up-spikes. He is careful about what that
    means — the sample is large enough that a near-zero t is a **precise null**,
    not an underpowered test. Volume magnitude at five-minute resolution does
    not predict the next bar's direction.
    """
    if len(window) < rules.volume_lookback + 1:
        return Rejected("warmup")
    z = _volume_z(window, rules.volume_lookback)
    if z is None:
        return Rejected("no volume history")
    if z < rules.volume_spike_z:
        return Rejected("no spike", f"z={z:.2f}")

    signal = window[-1]
    if signal.close <= signal.open:
        return Rejected("spike is downward")
    return _plan(signal=signal, entry=signal.close, stop=signal.low, rules=rules, equity=equity)


SIGNALS = (
    PaperSignal(
        "volume_spike",
        "Volume spike momentum",
        "Mesfin (2026) arXiv:2605.04004 §4.5",
        "FAIL — t=+0.07 on 2,119 events; a precise null, not an underpowered test",
        volume_spike_momentum,
        tested_on="MNQ (Micro E-Mini Nasdaq 100) futures, 5-minute bars, 947 days 2021-2025",
        recommended_class="futures",
        logic=(
            "Take the volume z-score against the previous 20 bars.",
            "Fire when z exceeds 2.0 and the bar closes up.",
            "Stop at the spike bar's low.",
        ),
    ),
)
