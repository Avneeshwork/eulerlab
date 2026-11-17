"""Tree ranker.

Source: Gu, Kelly and Xiu (2020).

One stock-screener model. Its rule and its library entry (SPECS, at the bottom) are both
in this file.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

from eulerlab.backtest.strategy import MarketView, Strategy
from eulerlab.features.panel import PanelRow
from eulerlab.strategies.daily.india_papers import MONTH, YEAR, PaperStrategy, liquid_universe
from eulerlab.strategies.daily.screener.common import LONG, _top, _z, facts


def features(rows: Sequence[PanelRow], f: Mapping[str, float] | None) -> list[float] | None:
    """The tree model's inputs at the last row; NaN where a value is missing."""
    if len(rows) < YEAR + 1:
        return None
    c = [r.close for r in rows]
    rets = [b / a - 1 for a, b in zip(c[-61:-1], c[-60:], strict=True) if a > 0]
    vol = (sum(x * x for x in rets) / len(rets)) ** 0.5 if rets else math.nan
    turn = sorted(r.turnover for r in rows[-60:])
    hi = max(c[-YEAR:])
    nan = math.nan
    g = f or {}
    return [
        c[-1] / c[-1 - MONTH] - 1,
        c[-1] / c[-1 - 6 * MONTH] - 1,
        c[-1 - MONTH] / c[-1 - YEAR] - 1,
        vol,
        math.log(turn[len(turn) // 2] + 1),
        c[-1] / hi if hi > 0 else nan,
        g.get("roe", nan),
        g.get("op_assets", nan),
        g.get("leverage", nan),
        g.get("earnings_yield", nan),
        g.get("book_yield", nan),
    ]


class TreeRanker(Strategy):
    """Gradient-boosted trees on price and fundamental features, refit each month (H-0033).

    Pure: the training set is built from the view alone. At each decision date
    the model learns, on the previous 24 month-ends in the view, the
    cross-sectional rank of each liquid stock's next-month return from its
    features at that month-end, then ranks today's stocks. Fixed settings,
    `random_state=0`.
    """

    rebalance_every = MONTH
    lookback = 3 * YEAR + 30
    TRAIN_MONTHS = 24

    def __init__(self) -> None:
        self.name = "screen_tree_ranker"

    def _snapshot(self, view: MarketView, end: int) -> dict[str, tuple[list[float], PanelRow]]:
        """Features for each liquid stock using its rows up to `end` sessions before the view's last."""
        out: dict[str, tuple[list[float], PanelRow]] = {}
        for s in liquid_universe(view):
            rows = view.history[s]
            past = rows[: len(rows) - end] if end else rows
            if len(past) < YEAR + 1:
                continue
            last = past[-1]
            x = features(past, facts(last.isin, last.day, last.close))
            if x is not None:
                out[s] = (x, last)
        return out

    def target_weights(self, view: MarketView) -> dict[str, float]:
        try:
            from sklearn.ensemble import HistGradientBoostingRegressor
        except ImportError:
            return {}
        X: list[list[float]] = []
        y: list[float] = []
        for k in range(1, self.TRAIN_MONTHS + 1):
            then, after = self._snapshot(view, k * MONTH), self._snapshot(view, (k - 1) * MONTH)
            fwd = {
                s: after[s][1].close / then[s][1].close - 1
                for s in then
                if s in after and then[s][1].close > 0
            }
            ranks = _z(fwd)
            for s, r in ranks.items():
                X.append(then[s][0])
                y.append(r)
        now = self._snapshot(view, 0)
        if len(y) < 1000 or len(now) < 40:
            return {}
        model = HistGradientBoostingRegressor(
            max_iter=200, learning_rate=0.05, max_leaf_nodes=15, min_samples_leaf=50, random_state=0
        )
        model.fit(X, y)
        names = sorted(now)
        pred = model.predict([now[s][0] for s in names])
        return _top({s: float(p) for s, p in zip(names, pred, strict=True)})


SPECS = (
    (
        PaperStrategy(
            id="screen_tree_ranker",
            title="Tree ranker",
            paper="gu-kelly-xiu-2020-ml-asset-pricing",
            citation="Gu, Kelly and Xiu (2020)",
            summary="Gradient-boosted trees on 11 price and fundamental features, refit monthly on 24 months; top 20.",
            logic=(
                "Learn next-month return rank from features at each of the last 24 month-ends.",
                "Rank today's liquid 250; hold the top 20 equally; rebalance every 21 sessions.",
            ),
            lookback=3 * YEAR + 30,
            build=TreeRanker,
        ),
        LONG,
    ),
)
