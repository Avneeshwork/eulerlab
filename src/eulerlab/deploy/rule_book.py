"""Paper books for the gated intraday rules: H-0052, H-0065, H-0096, H-0098 (ADR-142).

These four hypotheses passed the gate (PROMOTE or PAPER, research 164-165) but
are not daily rank-and-hold cards, so `forward.build` cannot trade them. Each
gets a trade generator here that re-applies the rule the gate judged to minute
bars after the holdout end (`mandate.yaml` `forward_evidence.holdout_end`),
and `study_book.run` does the rest unchanged: each trade's two legs through
the deployment's OMS (shorts sell first), the kill switch, recovery, the halt
when a past day's history changes, the equity curve and the state file.

- **H-0096** short each stock on its first F&O ban day, 09:20 to 15:10.
- **H-0098** the same stocks, short at the 09:15 opening-auction print, cover
  at 15:10 (the stocks' minute data ends at 15:14, so 15:15 does not exist). Its backtest covered at the closing auction, which an intraday
  (MIS) short cannot reach: the broker squares off about 15:20, and an
  overnight cash short is not allowed. So this paper book is a variant of
  the gated rule, and says so in its state.
- **H-0065** at 09:20, short the top decile of the 20-session mean overnight
  move (09:19 close over the previous session's last close), buy the bottom
  decile; out at 15:10. Needs 100 ranked names and 20 sessions after the
  holdout end, so it trades nothing for its first 21 sessions.
- **H-0052** buy NIFTYBEES 09:20 to 15:10 on a session whose next weekday is an
  NSE holiday (`ingest/holidays`, NSE's current-year list).

Sizing: H-0096 and H-0098 split the capital into ten slots, as backtested
(₹1 lakh each on ₹10 lakh); H-0065 spreads it evenly over that day's
positions; H-0052 puts all of it in NIFTYBEES. Only minute files that start
after the holdout end are opened (`research_screen.load_days(since=...)`).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from datetime import date, timedelta
from itertools import pairwise
from pathlib import Path
from typing import Any

from eulerlab.deploy.deployments import Deployment

SLOTS = 10
"""Positions a day for the ban rules: the backtest's ten ₹1 lakh slots."""
ENTRY, EXIT = 5, 355
"""09:20 and 15:10, as minutes after 09:15."""
LOOKBACK = 20
MIN_NAMES = 100
MIN_PRICE = 10.0
ETF = "NIFTYBEES"
REPORTS = Path("data/landing/nse_reports/manifest.jsonl")

Trade = dict[str, Any]
Generator = Callable[..., tuple[list[Trade], list[date]]]


def _trade(
    day: date, symbol: str, direction: int, quantity: int, entry: float, exit_: float, minute: int
) -> Trade:
    return {
        "day": day,
        "symbol": symbol,
        "direction": direction,
        "quantity": quantity,
        "entry": entry,
        "exit": exit_,
        "minute": minute,
    }


def _days(symbol: str, *, since: date, through: date) -> list[Any]:
    from eulerlab.intraday import research_screen as rs

    return rs.load_days(symbol, cutoff=through, cache=False, since=since)


def _fills(day: Any, entry_minute: int, exit_minute: int) -> tuple[float, float] | None:
    entry, leave = day.fill_at(entry_minute), day.fill_at(exit_minute)
    if entry is None or leave is None or entry[0] >= leave[0]:
        return None
    return entry[1], leave[1]


# --- the F&O ban list ------------------------------------------------------------


def ban_lists(*, since: date, through: date, path: Path = REPORTS) -> dict[date, set[str]]:
    """Each trade date's ban list from the nightly NSE report download. The list
    for the session before `since` is read too, so the first day's entries are
    known; a ban list is a report, not price data."""
    from eulerlab.ingest import landing_reader
    from eulerlab.intraday import nse_reports_screen as rep

    out: dict[date, set[str]] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        entry = json.loads(line)
        if entry.get("segment") != "fo_ban":
            continue
        day = date.fromisoformat(entry["trade_date"])
        if since - timedelta(days=10) <= day <= through:
            text = landing_reader.read(f"nse_reports/{entry['path']}").decode(
                "utf-8-sig", errors="replace"
            )
            out[day] = rep.ban_list(text)
    return out


