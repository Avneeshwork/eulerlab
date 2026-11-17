"""Post-earnings drift by announcement return (India).

Source: Chan, Jegadeesh & Lakonishok (1996), JF 51(5); Indian drift 2002-2017 (research
113).

One daily earnings-event strategy. Its rule and its library entry (STRATEGIES, at the
bottom) are both in this file.
"""

from __future__ import annotations

from bisect import bisect_right

from eulerlab.backtest.strategy import MarketView, Strategy
from eulerlab.strategies.daily.events.common import HOLD, WEEK, _index_at, known_by
from eulerlab.strategies.daily.india_papers import INDEX_ETF, PaperStrategy, liquid_universe


class AnnouncementDrift(Strategy):
    """Hold the top fifth of recent announcers by two-day announcement return.

    Formation: close the day before the announcement to the close the day after,
    less NIFTYBEES over the same days. Held from two sessions after the
    announcement to sixty. Weekly.
    """

    def __init__(self, name: str, *, hold_days: int = 60, top: float = 0.2) -> None:
        self.name = name
        self.hold_days = hold_days
        self.top = top
        self.rebalance_every = WEEK
        self.lookback = hold_days + 70
        self.hold_unchanged = True

    def target_weights(self, view: MarketView) -> dict[str, float]:
        market = view.history.get(INDEX_ETF) or []
        if not market:
            return {}
        scored: list[tuple[float, str]] = []
        for symbol in liquid_universe(view):
            rows = view.history[symbol]
            for day in reversed(known_by(symbol, view.as_of)):
                i = _index_at(rows, day)
                if i >= len(rows) or i < 1:
                    continue
                after = len(rows) - 1 - i
                if after > self.hold_days:
                    break
                if after < 2:
                    continue
                m = _index_at(market, rows[i - 1].day)
                n = bisect_right([r.day for r in market], rows[i + 1].day) - 1
                if m >= len(market) or n < m or market[m].close <= 0 or rows[i - 1].close <= 0:
                    continue
                excess = (rows[i + 1].close / rows[i - 1].close) - (
                    market[n].close / market[m].close
                )
                scored.append((excess, symbol))
                break
        if len(scored) < 10:
            return {}
        scored.sort(key=lambda x: (-x[0], x[1]))
        keep = [s for _, s in scored[: max(1, round(self.top * len(scored)))]][:HOLD]
        # Fixed 1/HOLD weights, the best reactions first (research 113).
        return dict.fromkeys(keep, 1.0 / HOLD)


STRATEGIES = (
    PaperStrategy(
        "india_announcement_drift",
        "Post-earnings drift by announcement return (India)",
        "chan-jegadeesh-lakonishok-1996-announcement-drift",
        "Chan, Jegadeesh & Lakonishok (1996), JF 51(5); Indian drift 2002-2017 (research 113)",
        "Buy the fifth of recent reporters with the best two-day reaction to their results; hold sixty sessions.",
        (
            "Reaction: close before the announcement to close after, less NIFTYBEES. Among "
            "stocks that announced 2-60 sessions ago, hold the top fifth.",
            "EPS surprises are not held; the price reaction stands in for the surprise. Weekly, "
            "up to 30 names. Run 2021-08 to 2024-11.",
        ),
        130,
        lambda: AnnouncementDrift("india_announcement_drift"),
    ),
)
