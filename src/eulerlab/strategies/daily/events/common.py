"""Shared pieces of the events strategies: helpers used by more than one, and the types they share."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from functools import cache

from eulerlab.backtest.strategy import MarketView, Strategy
from eulerlab.features.panel import PanelRow
from eulerlab.strategies.daily.india_papers import INDEX_ETF, liquid_universe

HOLD = 30
WEEK = 5


@cache
def announcements() -> dict[str, tuple[datetime, ...]]:
    """Symbol to the times each results announcement became known, oldest first."""
    from eulerlab.ingest import nse_earnings_announcements as source

    out: dict[str, list[datetime]] = {}
    for row in source.load():
        stamp = row.get("knowledge_time") or row.get("event_time")
        symbol = row.get("symbol")
        if stamp and symbol:
            out.setdefault(str(symbol), []).append(datetime.fromisoformat(str(stamp)))
    return {s: tuple(sorted(set(v))) for s, v in out.items()}


def known_by(symbol: str, day: date) -> list[date]:
    """Announcement days of `symbol` known by `day`'s close (15:30 IST), as trading
    days: one disclosed after the close counts from the next day."""
    found = []
    for stamp in announcements().get(symbol, ()):
        effective = (
            stamp.date()
            if (stamp.hour, stamp.minute) < (15, 30)
            else stamp.date() + timedelta(days=1)
        )
        if effective <= day:
            found.append(effective)
    return sorted(set(found))


def _index_at(rows: Sequence[PanelRow], day: date) -> int:
    """The first row on or after `day`."""
    return bisect_left([r.day for r in rows], day)


def recent_reaction(
    rows: Sequence[PanelRow], market: Sequence[PanelRow], symbol: str, day: date, hold_days: int
) -> float | None:
    """The newest announcement 2..`hold_days` sessions ago: its two-day return less NIFTYBEES."""
    days = [r.day for r in market]
    for announced in reversed(known_by(symbol, day)):
        i = _index_at(rows, announced)
        if i >= len(rows) or i < 1:
            continue
        after = len(rows) - 1 - i
        if after > hold_days:
            return None
        if after < 2:
            continue
        m = _index_at(market, rows[i - 1].day)
        n = bisect_right(days, rows[i + 1].day) - 1
        if m >= len(market) or n < m or market[m].close <= 0 or rows[i - 1].close <= 0:
            continue
        return (rows[i + 1].close / rows[i - 1].close) - (market[n].close / market[m].close)
    return None


class DriftMomentum(Strategy):
    """Recent reporters with a positive reaction that are also in Clenow's trend
    filter, the `hold` best by Clenow's score. Weekly, fixed weights.

    Combines the two edges that held up best in research 113: post-earnings
    drift and smooth-trend momentum. Declared before it was run (2026-10-18).
    """

    def __init__(
        self, name: str, *, hold: int = 15, hold_days: int = 60, topdown: bool = False
    ) -> None:
        self.name = name
        self.hold = hold
        self.hold_days = hold_days
        self.topdown = topdown
        """Research 182: only stocks in the top 5 sectors (`backtest.topdown`)."""
        self.rebalance_every = WEEK
        self.lookback = 140
        self.hold_unchanged = True

    def target_weights(self, view: MarketView) -> dict[str, float]:
        from eulerlab.backtest import topdown
        from eulerlab.strategies.daily.evidence import clenow_score

        market = view.history.get(INDEX_ETF) or []
        if not market:
            return {}
        names = liquid_universe(view)
        if self.topdown:
            ranking = topdown.rank(view, names)
            names = [s for s in names if ranking.in_top_sectors(s)]
        scored = []
        for symbol in names:
            rows = view.history[symbol]
            reaction = recent_reaction(rows, market, symbol, view.as_of, self.hold_days)
            if reaction is None or reaction <= 0:
                continue
            score = clenow_score(rows)
            if score is not None:
                scored.append((score, symbol))
        scored.sort(key=lambda x: (-x[0], x[1]))
        return {s: 1.0 / self.hold for _, s in scored[: self.hold]}


EVENTS_WINDOW = ("2021-08-01", "2024-11-30")