def first_ban_days(lists: dict[date, set[str]], *, after: date) -> dict[date, list[str]]:
    """{trade date: stocks new to the ban that day}, for dates after `after`."""
    days = sorted(lists)
    out: dict[date, list[str]] = {}
    for before, today in pairwise(days):
        if today > after:
            out[today] = sorted(lists[today] - lists[before])
    return out


def ban_trades(
    entries: dict[date, list[str]],
    load: Callable[[str], list[Any]],
    capital: float,
    *,
    auction: bool,
) -> tuple[list[Trade], list[date]]:
    """Shorts on first ban days: 09:20-15:10, or the auction variant 09:15-15:10."""
    slot = capital / SLOTS
    by_symbol: dict[str, list[date]] = {}
    for day, names in entries.items():
        for name in names:
            by_symbol.setdefault(name, []).append(day)
    chosen: dict[date, list[Trade]] = {}
    sessions: set[date] = set()
    for symbol, wanted in by_symbol.items():
        days = {d.day: d for d in load(symbol)}
        sessions.update(days)
        for day in wanted:
            bars = days.get(day)
            if bars is None:
                continue
            if auction:
                opened = bars.open_[0]
                leave = bars.fill_at(EXIT)
                prices = (opened, leave[1]) if opened is not None and leave is not None else None
                minute = 0
            else:
                prices, minute = _fills(bars, ENTRY, EXIT), ENTRY
            if prices is None or prices[0] < MIN_PRICE:
                continue
            quantity = int(slot / prices[0])
            if quantity:
                trade = _trade(day, symbol, -1, quantity, prices[0], prices[1], minute)
                chosen.setdefault(day, []).append(trade)
    trades = [
        t for day in sorted(chosen) for t in sorted(chosen[day], key=lambda t: t["symbol"])[:SLOTS]
    ]
    return trades, sorted(sessions)


def h0096(
    *, start: date, through: date, since: date, capital: float
) -> tuple[list[Trade], list[date]]:
    entries = first_ban_days(ban_lists(since=since, through=through), after=since)
    return ban_trades(
        {d: n for d, n in entries.items() if d >= start},
        lambda s: _days(s, since=since, through=through),
        capital,
        auction=False,
    )


def h0098(
    *, start: date, through: date, since: date, capital: float
) -> tuple[list[Trade], list[date]]:
    entries = first_ban_days(ban_lists(since=since, through=through), after=since)
    return ban_trades(
        {d: n for d, n in entries.items() if d >= start},
        lambda s: _days(s, since=since, through=through),
        capital,
        auction=True,
    )


# --- H-0065 overnight winners reverse by day ----------------------------------------


def overnight_trades(
    days_by_symbol: dict[str, list[Any]], *, start: date, capital: float
) -> tuple[list[Trade], list[date]]:
    """Rank on the mean of the previous 20 overnight moves; short the top decile, buy the bottom."""
    from eulerlab.intraday import overnight_reversal_screen as overnight

    sessions: set[date] = set()
    marks: dict[str, dict[date, Any]] = {}
    for symbol, days in days_by_symbol.items():
        sessions.update(d.day for d in days)
        marks[symbol] = overnight.extract(symbol, days)
    return overnight_trades_from_marks(marks, start=start, capital=capital), sorted(sessions)


def overnight_trades_from_marks(
    marks_by_symbol: dict[str, dict[date, Any]], *, start: date, capital: float
) -> list[Trade]:
    """H-0065's trades from each stock's overnight marks (`overnight_reversal_screen.extract`)."""
    ranked: dict[date, list[tuple[float, str, Any]]] = {}
    for symbol, marks in marks_by_symbol.items():
        ordered = sorted(marks)
        for i in range(LOOKBACK, len(ordered)):
            day = ordered[i]
            if day < start:
                continue
            mean = sum(marks[d].overnight for d in ordered[i - LOOKBACK : i]) / LOOKBACK
            ranked.setdefault(day, []).append((mean, symbol, marks[day]))
    trades: list[Trade] = []
    for day in sorted(ranked):
        names = ranked[day]
        if len(names) < MIN_NAMES:
            continue
        names.sort(key=lambda item: (item[0], item[1]))
        decile = len(names) // 10
        each = capital / (2 * decile)
        for direction, chosen in ((-1, names[-decile:]), (1, names[:decile])):
            for _, symbol, mark in chosen:
                quantity = int(each / mark.entry)
                if quantity:
                    trades.append(
                        _trade(day, symbol, direction, quantity, mark.entry, mark.exit, ENTRY)
                    )
    return trades


