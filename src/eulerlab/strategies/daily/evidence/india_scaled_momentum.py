"""Volatility-scaled momentum, long only (India).

Source: Barroso & Santa-Clara (2015), JFE 116(1).

One daily momentum or reversal refinement with published evidence. Its rule and its
library entry (STRATEGIES, at the bottom) are both in this file.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from itertools import pairwise

from eulerlab.backtest.strategy import MarketView, Strategy
from eulerlab.strategies.daily.evidence.common import HOLD, momentum_12_1
from eulerlab.strategies.daily.india_papers import MONTH, YEAR, PaperStrategy, liquid_universe


class ScaledMomentum(Strategy):
    """The `HOLD` best 12-1 performers, exposure scaled by long-run over 6-month vol.

    Long only, so the paper's scaled long-short portfolio becomes a scaled long
    book with the rest in cash. The target is the selection's own three-year
    volatility rather than a chosen number, so nothing here is tuned; the
    scale is capped at 1 (no leverage).
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self.rebalance_every = MONTH
        self.lookback = 3 * YEAR + 10

    def target_weights(self, view: MarketView) -> dict[str, float]:
        scored = []
        for symbol in liquid_universe(view):
            past = momentum_12_1(view.history[symbol])
            if past is not None:
                scored.append((past, symbol))
        if len(scored) < 3 * HOLD:
            return {}
        scored.sort(key=lambda x: (-x[0], x[1]))
        chosen = [s for _, s in scored[:HOLD]]
        book = _book_returns(view, chosen, 3 * YEAR)
        if len(book) < YEAR:
            return {}
        recent, long_run = statistics.pstdev(book[-126:]), statistics.pstdev(book)
        scale = min(1.0, long_run / recent) if recent > 0 else 1.0
        return {s: scale / len(chosen) for s in chosen}


def _book_returns(view: MarketView, chosen: Sequence[str], days: int) -> list[float]:
    """Daily returns of an equal-weight book of `chosen`, over the last `days`."""
    by_day: dict[object, list[float]] = {}
    for symbol in chosen:
        rows = view.history[symbol][-days - 1 :]
        for a, b in pairwise(rows):
            if a.close > 0:
                by_day.setdefault(b.day, []).append(b.close / a.close - 1.0)
    return [statistics.fmean(v) for _, v in sorted(by_day.items())]


STRATEGIES = (
    PaperStrategy(
        "india_scaled_momentum",
        "Volatility-scaled momentum, long only (India)",
        "barroso-santa-clara-2015-momentum-moments",
        "Barroso & Santa-Clara (2015), JFE 116(1)",
        "Hold the 30 best 12-1 performers, cutting exposure when their 6-month volatility runs above its 3-year level.",
        (
            "Scale = 3-year / 6-month (126-day) volatility of the equal-weight selection, "
            "capped at 1; the remainder stays in cash.",
            "The paper scales a long-short portfolio to a target; here the target is the "
            "book's own long-run volatility, so no number is chosen. Monthly.",
        ),
        3 * YEAR + 10,
        lambda: ScaledMomentum("india_scaled_momentum"),
    ),
)
