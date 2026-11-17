"""Halloween effect: Nifty in winter, cash in summer (India).

Source: Jacobsen & Zhang (2018), The Halloween Indicator, 'Sell in May and Go Away':
Everywhere and All the Time.

One daily momentum or reversal refinement with published evidence. Its rule and its
library entry (STRATEGIES, at the bottom) are both in this file.
"""

from __future__ import annotations

from eulerlab.backtest.strategy import MarketView, Strategy
from eulerlab.strategies.daily.evidence.common import SAFE
from eulerlab.strategies.daily.india_papers import INDEX_ETF, PaperStrategy

WINTER = (11, 12, 1, 2, 3, 4)


class Halloween(Strategy):
    """Jacobsen & Zhang (2018): NIFTYBEES from November to April, LIQUIDBEES from
    May to October. Decided at each close: the engine fills at the next close,
    so the switch lands on the first session of the new season."""

    rebalance_every = 1

    def __init__(self, name: str) -> None:
        self.name = name
        self.lookback = 2
        # The target is the same 100% every day within a season; without this
        # the engine would trim the position to equity every day.
        self.hold_unchanged = True

    def target_weights(self, view: MarketView) -> dict[str, float]:
        return {INDEX_ETF if view.as_of.month in WINTER else SAFE: 1.0}


STRATEGIES = (
    PaperStrategy(
        "india_halloween_nifty",
        "Halloween effect: Nifty in winter, cash in summer (India)",
        "jacobsen-zhang-2018-halloween-everywhere",
        "Jacobsen & Zhang (2018), The Halloween Indicator, 'Sell in May and Go Away': Everywhere and All the Time",
        "Hold NIFTYBEES from November to April and LIQUIDBEES from May to October.",
        (
            "Winter returns beat summer returns by about 4.5 points a year across 114 "
            "markets over 320 years, significant in 42; India's own figure was not read.",
            "Two switches a year; LIQUIDBEES stands in for cash.",
        ),
        2,
        lambda: Halloween("india_halloween_nifty"),
        "all",
        (INDEX_ETF, SAFE),
    ),
)
