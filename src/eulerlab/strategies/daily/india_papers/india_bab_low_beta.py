"""Betting against beta, long leg (India).

Source: Agarwalla, Jacob, Varma & Vasudevan (2014), IIMA WP 2014-07-01.

One daily strategy from a paper on Indian equities. Its rule and its library entry
(STRATEGIES, at the bottom) are both in this file.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import date

from eulerlab.backtest.strategy import MarketView, Strategy, normalise
from eulerlab.features.panel import PanelRow
from eulerlab.strategies.daily.india_papers.common import (
    INDEX_ETF,
    MONTH,
    YEAR,
    PaperStrategy,
    _returns,
    _sd,
    liquid_universe,
)


class LowBeta(Strategy):
    """The long leg of Betting Against Beta (Agarwalla et al. 2014).

    Beta = correlation of 3-day overlapping returns over 5 years (at least 750
    days) times the ratio of 1-year daily volatilities (at least 120 days),
    shrunk 0.6 toward 1. The market is NIFTYBEES, standing in for the Sensex.
    Stocks below the median beta are held with the paper's rank weights,
    unlevered.
    """

    rebalance_every = MONTH
    lookback = 5 * YEAR + 5

    sizing = "strategy"  # beta-based weights are the paper's portfolio (ADR-122)

    def __init__(self) -> None:
        self.name = "india_bab_low_beta"

    @staticmethod
    def _three_day(rows: Sequence[PanelRow]) -> dict[date, float]:
        return {
            rows[i].day: rows[i].close / rows[i - 3].close - 1.0
            for i in range(3, len(rows))
            if rows[i - 3].close > 0
        }

    def target_weights(self, view: MarketView) -> dict[str, float]:
        market = view.history.get(INDEX_ETF)
        if not market or len(market) < 750:
            return {}
        market_3d = self._three_day(market[-5 * YEAR :])
        market_daily = dict(zip([r.day for r in market[1:]], _returns(market), strict=False))
        market_sd = _sd(
            [market_daily[d] for d in [r.day for r in market[-YEAR:]] if d in market_daily]
        )
        if not market_sd:
            return {}

        betas: list[tuple[float, str]] = []
        for symbol in liquid_universe(view):
            rows = view.history[symbol]
            own_3d = self._three_day(rows[-5 * YEAR :])
            common = [d for d in own_3d if d in market_3d]
            if len(common) < 750:
                continue
            xs = [own_3d[d] for d in common]
            ys = [market_3d[d] for d in common]
            mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
            cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
            vx = sum((x - mx) ** 2 for x in xs)
            vy = sum((y - my) ** 2 for y in ys)
            if vx <= 0 or vy <= 0:
                continue
            rho = cov / math.sqrt(vx * vy)
            own_sd = _sd(_returns(rows[-YEAR - 1 :]))
            if own_sd is None or len(rows) < 121:
                continue
            beta = rho * own_sd / market_sd
            betas.append((0.6 * beta + 0.4, symbol))
        if len(betas) < 30:
            return {}
        betas.sort()
        ranks = {symbol: i + 1 for i, (_, symbol) in enumerate(betas)}
        mean_rank = (len(betas) + 1) / 2
        low = {s: mean_rank - r for s, r in ranks.items() if r < mean_rank}
        total = sum(low.values())
        return normalise({s: w / total for s, w in low.items()})


STRATEGIES = (
    PaperStrategy(
        "india_bab_low_beta",
        "Betting against beta, long leg (India)",
        "agarwalla-2014-betting-against-beta-india",
        "Agarwalla, Jacob, Varma & Vasudevan (2014), IIMA WP 2014-07-01",
        "Hold the below-median-beta half of the point-in-time top 250, rank-weighted toward the lowest beta.",
        (
            "Beta: correlation of 3-day returns with NIFTYBEES over 5 years (750+ days) "
            "times the ratio of 1-year daily volatilities, shrunk 0.6 toward 1.",
            "Each month, hold stocks below the median beta, weighted by distance below "
            "the mean rank. Unlevered and long only: the paper's short leg is dropped.",
        ),
        5 * YEAR + 5,
        LowBeta,
    ),
)
