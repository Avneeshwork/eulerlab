"""Weinstein Stage 2 with Mansfield RS (GitHub rule).

Source: abeer555/Trend-Radar `mansfield.py` (GitHub); Weinstein (1988), Secrets for
Profiting in Bull and Bear Markets.

One daily momentum or reversal refinement with published evidence. Its rule and its
library entry (STRATEGIES, at the bottom) are both in this file.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from datetime import date

from eulerlab.backtest.strategy import MarketView, Strategy
from eulerlab.features.panel import PanelRow
from eulerlab.strategies.daily.evidence.common import WEEK
from eulerlab.strategies.daily.india_papers import (
    INDEX_ETF,
    MONTH,
    YEAR,
    PaperStrategy,
    liquid_universe,
)


def mansfield_rs(rows: Sequence[PanelRow], market: dict[date, float]) -> float | None:
    """abeer555/Trend-Radar `compute_mansfield`: (stock / benchmark) now over the
    same ratio 52 weeks ago, less 1. NIFTYBEES stands in for the Nifty 50."""
    if len(rows) <= YEAR:
        return None
    now, then = rows[-1], rows[-1 - YEAR]
    m_now, m_then = market.get(now.day), market.get(then.day)
    if not m_now or not m_then or then.close <= 0:
        return None
    return (now.close / m_now) / (then.close / m_then) - 1.0


def stage_two(rows: Sequence[PanelRow], rising_over: int = MONTH) -> bool:
    """Weinstein's Stage 2: the close above a rising 30-week (150-day) average."""
    if len(rows) < 150 + rising_over:
        return False
    closes = [r.close for r in rows]
    now = statistics.fmean(closes[-150:])
    before = statistics.fmean(closes[-150 - rising_over : -rising_over])
    return closes[-1] > now > before


class WeinsteinStageTwo(Strategy):
    """Weekly, the `hold` Stage-2 stocks with the highest positive Mansfield RS.

    Fixed 1/`hold` weights. "Rising" is the average over a month ago, as
    Trend-Radar's stage test compares the 30-week average with its earlier
    value; the exact look-back there was not read.
    """

    def __init__(self, name: str, *, hold: int = 20) -> None:
        self.name = name
        self.hold = hold
        self.rebalance_every = WEEK
        self.lookback = YEAR + 30
        self.hold_unchanged = True

    def target_weights(self, view: MarketView) -> dict[str, float]:
        market = {r.day: r.close for r in view.history.get(INDEX_ETF) or []}
        scored = []
        for symbol in liquid_universe(view):
            rows = view.history[symbol]
            rs = mansfield_rs(rows, market)
            if rs is not None and rs > 0 and stage_two(rows):
                scored.append((rs, symbol))
        scored.sort(key=lambda x: (-x[0], x[1]))
        return {s: 1.0 / self.hold for _, s in scored[: self.hold]}


STRATEGIES = (
    PaperStrategy(
        "nse_github_weinstein_stage2",
        "Weinstein Stage 2 with Mansfield RS (GitHub rule)",
        "github-2026-trend-radar-minervini",
        "abeer555/Trend-Radar `mansfield.py` (GitHub); Weinstein (1988), Secrets for Profiting in Bull and Bear Markets",
        "Weekly, hold the 20 stocks above a rising 30-week average that have beaten the Nifty most over a year.",
        (
            "Stage 2: close above the 150-day average, itself above its level a month ago. "
            "Mansfield RS: stock/NIFTYBEES now over the same ratio 52 weeks ago, less 1; above 0.",
            "Top 20 by RS, fixed twentieths, point-in-time 250 most-traded.",
        ),
        YEAR + 30,
        lambda: WeinsteinStageTwo("nse_github_weinstein_stage2"),
    ),
)
