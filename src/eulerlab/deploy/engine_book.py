"""Paper books for engine cards: the gated rule, re-applied after the holdout end (ADR-150).

A card the autopilot (or anyone) wrote as an `engine:` spec and the gate passed
(PROMOTE or PAPER) gets a paper book with no new code: `rule_book` asks here
for its trades, and `study_book.run` does the rest unchanged (OMS legs, kill
switch, halts, the equity curve).

- **Data.** `rule_engine.LiveData`: daily bars, delivery, bulk deals, results
  and promoter disclosures after the holdout end only.
- **Intraday.** Official open to official close, at most ten a day, a tenth of
  the capital each, best rank first. A short is skipped on a stock on the
  previous evening's ASM/GSM or trade-for-trade list, and no day is traded
  without a list snapshot (as H-0161 and H-0168, ADR-148). The backtest
  covered at the official close, which an MIS position cannot reach: a variant,
  and the state says so.
- **Swing.** Delivery, long only, at most ten open, a position booked on its
  exit day with both fills (as H-0162, ADR-149).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from eulerlab.intraday import cross_section as cs
from eulerlab.intraday import daily_universe_screen as du

SLOTS = 10
Trade = dict[str, Any]
VARIANT = (
    "engine card: an intraday rule covers at the official close, which an MIS position cannot "
    "reach; shorts skip the previous evening's ASM, GSM and trade-for-trade lists; a swing "
    "position is booked on its exit day (ADR-150)"
)


def is_engine_card(strategy_id: str) -> bool:
    from eulerlab.intraday import rule_engine

    try:
        return rule_engine.card_spec(strategy_id) is not None
    except ValueError:
        return False


def trades(
    strategy_id: str, *, start: date, through: date, since: date, capital: float
) -> tuple[list[Trade], list[date]]:
    from eulerlab.deploy import delivery_fade_book as fade
    from eulerlab.deploy import rule_book
    from eulerlab.intraday import rule_engine

    spec = rule_engine.card_spec(strategy_id)
    if spec is None:
        msg = f"{strategy_id} has no engine block"
        raise KeyError(msg)
    data = rule_engine.LiveData(since=since, through=through)
    engine = rule_engine.Engine(data)
    sessions = [d for d in data.sessions if d >= start]
    slot = capital / SLOTS
    out: list[Trade] = []
    if spec.kind == "swing":
        for s in engine.swings(spec):
            if s.entry_day < start:
                continue
            quantity = int(slot / s.entry) if s.entry >= cs.MIN_PRICE else 0
            if not quantity:
                continue
            trade = rule_book._trade(s.exit_day, s.symbol, 1, quantity, s.entry, s.exit, 0)
            trade["segment"] = "delivery"
            trade["entry_day"] = s.entry_day
            out.append(trade)
        return out, sessions
    lists = fade.surveillance_lists()
    by_day: dict[date, list[tuple[float, str, Trade]]] = defaultdict(list)
    for day, symbol, side, rank in engine.events(spec):
        p = data.prev(day)
        if day < start or p is None:
            continue
        # a snapshot landed any time before the trade day's open counts (HISTORY #86)
        watched = fade.latest_on_or_before(lists, day - timedelta(days=1))
        if watched is None or p not in data.t2t:
            continue  # no list snapshot for that evening: not traded
        if side < 0 and symbol in watched:
            continue
        bar = data.panel[symbol][day]
        if not du.SPLIT_LOW <= bar.close / bar.open <= du.SPLIT_HIGH:
            continue
        quantity = int(slot / bar.open) if bar.open >= cs.MIN_PRICE else 0
        if quantity:
            by_day[day].append(
                (
                    rank,
                    symbol,
                    rule_book._trade(day, symbol, side, quantity, bar.open, bar.close, 0),
                )
            )
    for day in sorted(by_day):
        out.extend(t for _, _, t in sorted(by_day[day], key=lambda x: (x[0], x[1]))[:SLOTS])
    return out, sessions
