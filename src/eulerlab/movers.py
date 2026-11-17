"""Stocks likely to make a large move soon, and why (research 182).

Three kinds, each tied to a rule this project has tested:

- **Results due** in the next week (NSE board-meeting intimations), with each
  stock's typical results-day move: the median absolute close-to-close return
  on its past reaction sessions (2021-2024 NSE disclosures, plus any captured
  in the last 90 days). A results day is the largest scheduled move most
  stocks make.
- **Fresh results reactions**: a move of 5% or more on the reaction session.
  The session after it, H-0187 (follow it, intraday) applies; a positive
  reaction 2 to 60 sessions old is the earnings-drift swing setup
  (`india_drift_momentum_combo`, research 113).
- **Breakouts**: a close at a new 52-week high on twice the usual volume today
  (`screen_52w_breakout`).

A list here says where a move is likely or a tested setup has fired, not which
way to trade it, and none of it is advice. The reaction session is the first
session whose close comes after the disclosure: a disclosure before 15:30 on a
session day reacts that day, later ones the next session.
"""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Mapping, Sequence
from datetime import date, datetime, time, timedelta
from statistics import median
from typing import Any

from eulerlab.backtest.strategy import MarketView
from eulerlab.features.panel import PanelRow

BIG = 0.05
DRIFT = (2, 60)
RECENT_DAYS = 90
"""Days of NSE disclosures fetched: enough for the drift rule's 60 sessions."""
DRIFT_HOLD = 15
MIN_EVENTS = 3


def reaction_index(days: Sequence[date], when: datetime) -> int | None:
    """Index into `days` of the session that first prices a disclosure made at `when` (IST)."""
    i = bisect_left(days, when.date())
    if i < len(days) and days[i] == when.date() and when.time() >= time(15, 30):
        i += 1
    return i if 0 < i < len(days) else None


def reactions(rows: Sequence[PanelRow], times: Sequence[datetime]) -> list[tuple[date, float, int]]:
    """(reaction day, close-to-close return, sessions ago) for each disclosure, oldest first."""
    days = [r.day for r in rows]
    out: dict[date, tuple[date, float, int]] = {}
    for when in times:
        i = reaction_index(days, when)
        if i is None or rows[i - 1].close <= 0:
            continue
        r = rows[i].close / rows[i - 1].close - 1.0
        # A split or bonus inside the window shows as a huge move; the view's
        # rows are adjusted, but skip anything implausible rather than report it.
        if abs(r) < 0.5:
            out[days[i]] = (days[i], r, len(days) - 1 - i)
    return [out[d] for d in sorted(out)]


def drift_picks(
    view: MarketView,
    names: Sequence[str],
    times: Mapping[str, Sequence[datetime]],
    *,
    hold: int = DRIFT_HOLD,
) -> list[dict[str, Any]]:
    """`india_drift_momentum_combo` on today's view: recent reporters (2-60 sessions) whose
    two-day reaction beat NIFTYBEES, in Clenow's trend filter, the `hold` best by his score.

    The same reading as `events_daily.recent_reaction`: the reaction session is the first
    on or after the disclosure's effective day (after 15:30 counts from the next day),
    the reaction is its next close over the close before it, less NIFTYBEES."""
    from eulerlab.strategies.daily.evidence import clenow_score
    from eulerlab.strategies.daily.india_papers import INDEX_ETF

    market = view.history.get(INDEX_ETF) or []
    mdays = [r.day for r in market]
    scored: list[tuple[float, str, float, int]] = []
    for s in names:
        rows = view.history.get(s) or []
        days = [r.day for r in rows]
        found = None
        for when in sorted(times.get(s, ()), reverse=True):
            eff = when.date() if when.time() < time(15, 30) else when.date() + timedelta(days=1)
            i = bisect_left(days, eff)
            if i >= len(rows) or i < 1:
                continue
            after = len(rows) - 1 - i
            if after > DRIFT[1]:
                break
            if after < DRIFT[0]:
                continue
            m = bisect_left(mdays, rows[i - 1].day)
            n = bisect_left(mdays, rows[i + 1].day)
            if m >= len(market) or n >= len(market) or market[m].close <= 0:
                continue
            reaction = rows[i + 1].close / rows[i - 1].close - market[n].close / market[m].close
            found = (reaction, after)
            break
        if found is None or found[0] <= 0:
            continue
        score = clenow_score(rows)
        if score is not None:
            scored.append((score, s, found[0], found[1]))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [
        {"symbol": s, "trend_score": round(sc, 3), "reaction": round(r, 4), "sessions_ago": ago}
        for sc, s, r, ago in scored[:hold]
    ]


