"""Top-down momentum at a discount to peers.

Source: Asness, Porter and Stevens (2000); Moskowitz and Grinblatt (1999); research 182.

One stock-screener model. Its rule and its library entry (SPECS, at the bottom) are both
in this file.
"""

from __future__ import annotations

from collections.abc import Mapping
from statistics import median

from eulerlab.backtest import topdown
from eulerlab.backtest.strategy import MarketView, Strategy
from eulerlab.strategies.daily.india_papers import (
    MONTH,
    YEAR,
    PaperStrategy,
    sharpe_momentum_over,
)
from eulerlab.strategies.daily.screener.common import (
    _TOPDOWN_FUNNEL,
    LONG,
    _capped,
    _mean_of,
    _universe_facts,
    _z,
)


def industry_relative(values: Mapping[str, float], ranking: topdown.Ranking) -> dict[str, float]:
    """Each value less the median of its industry (3 or more with a value), else of its sector."""
    by_ind: dict[str, list[float]] = {}
    by_sec: dict[str, list[float]] = {}
    for s, v in values.items():
        if s in ranking.industry_of:
            by_ind.setdefault(ranking.industry_of[s], []).append(v)
            by_sec.setdefault(ranking.sector_of[s], []).append(v)
    out: dict[str, float] = {}
    for s, v in values.items():
        if s not in ranking.industry_of:
            continue
        peers = by_ind[ranking.industry_of[s]]
        if len(peers) < topdown.MIN_MEMBERS:
            peers = by_sec[ranking.sector_of[s]]
        if len(peers) >= topdown.MIN_MEMBERS:
            out[s] = v - median(peers)
    return out


class TopDownDiscount(Strategy):
    """The same funnel, ranked on momentum and on cheapness against industry peers."""

    rebalance_every = MONTH
    lookback = YEAR + 10

    def __init__(self) -> None:
        self.name = "screen_topdown_discount"
        self.score = sharpe_momentum_over(YEAR)

    def target_weights(self, view: MarketView) -> dict[str, float]:
        names, f = _universe_facts(view)
        if len(f) < 40:
            return {}
        rk = topdown.rank(view, names)
        ey = {s: v["earnings_yield"] for s, v in f.items() if "earnings_yield" in v}
        rel = industry_relative(ey, rk)
        cands = [s for s in rel if ey[s] > 0 and rk.passes(s)]
        mom = {s: m for s in cands if (m := self.score(view.history[s])) is not None}
        if not mom:
            return {}
        blend = _mean_of([_z(mom), _z({s: rel[s] for s in mom})], mom)
        return _capped(blend, rk.sector_of)


SPECS = (
    (
        PaperStrategy(
            id="screen_topdown_discount",
            title="Top-down momentum at a discount to peers",
            paper="asness-porter-stevens-2000-industry-relative",
            citation="Asness, Porter and Stevens (2000); Moskowitz and Grinblatt (1999); research 182",
            summary="Top 5 sectors, strong industries; momentum plus earnings yield above the industry median.",
            logic=(
                *_TOPDOWN_FUNNEL,
                "Earnings yield positive; score = mean rank of Sharpe momentum and of earnings "
                "yield less its industry median (sector median under 3 peers).",
                "Top 20, at most 6 from one sector, equal; rebalanced every 21 sessions.",
            ),
            lookback=YEAR + 10,
            build=TopDownDiscount,
        ),
        LONG,
    ),
)
