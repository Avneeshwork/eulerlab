"""Faber tactical allocation, Indian ETFs (GitHub rule).

Source: mmoraschini/faber-taa (GitHub, 2023).

One daily rule from a public GitHub repository. Its rule and its library entry
(STRATEGIES, at the bottom) are both in this file.
"""

from __future__ import annotations

from eulerlab.backtest.strategy import MarketView, Strategy
from eulerlab.strategies.daily.github.common import _closes
from eulerlab.strategies.daily.india_papers import MONTH, PaperStrategy

FABER = ("NIFTYBEES", "JUNIORBEES", "GOLDBEES", "MON100")
"""Faber's GTAA classes, as Indian ETFs: large caps, mid caps, gold, US stocks."""
CASH = "LIQUIDBEES"


class FaberTAA(Strategy):
    """mmoraschini/faber-taa on Indian ETFs: each month, each sleeve holds its
    ETF while the close is above its 10-month average (the mean daily close over
    the last ten months, as the repository computes it), else LIQUIDBEES. A
    sleeve whose ETF has under ten months of history sits in LIQUIDBEES."""

    sizing = "strategy"  # fixed sleeve weights are the allocation itself (ADR-122)

    def __init__(self, name: str) -> None:
        self.name = name
        self.rebalance_every = MONTH
        self.lookback = 10 * MONTH + 5

    def target_weights(self, view: MarketView) -> dict[str, float]:
        weights: dict[str, float] = {}
        share = 1.0 / len(FABER)
        for symbol in FABER:
            rows = view.history.get(symbol) or []
            closes = _closes(rows[-10 * MONTH :])
            above = len(closes) >= 10 * MONTH and closes[-1] > sum(closes) / len(closes)
            chosen = symbol if above and rows[-1].day == view.as_of else CASH
            weights[chosen] = weights.get(chosen, 0.0) + share
        return weights


STRATEGIES = (
    PaperStrategy(
        "nse_github_faber_taa_etf",
        "Faber tactical allocation, Indian ETFs (GitHub rule)",
        "github-2023-faber-taa",
        "mmoraschini/faber-taa (GitHub, 2023)",
        "Each month, a quarter in each of NIFTYBEES, JUNIORBEES, GOLDBEES and MON100 while above its 10-month average; otherwise that quarter in LIQUIDBEES.",
        (
            "10-month average = mean daily close over the last 210 sessions, as the "
            "repository computes it from monthly sums and counts.",
            "MON100 trades from June 2021; before that its quarter sits in LIQUIDBEES.",
        ),
        10 * MONTH + 5,
        lambda: FaberTAA("nse_github_faber_taa_etf"),
        "all",
        (*FABER, CASH),
    ),
)
