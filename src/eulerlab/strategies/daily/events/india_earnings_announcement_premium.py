"""Earnings announcement premium, expected reporters (India).

Source: Barber, De George, Lehavy & Trueman (2013), JFE 108(1); Frazzini & Lamont
(2007).

One daily earnings-event strategy. Its rule and its library entry (STRATEGIES, at the
bottom) are both in this file.
"""

from __future__ import annotations

from datetime import date, timedelta

from eulerlab.backtest.strategy import MarketView, Strategy
from eulerlab.strategies.daily.events.common import HOLD, WEEK, known_by
from eulerlab.strategies.daily.india_papers import PaperStrategy, liquid_universe


class AnnouncementPremium(Strategy):
    """Hold stocks expected to announce within `ahead` sessions, through the day after.

    Expected date: a known announcement 357-371 days ago, plus a year. Weekly.
    """

    def __init__(self, name: str, *, ahead: int = 10) -> None:
        self.name = name
        self.ahead = ahead
        self.rebalance_every = WEEK
        self.lookback = 70
        self.hold_unchanged = True

    def target_weights(self, view: MarketView) -> dict[str, float]:
        today = view.as_of
        horizon = today + timedelta(days=self.ahead * 7 // 5 + 2)
        due: list[tuple[date, str]] = []
        for symbol in liquid_universe(view):
            past = known_by(symbol, today)
            expected = [
                d + timedelta(days=364)
                for d in past
                if 357 <= (today - d).days <= 371 + self.ahead * 2
            ]
            soon = [e for e in expected if today - timedelta(days=1) <= e <= horizon]
            if soon:
                due.append((min(soon), symbol))
        # Fixed 1/HOLD weights, the soonest reporters first (research 113).
        due.sort()
        return {s: 1.0 / HOLD for _, s in due[:HOLD]}


STRATEGIES = (
    PaperStrategy(
        "india_earnings_announcement_premium",
        "Earnings announcement premium, expected reporters (India)",
        "barber-degeorge-lehavy-trueman-2013-announcement-premium",
        "Barber, De George, Lehavy & Trueman (2013), JFE 108(1); Frazzini & Lamont (2007)",
        "Hold stocks expected to report results within ten sessions, through the day after.",
        (
            "Expected date: the same quarter's NSE results disclosure a year earlier, plus 364 "
            "days, only from announcements known by the decision day.",
            "Weekly, up to 30 names, point-in-time 250 most-traded. Data: 2021-07 to 2024; "
            "run 2021-08 to 2024-11.",
        ),
        70,
        lambda: AnnouncementPremium("india_earnings_announcement_premium"),
    ),
)
