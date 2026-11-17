"""Top 5 sectors.

Source: Moskowitz and Grinblatt (1999); Sehgal and Jain (2011); research 182.

One stock-screener model. Its rule and its library entry (SPECS, at the bottom) are both
in this file.
"""

from __future__ import annotations

from eulerlab.backtest import topdown
from eulerlab.backtest.strategy import MarketView, Strategy
from eulerlab.strategies.daily.india_papers import MONTH, PaperStrategy, liquid_universe
from eulerlab.strategies.daily.screener.common import _TOPDOWN_FUNNEL, LONG


class TopDownSectors(Strategy):
    """Every liquid stock in the top 5 sectors; a fifth to each sector, equal inside it."""

    rebalance_every = MONTH
    lookback = topdown.FORMATION + 10

    def __init__(self) -> None:
        self.name = "screen_topdown_sectors"

    def target_weights(self, view: MarketView) -> dict[str, float]:
        names = liquid_universe(view)
        rk = topdown.rank(view, names)
        out: dict[str, float] = {}
        for sec in rk.top_sectors:
            members = [s for s in names if rk.sector_of.get(s) == sec]
            for s in members:
                out[s] = 1.0 / len(rk.top_sectors) / len(members)
        return out


SPECS = (
    (
        PaperStrategy(
            id="screen_topdown_sectors",
            title="Top 5 sectors",
            paper="moskowitz-grinblatt-1999-industry-momentum",
            citation="Moskowitz and Grinblatt (1999); Sehgal and Jain (2011); research 182",
            summary="Every liquid stock in the five sectors with the best six months; monthly.",
            logic=(
                _TOPDOWN_FUNNEL[0],
                "A fifth of capital to each top sector, equal inside it. Rebalanced every 21 sessions.",
                _TOPDOWN_FUNNEL[1],
            ),
            lookback=topdown.FORMATION + 10,
            build=TopDownSectors,
        ),
        LONG,
    ),
)
