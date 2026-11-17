"""Piotroski value.

Source: Piotroski (2000).

One stock-screener model. Its rule and its library entry (SPECS, at the bottom) are both
in this file.
"""

from __future__ import annotations

from eulerlab.backtest.strategy import MarketView, Strategy
from eulerlab.strategies.daily.india_papers import MONTH, PaperStrategy
from eulerlab.strategies.daily.screener.common import LONG, TOP, _universe_facts


class Piotroski(Strategy):
    """Cheapest 30% on book yield with an F-score of 6 or more of 8 (H-0032)."""

    rebalance_every = 3 * MONTH
    lookback = 70

    def __init__(self) -> None:
        self.name = "screen_piotroski"

    def target_weights(self, view: MarketView) -> dict[str, float]:
        _, f = _universe_facts(view)
        cheap = sorted(
            (s for s in f if "book_yield" in f[s] and f[s]["book_yield"] > 0),
            key=lambda s: (-f[s]["book_yield"], s),
        )
        cheap = cheap[: max(1, round(len(cheap) * 0.3))]
        held = [s for s in cheap if f[s].get("fscore", 0) >= 6]
        if not held:
            return {}
        held = held[: TOP + 10]
        return dict.fromkeys(held, 1.0 / len(held))


SPECS = (
    (
        PaperStrategy(
            id="screen_piotroski",
            title="Piotroski value",
            paper="piotroski-2000-fscore",
            citation="Piotroski (2000)",
            summary="The cheapest 30% on book yield with an F-score of 6 or more of 8; quarterly.",
            logic=(
                "Book yield from the last annual statement known 90 days after the year end.",
                "F-score from 8 of Piotroski's 9 signals.",
                "Hold up to 30 equally; rebalance every 63 sessions.",
            ),
            lookback=70,
            build=Piotroski,
        ),
        LONG,
    ),
)
