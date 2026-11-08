"""Paper books for H-0168 (results-morning gap fade) and H-0162 (promoter buys, 20 days) (ADR-149).

Both were gated on daily bars of the 500 most traded NSE stocks (research 173,
176). Each generator re-applies the gated rule to daily data after the holdout
end and returns `rule_book`'s trade shape for `study_book.run`.

- **H-0168**: results disclosed after the previous 15:30 and before 09:15
  (NSE's corporate-announcement API, landed one finished day at a time,
  dated by when NSE disseminated it); a gap of 3% or more at the official
  open is traded against, open to close; at most ten a day, a tenth of the
  capital each. A short is skipped on a stock on the previous evening's
  ASM/GSM or trade-for-trade list, and no day is traded without a list
  snapshot (as H-0161, ADR-148).
- **H-0162**: a SAST promoter acquisition; buy at the next session's open,
  sell at the close twenty sessions later; delivery (CNC) charges. A position
  is booked on its exit day, so the book shows it once it has closed, with
  both fills; until then it is not in the equity curve.

Only data after the holdout end is read, so the liquidity ranking needs 20
sessions after it.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date, datetime, time, timedelta
from typing import Any

from eulerlab.intraday import cross_section as cs
from eulerlab.intraday import daily_universe_screen as du

SLOTS = 10
HOLD = 20
Trade = dict[str, Any]


# --- results disclosures, one finished day at a time ------------------------------------


def results_times(*, since: date, through: date) -> dict[str, list[datetime]]:
    """{symbol: dissemination times of financial results} from `since` to `through`."""
    from eulerlab.ingest import nse_earnings_announcements as ann

    paths = []
    day = since
    while day <= through:
        if day.weekday() < 5:
            paths += ann.land(day, day)
        day += timedelta(days=1)
    rows, _ = ann.derive(paths)
    out: dict[str, list[datetime]] = defaultdict(list)
    for row in rows:
        out[row["symbol"]].append(datetime.fromisoformat(row["knowledge_time"]))
    return {s: sorted(v) for s, v in out.items()}


def results_mornings(
    sessions: Sequence[date], results: Mapping[str, Sequence[datetime]]
) -> list[tuple[date, str]]:
    """(session, symbol) with results disclosed after the previous 15:30 and before 09:15."""
    import bisect

    out = set()
    for symbol, times in results.items():
        for when in times:
            i = bisect.bisect_left(sessions, when.date())
            if i < len(sessions) and sessions[i] == when.date():
                if time(9, 15) <= when.time() < time(15, 30):
                    continue
                if when.time() >= time(15, 30):
                    i += 1
            if i < len(sessions):
                out.add((sessions[i], symbol))
    return sorted(out)


# --- H-0168 ----------------------------------------------------------------------------


def gap_fade_trades(
    panel: Mapping[str, Mapping[date, du.Bar]],
    mornings: Sequence[tuple[date, str]],
    t2t: Mapping[date, frozenset[str]],
    surveillance: Mapping[date, frozenset[str]],
    *,
    start: date,
    capital: float,
) -> tuple[list[Trade], list[date]]:
    from eulerlab.deploy import delivery_fade_book as fade
    from eulerlab.deploy import rule_book

    sessions = sorted({d for bars in panel.values() for d in bars})
    index = {d: i for i, d in enumerate(sessions)}
    liquid = du.liquid_sets(panel, sessions)
    by_day: dict[date, list[tuple[float, str, Trade]]] = defaultdict(list)
    for day, symbol in mornings:
        i = index.get(day)
        if day < start or i is None or i == 0 or symbol not in liquid.get(day, frozenset()):
            continue
        p = sessions[i - 1]
        bars = panel[symbol]
        if day not in bars or p not in bars or p not in t2t or symbol in t2t[p]:
            continue
        watched = fade.latest_on_or_before(surveillance, p)
        if watched is None:
            continue
        gap = bars[day].open / bars[p].close - 1.0
        if abs(gap) < 0.03 or not du.SPLIT_LOW <= 1 + gap <= du.SPLIT_HIGH:
            continue
        side = -1 if gap > 0 else 1
        if side < 0 and symbol in watched:
            continue
        bar = bars[day]
        quantity = int(capital / SLOTS / bar.open) if bar.open >= cs.MIN_PRICE else 0
        if quantity:
            trade = rule_book._trade(day, symbol, side, quantity, bar.open, bar.close, 0)
            by_day[day].append((-abs(gap), symbol, trade))
    out: list[Trade] = []
    for day in sorted(by_day):
        out.extend(t for _, _, t in sorted(by_day[day], key=lambda x: (x[0], x[1]))[:SLOTS])
    return out, [d for d in sessions if d >= start]


def h0168(
    *, start: date, through: date, since: date, capital: float
) -> tuple[list[Trade], list[date]]:
    from eulerlab.deploy import delivery_fade_book as fade
    from eulerlab.ingest import trade_for_trade

    trade_for_trade.build()
    panel = du.load_panel(start=since + timedelta(days=1), end=through)
    sessions = sorted({d for bars in panel.values() for d in bars})
    mornings = results_mornings(sessions, results_times(since=since, through=through))
    return gap_fade_trades(
        panel,
        mornings,
        trade_for_trade.load(),
        fade.surveillance_lists(),
        start=start,
        capital=capital,
    )


# --- H-0162 ----------------------------------------------------------------------------


def promoter_trades(
    panel: Mapping[str, Mapping[date, du.Bar]],
    promoters: Mapping[str, Mapping[date, float]],
    *,
    start: date,
    through: date,
    capital: float,
) -> tuple[list[Trade], list[date]]:
    """Closed 20-session positions, each booked on its exit day with both prices."""
    from eulerlab.deploy import rule_book

    sessions = sorted({d for bars in panel.values() for d in bars})
    index = {d: i for i, d in enumerate(sessions)}
    liquid = du.liquid_sets(panel, sessions)
    found = []
    for symbol, days in promoters.items():
        bars = panel.get(symbol)
        if not bars:
            continue
        for day, share in days.items():
            i = index.get(day)
            if day < start or i is None or symbol not in liquid.get(day, frozenset()):
                continue
            if i + HOLD >= len(sessions) or sessions[i + HOLD] > through:
                continue  # still open: booked when it closes
            window = sessions[i : i + HOLD + 1]
            if any(d not in bars for d in window) or not du._clean(bars, window):
                continue
            found.append((day, -share, symbol, window[-1]))
    found.sort()
    out: list[Trade] = []
    open_: list[tuple[str, date]] = []
    slot = capital / SLOTS
    for day, _, symbol, exit_day in found:
        open_ = [(s, x) for s, x in open_ if x >= day]
        if len(open_) >= SLOTS or any(s == symbol for s, _ in open_):
            continue
        bar = panel[symbol][day]
        quantity = int(slot / bar.open) if bar.open >= cs.MIN_PRICE else 0
        if not quantity:
            continue
        open_.append((symbol, exit_day))
        trade = rule_book._trade(
            exit_day, symbol, 1, quantity, bar.open, panel[symbol][exit_day].close, 0
        )
        trade["segment"] = "delivery"
        trade["entry_day"] = day
        out.append(trade)
    return out, [d for d in sessions if d >= start]


def h0162(
    *, start: date, through: date, since: date, capital: float
) -> tuple[list[Trade], list[date]]:
    from eulerlab.intraday import nse_reports_screen as rep

    panel = du.load_panel(start=since + timedelta(days=1), end=through)
    sessions = sorted({d for bars in panel.values() for d in bars})
    sast = [x for _, found in rep._parsed("sast", rep.promoter_buys, since, through) for x in found]
    promoters = rep.promoter_events(sast, sessions)
    return promoter_trades(panel, promoters, start=start, through=through, capital=capital)


def as_json(trades: Sequence[Trade]) -> str:
    """For a quick look: the trades with dates as text."""
    return json.dumps(
        [{k: str(v) if isinstance(v, date) else v for k, v in t.items()} for t in trades]
    )


# --- H-0187 (research 178) ---------------------------------------------------------------


def results_follow_trades(
    panel: Mapping[str, Mapping[date, du.Bar]],
    mornings: Sequence[tuple[date, str]],
    t2t: Mapping[date, frozenset[str]],
    surveillance: Mapping[date, frozenset[str]],
    *,
    start: date,
    capital: float,
    move: float = 0.05,
) -> tuple[list[Trade], list[date]]:
    """H-0187: the session after a 5% results reaction, with it, open to close."""
    from eulerlab.deploy import delivery_fade_book as fade
    from eulerlab.deploy import rule_book

    sessions = sorted({d for bars in panel.values() for d in bars})
    index = {d: i for i, d in enumerate(sessions)}
    liquid = du.liquid_sets(panel, sessions)
    by_day: dict[date, list[tuple[float, str, Trade]]] = defaultdict(list)
    for reaction, symbol in mornings:
        i = index.get(reaction)
        if i is None or i == 0 or i + 1 >= len(sessions):
            continue
        day, before = sessions[i + 1], sessions[i - 1]
        bars = panel[symbol]
        if day < start or symbol not in liquid.get(day, frozenset()):
            continue
        if any(d not in bars for d in (before, reaction, day)) or reaction not in t2t:
            continue
        if symbol in t2t[reaction]:
            continue
        r = bars[reaction].close / bars[before].close - 1.0
        if abs(r) < move or not du.SPLIT_LOW <= 1 + r <= du.SPLIT_HIGH:
            continue
        side = 1 if r > 0 else -1
        watched = fade.latest_on_or_before(surveillance, reaction)
        if watched is None or (side < 0 and symbol in watched):
            continue
        bar = bars[day]
        quantity = int(capital / SLOTS / bar.open) if bar.open >= cs.MIN_PRICE else 0
        if quantity:
            trade = rule_book._trade(day, symbol, side, quantity, bar.open, bar.close, 0)
            by_day[day].append((-abs(r), symbol, trade))
    out: list[Trade] = []
    for day in sorted(by_day):
        out.extend(t for _, _, t in sorted(by_day[day], key=lambda x: (x[0], x[1]))[:SLOTS])
    return out, [d for d in sessions if d >= start]


def h0187(
    *, start: date, through: date, since: date, capital: float
) -> tuple[list[Trade], list[date]]:
    from eulerlab.deploy import delivery_fade_book as fade
    from eulerlab.ingest import trade_for_trade

    trade_for_trade.build()
    panel = du.load_panel(start=since + timedelta(days=1), end=through)
    sessions = sorted({d for bars in panel.values() for d in bars})
    mornings = results_mornings(sessions, results_times(since=since, through=through))
    return results_follow_trades(
        panel,
        mornings,
        trade_for_trade.load(),
        fade.surveillance_lists(),
        start=start,
        capital=capital,
    )
