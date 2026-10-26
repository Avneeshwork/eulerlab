"""Two earnings-event strategies on NSE's dated results announcements.

Research 113, batch 5. Both read `nse_earnings_announcements` (make
nse-earnings-announcements): the first NSE disclosure of each company's
results, with its `knowledge_time`. A decision on day d sees only
announcements known by d's close, so neither strategy can read a date early.

- Earnings announcement premium: Barber, De George, Lehavy & Trueman (2013),
  JFE 108(1), across many countries; Frazzini & Lamont (2007). Stocks earn
  more around scheduled announcements. The next date is predicted as the same
  quarter's date a year earlier, the paper's method.
- Post-earnings drift by announcement return: Chan, Jegadeesh & Lakonishok
  (1996), JF 51(5); Brandt, Kishore, Santa-Clara & Venkatachalam (2008). In
  India, drift in the direction of the surprise over 2002-2017 (research 113).
  EPS surprises are not held here, so the surprise is the stock's two-day
  return around the announcement, net of NIFTYBEES.

The data covers 2021-07 to 2024 and labels July-December 2022 differently
(research 112), so fewer events are seen then. Run on 2021-08..2024-11 only
(`make events-daily`); elsewhere the strategies would hold cash.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Callable, Sequence
from datetime import date, datetime, timedelta
from functools import cache

from eulerlab.backtest.india_papers import INDEX_ETF, PaperStrategy, liquid_universe
from eulerlab.backtest.strategy import MarketView, Strategy
from eulerlab.features.panel import PanelRow

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

    def __init__(self, name: str, *, hold: int = 15, hold_days: int = 60) -> None:
        self.name = name
        self.hold = hold
        self.hold_days = hold_days
        self.rebalance_every = WEEK
        self.lookback = 140
        self.hold_unchanged = True

    def target_weights(self, view: MarketView) -> dict[str, float]:
        from eulerlab.backtest.evidence_daily import clenow_score

        market = view.history.get(INDEX_ETF) or []
        if not market:
            return {}
        scored = []
        for symbol in liquid_universe(view):
            rows = view.history[symbol]
            reaction = recent_reaction(rows, market, symbol, view.as_of, self.hold_days)
            if reaction is None or reaction <= 0:
                continue
            score = clenow_score(rows)
            if score is not None:
                scored.append((score, symbol))
        scored.sort(key=lambda x: (-x[0], x[1]))
        return {s: 1.0 / self.hold for _, s in scored[: self.hold]}


STRATEGIES: tuple[PaperStrategy, ...] = (
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
    PaperStrategy(
        "india_drift_momentum_combo",
        "Earnings drift plus Clenow momentum (India)",
        "chan-jegadeesh-lakonishok-1996-announcement-drift",
        "Chan, Jegadeesh & Lakonishok (1996); Clenow (2015) via skyte/momentum",
        "Weekly, hold the 15 recent reporters with a positive reaction and the steepest, smoothest trend.",
        (
            "Announced 2-60 sessions ago with a positive two-day reaction net of NIFTYBEES, "
            "and in Clenow's filter (above the 100-day average, no 15% day).",
            "Ranked by Clenow's slope x R^2, 15 names at fixed fifteenths. Run 2021-08 to 2024-11.",
        ),
        140,
        lambda: DriftMomentum("india_drift_momentum_combo"),
    ),
)

BUILDERS: dict[str, Callable[[], Strategy]] = {s.id: s.build for s in STRATEGIES}
BY_ID: dict[str, PaperStrategy] = {s.id: s for s in STRATEGIES}
EVENTS_WINDOW = ("2021-08-01", "2024-11-30")
