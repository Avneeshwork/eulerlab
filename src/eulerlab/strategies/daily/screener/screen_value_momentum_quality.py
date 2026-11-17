"""Value, momentum and quality.

Source: Asness, Moskowitz and Pedersen (2013); Novy-Marx (2013).

One stock-screener model. Its rule and its library entry (SPECS, at the bottom) are both
in this file.
"""

from __future__ import annotations

from eulerlab.backtest.strategy import MarketView, Strategy
from eulerlab.strategies.daily.india_papers import MONTH, YEAR, PaperStrategy, momentum
from eulerlab.strategies.daily.screener.common import (
    LONG,
    _mean_of,
    _top,
    _universe_facts,
    _z,
    quality,
)


class ValueMomentumQuality(Strategy):
    """Equal blend of value, quality and 12-1 momentum ranks (H-0031)."""

    rebalance_every = MONTH
    lookback = YEAR + 10

    def __init__(self) -> None:
        self.name = "screen_value_momentum_quality"
        self.mom = momentum(YEAR, MONTH)

    def target_weights(self, view: MarketView) -> dict[str, float]:
        _, f = _universe_facts(view)
        if len(f) < 40:
            return {}
        value = _mean_of(
            [
                _z({s: v["earnings_yield"] for s, v in f.items() if "earnings_yield" in v}),
                _z({s: v["book_yield"] for s, v in f.items() if "book_yield" in v}),
            ],
            f,
        )
        mom = _z({s: m for s in f if (m := self.mom(view.history[s])) is not None})
        blend = _mean_of([value, quality(f), mom], f)
        return _top(blend)


SPECS = (
    (
        PaperStrategy(
            id="screen_value_momentum_quality",
            title="Value, momentum and quality",
            paper="asness-moskowitz-pedersen-2013-value-momentum-everywhere",
            citation="Asness, Moskowitz and Pedersen (2013); Novy-Marx (2013)",
            summary="Equal blend of value, quality and 12-1 momentum ranks; top 20, monthly.",
            logic=(
                "Value: mean rank of earnings yield and book yield.",
                "Blend with quality and 12-1 month momentum ranks, equally.",
                "Hold the top 20 equally; rebalance every 21 sessions.",
            ),
            lookback=YEAR + 10,
            build=ValueMomentumQuality,
        ),
        LONG,
    ),
)