def breakout_today(rows: Sequence[PanelRow], year: int = 252) -> bool:
    if len(rows) < year:
        return False
    prior = max(r.close for r in rows[-year:-1])
    vols = sorted(r.volume for r in rows[-51:-1])
    usual = vols[len(vols) // 2]
    return rows[-1].close >= prior and usual > 0 and rows[-1].volume >= 2 * usual


def _recent_times(today: date) -> dict[str, list[datetime]]:
    """Disclosures of the last 90 days from NSE (landed once each day); empty offline."""
    try:
        from eulerlab.deploy.daily_books import results_times

        return results_times(since=today - timedelta(days=RECENT_DAYS), through=today)
    except Exception:  # offline or NSE refused: the page says what is missing
        return {}


def _past_times() -> dict[str, tuple[datetime, ...]]:
    try:
        from eulerlab.strategies.daily.events import announcements

        return announcements()
    except (OSError, ValueError):
        return {}


def build(
    view: MarketView,
    names: Sequence[str],
    table: Mapping[str, Mapping[str, Any]],
    *,
    upcoming: Sequence[Mapping[str, Any]] | None = None,
    recent: Mapping[str, Sequence[datetime]] | None = None,
    past: Mapping[str, Sequence[datetime]] | None = None,
) -> dict[str, Any]:
    """The three lists for the liquid stocks in `names` on `view.as_of`."""
    today = view.as_of
    if upcoming is None:
        from eulerlab.ingest import board_meetings

        try:
            upcoming = board_meetings.upcoming(today, days=7)
        except (OSError, ValueError):
            upcoming = []
    recent = _recent_times(today) if recent is None else recent
    past = _past_times() if past is None else past
    gaps: list[str] = []
    if not recent:
        gaps.append("results disclosed in the last 90 days were not reached (NSE offline?)")

    wanted = set(names)
    typical: dict[str, dict[str, Any]] = {}
    fresh: list[dict[str, Any]] = []
    for s in names:
        rows = view.history.get(s) or []
        if len(rows) < 2:
            continue
        times = sorted({*past.get(s, ()), *recent.get(s, ())})
        got = reactions(rows, times)
        moves = [abs(r) for _, r, _ in got]
        if len(moves) >= MIN_EVENTS:
            typical[s] = {"median_move": round(median(moves), 4), "events": len(moves)}
        for day, r, ago in got:
            if ago > DRIFT[1] or abs(r) < BIG:
                continue
            setups = []
            if ago == 0:
                setups.append("H-0187: follow it next session, intraday")
            if r > 0 and DRIFT[0] <= ago:
                setups.append("earnings drift (swing)")
            if setups:
                fresh.append(
                    {
                        "symbol": s,
                        "reaction_day": day.isoformat(),
                        "move": round(r, 4),
                        "sessions_ago": ago,
                        "setups": setups,
                        **_place(table, s),
                    }
                )

    due = []
    for row in upcoming:
        s = str(row.get("symbol") or "")
        if s in wanted:
            due.append(
                {
                    "symbol": s,
                    "meeting": str(row.get("meeting")),
                    "typical_move": (typical.get(s) or {}).get("median_move"),
                    "events": (typical.get(s) or {}).get("events", 0),
                    **_place(table, s),
                }
            )
    due.sort(key=lambda x: (x["meeting"], -(x["typical_move"] or 0), x["symbol"]))
    fresh.sort(key=lambda x: (x["sessions_ago"], -abs(x["move"]), x["symbol"]))
    combined = {s: sorted({*past.get(s, ()), *recent.get(s, ())}) for s in names}
    drift = [d | _place(table, d["symbol"]) for d in drift_picks(view, names, combined)]
    breakouts = [
        {"symbol": s, **_place(table, s)}
        for s in names
        if breakout_today(view.history.get(s) or []) and (view.history[s][-1].day == today)
    ]
    return {
        "as_of": today.isoformat(),
        "results_due": due,
        "fresh_reactions": fresh,
        "drift": drift,
        "breakouts": sorted(breakouts, key=lambda x: (not x.get("top_sector"), x["symbol"])),
        "gaps": gaps,
        "evidence": {
            "results_due": "Typical move: median absolute close-to-close return on the stock's past "
            "results reaction sessions (3 or more), NSE disclosures 2021-2024 and the last 90 days.",
            "H-0187": "Follow a 5% results reaction the next session, open to close: +67 bps a trade "
            "after costs, 935 trades 2021-2024, every year positive; about 1.8x overstated from the "
            "official open (research 178, 180). PROMOTE; paper book built, not started.",
            "drift": "Recent reporters with a positive reaction in a smooth trend, weekly, 15 names: "
            "Sharpe 1.55, +197% 2021-08 to 2024-11 against the Nifty ETF's +58%, drawdown -26% "
            "(india_drift_momentum_combo, screening run, research 113).",
            "breakouts": "52-week high on 2x volume, held 20 sessions: Sharpe 0.84, +378% 2016-2026, "
            "drawdown -39% (screen_52w_breakout, screening run, research 150).",
        },
    }


def _place(table: Mapping[str, Mapping[str, Any]], s: str) -> dict[str, Any]:
    row = table.get(s) or {}
    return {
        "sector": row.get("sector"),
        "top_sector": bool(row.get("top_sector")),
        "change_1m": row.get("change_1m"),
    }
