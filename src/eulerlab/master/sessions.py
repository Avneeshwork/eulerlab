"""Short sessions: days the exchange was open, but not for a normal day.

NSE runs a one-hour Muhurat session on Diwali (some years on a weekend), and
the odd day opens late after an outage (2017-07-10 opened at 12:15). Those
days have a real bhavcopy, so they are trading days, but a daily strategy that
treats one as a full day decides on a thin close and fills at a thin price.

A short session is recognised from evidence, not from a list: the day's total
turnover is under `SHORT_SESSION_RATIO` of the median of the
`TRAILING_DAYS` sessions before it. Measured on the price panel 2015-2026,
weekend sessions included (research 183): the fourteen short sessions score
0.10-0.27 and Muhurat 2026-11-08 (a busy afternoon hour) 0.39; the lowest full
day is 0.59 (2021-02-24, NSE's outage day), then New Year's Days at 0.60-0.67.
A full-day Budget Saturday scores about 1. A panel with no turnover (US,
crypto, FX) flags nothing.

# ASSUMPTION: 0.5 separates short from normal sessions. See A-129.
"""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from statistics import median
from typing import Protocol

SHORT_SESSION_RATIO = 0.5
TRAILING_DAYS = 20
MIN_TRAILING = 10
"""A day needs this many earlier sessions before it can be judged."""
MIN_BREADTH = 100
"""Fewer symbols than this on the busiest day and the panel is not judged: one
stock's quiet day says nothing about how long the market was open."""


class _HasTurnover(Protocol):
    @property
    def day(self) -> date: ...

    @property
    def turnover(self) -> float: ...


def short_days(turnover_by_day: Mapping[date, float]) -> frozenset[date]:
    """Days whose turnover is far below the sessions just before them."""
    days = sorted(turnover_by_day)
    found: set[date] = set()
    for index, day in enumerate(days):
        window = [turnover_by_day[d] for d in days[max(0, index - TRAILING_DAYS) : index]]
        if len(window) < MIN_TRAILING:
            continue
        typical = median(window)
        if typical > 0 and turnover_by_day[day] < SHORT_SESSION_RATIO * typical:
            found.add(day)
    return frozenset(found)


def short_sessions(rows: Iterable[_HasTurnover]) -> frozenset[date]:
    """Short sessions in a panel, from the rows' own turnover."""
    totals: dict[date, float] = {}
    counts: dict[date, int] = {}
    for row in rows:
        totals[row.day] = totals.get(row.day, 0.0) + (row.turnover or 0.0)
        counts[row.day] = counts.get(row.day, 0) + 1
    if not counts or max(counts.values()) < MIN_BREADTH:
        return frozenset()
    return short_days(totals)


def regular_days(
    days: Sequence[date], warmup: int, short: frozenset[date]
) -> tuple[list[date], int]:
    """Drop short sessions from a day list, keeping the run's first decision day.

    `warmup` is an index into `days`. Removing earlier days would move it, so
    it is recomputed to point at the same calendar day (or the next regular
    one when that day is itself short).
    """
    if not short or warmup >= len(days):
        return list(days), warmup
    start = days[warmup]
    kept = [d for d in days if d not in short]
    return kept, bisect_left(kept, start)
