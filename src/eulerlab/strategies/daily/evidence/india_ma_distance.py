"""Moving-average distance, 21 over 200 days (India).

Source: Avramov, Kaplanski & Subrahmanyam (2021), Review of Financial Economics 39(2).

One daily momentum or reversal refinement with published evidence. Its rule and its
library entry (STRATEGIES, at the bottom) are both in this file.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence

from eulerlab.backtest.strategy import MarketView, Strategy
from eulerlab.features.panel import PanelRow
from eulerlab.strategies.daily.evidence.common import HOLD, _equal
from eulerlab.strategies.daily.india_papers import MONTH, PaperStrategy, liquid_universe


def ma_distance(rows: Sequence[PanelRow]) -> float | None:
    """Avramov, Kaplanski & Subrahmanyam: the 21-day over the 200-day average close."""
    if len(rows) < 200:
        return None
    closes = [r.close for r in rows[-200:]]
    long_run = statistics.fmean(closes)
    return statistics.fmean(closes[-21:]) / long_run if long_run > 0 else None


class MovingAverageDistance(Strategy):
    """Each month, the `hold` stocks with the highest MA(21) / MA(200)."""

    def __init__(self, name: str, *, hold: int = HOLD) -> None:
        self.name = name
        self.hold = hold
        self.rebalance_every = MONTH
        self.lookback = 210

    def target_weights(self, view: MarketView) -> dict[str, float]:
        scored = []
        for symbol in liquid_universe(view):
            distance = ma_distance(view.history[symbol])
            if distance is not None:
                scored.append((distance, symbol))
        if len(scored) < 3 * self.hold:
            return {}
        scored.sort(key=lambda x: (-x[0], x[1]))
        return _equal([s for _, s in scored[: self.hold]])


STRATEGIES = (
    PaperStrategy(
        "india_ma_distance",
        "Moving-average distance, 21 over 200 days (India)",
        "avramov-kaplanski-subrahmanyam-2021-ma-distance",
        "Avramov, Kaplanski & Subrahmanyam (2021), Review of Financial Economics 39(2)",
        "Each month, hold the 30 stocks whose 21-day average is highest relative to their 200-day average.",
        (
            "MAD = MA(21) / MA(200) of the close; the paper buys the top decile and finds "
            "the effect beyond momentum and the 52-week high, also outside the US.",
            "Monthly, equal weight, point-in-time 250 most-traded. Long only.",
        ),
        210,
        lambda: MovingAverageDistance("india_ma_distance"),
    ),
)
