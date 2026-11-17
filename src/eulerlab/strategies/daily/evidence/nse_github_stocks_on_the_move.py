"""Clenow's Stocks on the Move, top 25 (GitHub rule).

Source: skyte/momentum (GitHub); Clenow (2015), Stocks on the Move.

One daily momentum or reversal refinement with published evidence. Its rule and its
library entry (STRATEGIES, at the bottom) are both in this file.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from itertools import pairwise

from eulerlab.backtest.strategy import MarketView, Strategy
from eulerlab.features.panel import PanelRow
from eulerlab.strategies.daily.evidence.common import WEEK
from eulerlab.strategies.daily.india_papers import PaperStrategy, liquid_universe


def clenow_score(rows: Sequence[PanelRow], days: int = 125) -> float | None:
    """skyte/momentum `momentum`: annualised exponential-regression slope x R^2,
    or None when the close is under its 100-day average or a day moved 15%."""
    if len(rows) < max(days, 100) + 1:
        return None
    closes = [r.close for r in rows[-days:]]
    if min(closes) <= 0 or closes[-1] < statistics.fmean(r.close for r in rows[-100:]):
        return None
    moves = [abs(b / a - 1.0) for a, b in pairwise(closes)]
    if max(moves) > 0.15:
        return None
    logs = [math.log(c) for c in closes]
    xs = list(range(days))
    mean_x, mean_y = statistics.fmean(xs), statistics.fmean(logs)
    sxx = sum((x - mean_x) ** 2 for x in xs)
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, logs, strict=True))
    syy = sum((y - mean_y) ** 2 for y in logs)
    if sxx <= 0 or syy <= 0:
        return None
    slope = sxy / sxx
    r2 = sxy * sxy / (sxx * syy)
    return (math.exp(slope) ** 252 - 1.0) * r2


def _atr20(rows: Sequence[PanelRow]) -> float | None:
    bars = [r.ohlc() for r in rows[-21:]]
    if len(bars) < 21:
        return None
    ranges = [
        max(h - lo, abs(h - prev[3]), abs(lo - prev[3])) for prev, (_, h, lo, _) in pairwise(bars)
    ]
    return statistics.fmean(ranges)


class StocksOnTheMove(Strategy):
    """Clenow's ranking (skyte/momentum), top 25, weekly, weights by inverse ATR.

    The repository sizes each position to risk the same rupees per ATR
    (risk parity); here that becomes weights proportional to close / ATR(20),
    normalised to the whole book. Clenow's book adds an index filter (stop
    buying when the index is under its 200-day average); the repository does
    not, and neither does this.

    Names are listed best score first and the weights are sizes, so a
    deployment too small for all 25 keeps them in score order
    (`ranked_by_order`, ADR-120).
    """

    ranked_by_order = True
    sizing = "strategy"  # inverse ATR is Clenow's own sizing (ADR-122)

    def __init__(self, name: str, *, hold: int = 25, universe: int = 250) -> None:
        self.name = name
        self.hold = hold
        self.universe = universe
        self.rebalance_every = WEEK
        self.lookback = 135

    def target_weights(self, view: MarketView) -> dict[str, float]:
        scored = []
        for symbol in liquid_universe(view, self.universe):
            rows = view.history[symbol]
            score = clenow_score(rows)
            atr = _atr20(rows) if score is not None else None
            if score is not None and atr and atr > 0:
                scored.append((score, symbol, rows[-1].close / atr))
        if len(scored) < self.hold:
            return {}
        scored.sort(key=lambda x: (-x[0], x[1]))
        chosen = scored[: self.hold]
        total = sum(w for _, _, w in chosen)
        return {s: w / total for _, s, w in chosen}


STRATEGIES = (
    PaperStrategy(
        "nse_github_stocks_on_the_move",
        "Clenow's Stocks on the Move, top 25 (GitHub rule)",
        "github-2021-skyte-clenow-momentum",
        "skyte/momentum (GitHub); Clenow (2015), Stocks on the Move",
        "Weekly, hold the 25 stocks with the steepest, smoothest 125-day trend, sized by inverse ATR.",
        (
            "Score: annualised slope of a 125-day regression of log price, times R^2. Out "
            "if under the 100-day average or any day moved more than 15%.",
            "Weights proportional to close / ATR(20), the repository's risk parity. No index "
            "filter, as in the repository. Point-in-time 250 most-traded.",
        ),
        135,
        lambda: StocksOnTheMove("nse_github_stocks_on_the_move"),
    ),
)