def h0065(
    *, start: date, through: date, since: date, capital: float
) -> tuple[list[Trade], list[date]]:
    from eulerlab.intraday import cross_section as cs

    loaded = {s: _days(s, since=since, through=through) for s in cs.universe()}
    return overnight_trades(loaded, start=start, capital=capital)


# --- H-0052 NIFTYBEES before a holiday ------------------------------------------------


def pre_holiday(day: date, holidays: frozenset[date]) -> bool:
    """A session whose next weekday is an NSE holiday."""
    nxt = day + timedelta(days=1)
    while nxt.weekday() >= 5:
        nxt += timedelta(days=1)
    return nxt in holidays


def holiday_trades(
    days: Sequence[Any], holidays: frozenset[date], *, start: date, capital: float
) -> tuple[list[Trade], list[date]]:
    trades: list[Trade] = []
    for bars in days:
        if bars.day < start or not pre_holiday(bars.day, holidays):
            continue
        prices = _fills(bars, ENTRY, EXIT)
        if prices is not None and (quantity := int(capital / prices[0])):
            trades.append(_trade(bars.day, ETF, 1, quantity, prices[0], prices[1], ENTRY))
    return trades, sorted(d.day for d in days)


def h0052(
    *, start: date, through: date, since: date, capital: float
) -> tuple[list[Trade], list[date]]:
    from eulerlab.ingest import holidays

    known = holidays.load_holidays(holidays.REFERENCE)
    if not known:
        msg = "no NSE holiday list cached; run `make holidays`"
        raise ValueError(msg)
    return holiday_trades(
        _days(ETF, since=since, through=through), known, start=start, capital=capital
    )


# --- the book ---------------------------------------------------------------------------

RULES: dict[str, Generator] = {"H-0052": h0052, "H-0065": h0065, "H-0096": h0096, "H-0098": h0098}

VARIANT = {
    "H-0098": "variant: covers at 15:10, not the closing auction its backtest used "
    "(an intraday short cannot be held to the close)"
}


def is_rule(strategy_id: str) -> bool:
    return strategy_id in RULES


def blocker(strategy_id: str) -> str:
    """Why this rule cannot paper-trade now, or ""."""
    from eulerlab import forward
    from eulerlab.deploy import intraday_book

    if not is_rule(strategy_id):
        return f"{strategy_id} is not an intraday rule this book trades"
    gate = forward.verdicts()
    verdict = gate.get(strategy_id, ("", None))[0].upper()
    if not verdict.startswith(("PROMOTE", "PAPER")):
        return (
            f"the gate's verdict on {strategy_id} is {verdict or 'missing'}; "
            "paper trading needs PROMOTE or PAPER"
        )
    if intraday_book.holdout_end() is None:
        return "paper trading needs `forward_evidence: holdout_end` in mandate.yaml"
    return ""


def trades_for(
    strategy_id: str, *, start: date, through: date, since: date, capital: float
) -> tuple[list[Trade], list[date]]:
    return RULES[strategy_id](start=start, through=through, since=since, capital=capital)


def run(deployment: Deployment) -> dict[str, Any]:
    """Bring one rule deployment up to yesterday's minute bars, through `study_book.run`."""
    from eulerlab.deploy import deployments as store
    from eulerlab.deploy import study_book

    state = study_book.run(deployment, trades_for=trades_for, block=blocker)
    if note := VARIANT.get(deployment.strategy_id):
        state.setdefault("warnings", []).append(note)
        store.write_state(deployment, state)
    return state
