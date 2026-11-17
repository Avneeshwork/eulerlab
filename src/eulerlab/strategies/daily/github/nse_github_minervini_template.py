"""Minervini trend template, top 20 by RS (GitHub rule).

Source: abeer555/Trend-Radar (GitHub, 2026).

One daily rule from a public GitHub repository. Its rule and its library entry
(STRATEGIES, at the bottom) are both in this file.
"""

from __future__ import annotations

from collections.abc import Sequence

from eulerlab.backtest.strategy import MarketView, Strategy
from eulerlab.strategies.daily.github.common import _closes
from eulerlab.strategies.daily.india_papers import MONTH, YEAR, PaperStrategy, liquid_universe

RS_WEIGHTS = ((63, 0.40), (126, 0.20), (189, 0.20), (252, 0.20))
"""abeer555/Trend-Radar `RS_WEIGHTS`: 3, 6, 9 and 12-month returns."""


def rs_raw(closes: Sequence[float]) -> float | None:
    if len(closes) <= 252 or closes[-253] <= 0:
        return None
    return sum(w * (closes[-1] / closes[-1 - d] - 1.0) for d, w in RS_WEIGHTS)


def trend_template(closes: Sequence[float]) -> bool:
    """abeer555/Trend-Radar `compute_trend_template`, the seven price criteria."""
    if len(closes) < 200 + 22:
        return False
    price = closes[-1]
    ma50, ma150, ma200 = (sum(closes[-k:]) / k for k in (50, 150, 200))
    ma200_month_ago = sum(closes[-222:-22]) / 200
    year = closes[-252:]
    high, low = max(year), min(year)
    return (
        price > ma50
        and price > ma150
        and price > ma200
        and ma150 > ma200
        and ma200 > ma200_month_ago
        and (price - low) / low >= 0.30
        and (high - price) / high <= 0.25
    )


class TrendTemplate(Strategy):
    """Each month, the stocks passing all eight criteria, top 20 by RS score.

    The eighth criterion is the RS rank gate (70, Trend-Radar's
    `TT_MIN_RS_RANK`): a stock's RS composite must be at or above the 70th
    percentile of the point-in-time top 250.
    """

    def __init__(self, name: str, *, hold: int = 20) -> None:
        self.name = name
        self.hold = hold
        self.rebalance_every = MONTH
        self.lookback = YEAR + 30

    def target_weights(self, view: MarketView) -> dict[str, float]:
        scored: list[tuple[float, str, bool]] = []
        for symbol in liquid_universe(view):
            closes = _closes(view.history[symbol])
            score = rs_raw(closes)
            if score is not None:
                scored.append((score, symbol, trend_template(closes)))
        if not scored:
            return {}
        ordered = sorted(score for score, _, _ in scored)
        gate = ordered[int(0.70 * (len(ordered) - 1))]
        passing = sorted(
            ((score, symbol) for score, symbol, ok in scored if ok and score >= gate),
            key=lambda item: (-item[0], item[1]),
        )[: self.hold]
        return {symbol: 1.0 / self.hold for _, symbol in passing}


STRATEGIES = (
    PaperStrategy(
        "nse_github_minervini_template",
        "Minervini trend template, top 20 by RS (GitHub rule)",
        "github-2026-trend-radar-minervini",
        "abeer555/Trend-Radar (GitHub, 2026)",
        "Each month, hold up to 20 stocks that pass all eight trend-template criteria, ranked by relative strength.",
        (
            "Price above the 50, 150 and 200-day averages; 150 above 200; 200 rising over a "
            "month; at least 30% above the 52-week low and within 25% of the high.",
            "RS = 0.4 x 3-month + 0.2 x each of 6, 9 and 12-month return; RS at or above the "
            "70th percentile of the point-in-time 250. Equal twentieths; monthly.",
        ),
        YEAR + 30,
        lambda: TrendTemplate("nse_github_minervini_template"),
    ),
)
