"""Results published during market hours: follow the first five minutes (research 112, H-0022).

Patell and Wolfson (1984) measure how fast prices absorb earnings news; an
Indian event study (Asian Journal of Accounting Research, 2019) finds the
reaction differs for results released during trading hours. Fixed rule: when a
stock's results are first disclosed on NSE between 09:20 and 14:30, measure the
move over the next five minutes from the last close before the disclosure. A
move of at least 1% is followed: enter at the next open, flat at 15:10.

Disclosure time is the first public one: the results row, or a same-day
board-meeting outcome if that came out earlier (`nse_earnings_announcements`).
July to December 2022 is left out: NSE filed results under other labels then.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from eulerlab.ingest import nse_earnings_announcements as announcements
from eulerlab.intraday import cross_section as cs
from eulerlab.intraday import india_papers as ip

RUN_ID = "nse_results_in_hours_follow_five_minutes"
FIRST = 5
"""09:20: a disclosure before it meets the noisy opening minutes."""

LAST = 315
"""14:30: later leaves too little of the session to hold."""

REACTION = 5
THRESHOLD = 0.01
MAX_OPEN = 10
"""At most ten positions a day, ₹1 lakh each: results days crowd."""


def events(rows: Sequence[Mapping[str, Any]]) -> dict[str, dict[date, int]]:
    """{symbol: {day: minute after 09:15 of the first disclosure}}, in-hours only."""
    out: dict[str, dict[date, int]] = defaultdict(dict)
    for row in rows:
        known = datetime.fromisoformat(str(row["knowledge_time"]))
        day = known.date()
        if any(start <= day <= end for start, end in announcements.INCOMPLETE):
            continue
        minute = (known.hour - 9) * 60 + known.minute - 15
        if not FIRST <= minute <= LAST:
            continue
        symbol = str(row["symbol"])
        out[symbol][day] = min(out[symbol].get(day, minute), minute)
    return dict(out)


@dataclass(frozen=True)
class Mark:
    disclosed: int
    reaction: float
    entry_minute: int
    entry: float
    exit_minute: int
    exit: float


def mark(day: ip.Day, disclosed: int) -> Mark | None:
    reference = day.close[disclosed - 1]
    reaction = day.close[disclosed + REACTION - 1] / reference - 1.0
    if abs(reaction) < THRESHOLD:
        return None
    entry = day.fill_at(disclosed + REACTION)
    leave = day.fill_at(cs.EXIT)
    if entry is None or leave is None or entry[0] >= cs.EXIT:
        return None
    return Mark(disclosed, reaction, entry[0], entry[1], leave[0], leave[1])


def extractor(known: Mapping[str, Mapping[date, int]]) -> cs.Extractor:
    def extract(symbol: str, days: Sequence[ip.Day]) -> dict[date, Mark]:
        mine = known.get(symbol, {})
        out = {}
        for day in days:
            disclosed = mine.get(day.day)
            if disclosed is None or day.close[disclosed - 1] < cs.MIN_PRICE:
                continue
            found = mark(day, disclosed)
            if found is not None:
                out[day.day] = found
        return out

    return extract


def evaluate(marks: Mapping[str, Mapping[date, Mark]], sessions: Sequence[date]) -> dict[str, Any]:
    by_day: dict[date, list[tuple[str, Mark]]] = defaultdict(list)
    for symbol, days in marks.items():
        for day, found in days.items():
            by_day[day].append((symbol, found))
    trades = []
    each = cs.CAPITAL / MAX_OPEN
    for day, found_today in by_day.items():
        found_today.sort(key=lambda item: (item[1].entry_minute, item[0]))
        for symbol, found in found_today[:MAX_OPEN]:
            quantity = cs.sized(each, found.entry)
            if quantity:
                trades.append(
                    cs.Trade(
                        symbol,
                        day,
                        1 if found.reaction > 0 else -1,
                        quantity,
                        found.entry_minute,
                        found.entry,
                        found.exit_minute,
                        found.exit,
                        "time_exit",
                    )
                )
    return cs.report(
        RUN_ID,
        trades,
        sessions,
        params={
            "event": "first NSE disclosure of results, 09:20-14:30",
            "reaction": f"{REACTION} minutes from the close before disclosure",
            "threshold": THRESHOLD,
            "entry": "next open, in the reaction's direction",
            "exit": "15:10",
            "sizing": f"₹{cs.CAPITAL / MAX_OPEN:,.0f} a trade, at most {MAX_OPEN} a day",
            "excluded": "2022-07-01 to 2022-12-31 (results not labelled)",
            "slippage_bps_per_side": cs.SLIPPAGE_BPS,
        },
    )
