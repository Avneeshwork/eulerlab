"""Mid caps follow large caps, weekly (India).

Source: Sahoo & Kumar (2022), Southeast Asian Journal of Economics 10(2).

One daily strategy from a paper on Indian equities. Its rule and its library entry
(STRATEGIES, at the bottom) are both in this file.
"""

from __future__ import annotations

from eulerlab.backtest.strategy import MarketView, Strategy
from eulerlab.strategies.daily.india_papers.common import PaperStrategy


class LeadLag(Strategy):
    """Hold the follower ETF for a week after the leader rose over the week
    before (Sahoo & Kumar 2022: large caps lead mid and small caps)."""

    rebalance_every = 5
    lookback = 10

    def __init__(self, name: str, leader: str, follower: str) -> None:
        self.name = name
        self.leader = leader
        self.follower = follower
        self.hold_unchanged = True

    def target_weights(self, view: MarketView) -> dict[str, float]:
        lead = view.history.get(self.leader)
        follow = view.history.get(self.follower)
        if not lead or not follow or len(lead) < 6 or follow[-1].day != view.as_of:
            return {}
        return {self.follower: 1.0} if lead[-1].close > lead[-6].close else {}


STRATEGIES = (
    PaperStrategy(
        "india_midcap_follows_largecap",
        "Mid caps follow large caps, weekly (India)",
        "sahoo-2022-lead-lag-india",
        "Sahoo & Kumar (2022), Southeast Asian Journal of Economics 10(2)",
        "Hold the Midcap 150 ETF for a week after the Nifty 100 ETF rose over the week before.",
        (
            "Leader NIF100BEES, follower MID150BEES; both ETFs list from 2022.",
            "Weekly, because the engine fills a decision on the next close: a one-day lead "
            "would be lost to that lag.",
        ),
        10,
        lambda: LeadLag("india_midcap_follows_largecap", "NIF100BEES", "MID150BEES"),
        "all",
        ("NIF100BEES", "MID150BEES"),
    ),
)
