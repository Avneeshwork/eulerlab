"""Paper book for H-0161, the low-delivery rally fade on every liquid NSE stock (ADR-148).

The rule research 173 gated: yesterday a stock rose at least 3% on at most
half its usual delivery %; short it at today's official open, cover at the
official close; the 500 most traded NSE stocks by 20-session traded value; at
most ten a day, lowest delivery ratio first; a tenth of the capital each.

Before a stock is shorted, research 174's checks, all read as of the previous
evening so nothing from the trade day is used:

- **trade-for-trade**: not in series BE or BZ in the previous session's cash
  bhavcopy (`ingest/trade_for_trade`);
- **surveillance**: not on NSE's ASM or GSM list in the latest snapshot landed
  on or before the previous session (`nse_reports` `asm`, `gsm`). A day with
  no snapshot on or before it is not traded: the lists began landing on
  2026-11-07, and NSE publishes no history of them.

Only daily data after the holdout end is read (`since`), so the ranking and
the delivery ratio need 20 sessions after it; the book trades nothing before.
The official close stands in for a cover at about 15:15: an MIS short is
squared off by the broker from 15:12 and cannot reach the closing auction,
so this book is a variant of the gated rule and says so in its state.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any

from eulerlab.intraday import cross_section as cs
from eulerlab.intraday import daily_universe_screen as du

REPORTS = Path("data/landing/nse_reports/manifest.jsonl")
SLOTS = 10
VARIANT = (
    "variant: covers at the official close, which an MIS short cannot reach "
    "(the broker squares off from 15:12); shorts only stocks off the ASM, GSM "
    "and trade-for-trade lists of the previous evening"
)

Trade = dict[str, Any]


def surveillance_lists(path: Path = REPORTS) -> dict[date, frozenset[str]]:
    """{snapshot day: symbols on the ASM or GSM list that evening}."""
    from eulerlab.ingest import landing_reader

    out: dict[date, set[str]] = defaultdict(set)
    if not path.exists():
        return {}
    for line in path.read_text(encoding="utf-8").splitlines():
        entry = json.loads(line)
        if entry.get("segment") not in ("asm", "gsm"):
            continue
        day = date.fromisoformat(entry["trade_date"])
        body = json.loads(landing_reader.read(f"nse_reports/{entry['path']}"))
        out[day] |= symbols_on_lists(body)
    return {d: frozenset(v) for d, v in out.items()}


def symbols_on_lists(body: Any) -> set[str]:
    """Symbols in an ASM payload ({"longterm": {"data": []}, ...}) or a GSM list."""
    rows: list[Any] = []
    if isinstance(body, dict):
        for key in ("longterm", "shortterm"):
            rows += (body.get(key) or {}).get("data") or []
    elif isinstance(body, list):
        rows = body
    return {str(r.get("symbol")) for r in rows if isinstance(r, dict) and r.get("symbol")}


def latest_on_or_before(lists: Mapping[date, frozenset[str]], day: date) -> frozenset[str] | None:
    found = [d for d in lists if d <= day]
    return lists[max(found)] if found else None


def trades(
    panel: Mapping[str, Mapping[date, du.Bar]],
    delivery: Mapping[str, Mapping[date, float]],
    t2t: Mapping[date, frozenset[str]],
    surveillance: Mapping[date, frozenset[str]],
    *,
    start: date,
    capital: float,
) -> tuple[list[Trade], list[date]]:
    """H-0161's shorts from `start`, with the shortability checks."""
    from eulerlab.deploy import rule_book

    sessions = sorted({d for bars in panel.values() for d in bars})
    liquid = du.liquid_sets(panel, sessions)
    slot = capital / SLOTS
    by_day: dict[date, list[tuple[float, str, Trade]]] = defaultdict(list)
    for i in range(2, len(sessions)):
        day, p, q = sessions[i], sessions[i - 1], sessions[i - 2]
        if day < start:
            continue
        watched = latest_on_or_before(surveillance, p)
        if watched is None or p not in t2t:
            continue
        for symbol in liquid.get(day, frozenset()):
            bars = panel[symbol]
            if day not in bars or p not in bars or q not in bars:
                continue
            if symbol in watched or symbol in t2t[p]:
                continue
            r = bars[p].close / bars[q].close - 1.0
            ratio = delivery.get(symbol, {}).get(p)
            if r < 0.03 or ratio is None or ratio > 0.5 or not du._clean(bars, (q, p, day)):
                continue
            bar = bars[day]
            quantity = int(slot / bar.open) if bar.open >= cs.MIN_PRICE else 0
            if quantity:
                trade = rule_book._trade(day, symbol, -1, quantity, bar.open, bar.close, 0)
                by_day[day].append((ratio, symbol, trade))
    out: list[Trade] = []
    for day in sorted(by_day):
        out.extend(t for _, _, t in sorted(by_day[day], key=lambda x: (x[0], x[1]))[:SLOTS])
    return out, [d for d in sessions if d >= start]


def h0161(
    *, start: date, through: date, since: date, capital: float
) -> tuple[list[Trade], list[date]]:
    from datetime import timedelta

    from eulerlab.ingest import trade_for_trade
    from eulerlab.intraday import other_data_screen as od

    trade_for_trade.build()
    panel = du.load_panel(start=since + timedelta(days=1), end=through)
    delivery = {
        s: {d: r for d, r in days.items() if d <= through}
        for s, days in od.delivery_ratios(since=since).items()
    }
    return trades(
        panel, delivery, trade_for_trade.load(), surveillance_lists(), start=start, capital=capital
    )
