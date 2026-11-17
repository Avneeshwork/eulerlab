"""The day after the narrowest range of seven: trade the opening-range breakout (research 112, H-0023).

Crabel (1990) pairs the narrowest daily range in seven sessions (NR7) with an
opening-range breakout the next day; Holmberg, Lönnbark and Lundström (2013)
test opening-range breakouts formally. Fixed rule: after an NR7 session, take
the 09:16-09:30 range. The first one-minute close outside it is followed at the
next open; the stop is the other side of the range; flat at 15:10.

The range starts at 09:16, not 09:15: the first print is an auction artefact
here (research 075), and earlier opening-range results were wrong because of it.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from eulerlab.intraday import cross_section as cs
from eulerlab.intraday import india_papers as ip

RUN_ID = "nse_nr7_opening_range_breakout"
LOOKBACK = 7
RANGE_START, RANGE_END = 1, 16
"""Minutes [1, 16): 09:16 through 09:30."""

MIN_SLOTS = 10


def day_range(day: ip.Day) -> float | None:
    span = day.span(0, day.last + 1)
    return span[0] - span[1] if span else None


@dataclass(frozen=True)
class Mark:
    """An NR7 candidate's day; `direction` 0 when the range never broke."""

    direction: int
    entry_minute: int
    entry: float
    exit_minute: int
    exit: float
    reason: str


def mark(day: ip.Day) -> Mark:
    idle = Mark(0, 0, 0.0, 0, 0.0, "no_breakout")
    opening = day.span(RANGE_START, RANGE_END)
    if opening is None:
        return idle
    top, bottom = opening
    for minute in range(RANGE_END, cs.EXIT - 1):
        if day.high[minute] is None:
            continue
        close = day.close[minute]
        direction = 1 if close > top else -1 if close < bottom else 0
        if not direction:
            continue
        entry = day.fill_at(minute + 1)
        if entry is None or entry[0] >= cs.EXIT:
            return idle
        stop = bottom if direction > 0 else top
        for later in range(entry[0], cs.EXIT):
            low, high, open_ = day.low[later], day.high[later], day.open_[later]
            if low is None or high is None or open_ is None:
                continue
            if direction > 0 and low <= stop:
                return Mark(direction, entry[0], entry[1], later, min(open_, stop), "stop")
            if direction < 0 and high >= stop:
                return Mark(direction, entry[0], entry[1], later, max(open_, stop), "stop")
        leave = day.fill_at(cs.EXIT)
        if leave is None:
            return idle
        return Mark(direction, entry[0], entry[1], leave[0], leave[1], "time_exit")
    return idle


def extract(symbol: str, days: Sequence[ip.Day]) -> dict[date, Mark]:
    ranges = [day_range(day) for day in days]
    out = {}
    for index in range(LOOKBACK, len(days)):
        window = ranges[index - LOOKBACK : index]
        if any(r is None or r <= 0 for r in window):
            continue
        known = [float(r) for r in window if r is not None]
        if known[-1] >= min(known[:-1]):
            continue
        before = cs.previous_close(days, index)
        if before is None or before < cs.MIN_PRICE:
            continue
        out[days[index].day] = mark(days[index])
    return out


def evaluate(marks: Mapping[str, Mapping[date, Mark]], sessions: Sequence[date]) -> dict[str, Any]:
    by_day: dict[date, list[tuple[str, Mark]]] = defaultdict(list)
    for symbol, days in marks.items():
        for day, found in days.items():
            by_day[day].append((symbol, found))
    trades = []
    for day, candidates in by_day.items():
        each = cs.CAPITAL / max(len(candidates), MIN_SLOTS)
        for symbol, found in candidates:
            if not found.direction:
                continue
            quantity = cs.sized(each, found.entry)
            if quantity:
                trades.append(
                    cs.Trade(
                        symbol,
                        day,
                        found.direction,
                        quantity,
                        found.entry_minute,
                        found.entry,
                        found.exit_minute,
                        found.exit,
                        found.reason,
                    )
                )
    return cs.report(
        RUN_ID,
        trades,
        sessions,
        params={
            "setup": "previous session's range the narrowest of the last seven",
            "opening_range": "09:16-09:30",
            "entry": "next open after the first one-minute close outside it",
            "stop": "the other side of the range, filled at the worse of it and the open",
            "exit": "15:10",
            "sizing": f"capital split equally over the day's NR7 names, at least {MIN_SLOTS} ways",
            "slippage_bps_per_side": cs.SLIPPAGE_BPS,
        },
    )
