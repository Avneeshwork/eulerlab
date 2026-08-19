"""Trading calendar built from evidence, never from a weekday rule.

A rule says "markets are open Monday to Friday except holidays". That is wrong
often enough to matter, and wrong in a way nothing detects: NSE has run special
sessions on non-weekdays (Muhurat), and a single Monday appeared among
seventeen Tuesday Nifty expiries in the instrument master — which is exactly
why expiry must never be computed from a weekday either.

So the calendar is a *record of what happened*: a day is a trading day if a
bhavcopy exists for it. That is the same evidence the ingest already collects,
so the calendar costs nothing extra and cannot drift from the data.

**Absence is not proof of closure.** A day with no file might be a holiday, or
might be a day we failed to download. The two are distinguished the same way
`nse_eod.py` does it — by cross-checking the segments against each other, since
a real closure shuts both.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum
from itertools import pairwise

SATURDAY = 5


class DayKind(StrEnum):
    TRADING = "trading"
    """A bhavcopy exists. The market was open — this is the only positive fact."""

    CLOSED = "closed"
    """A weekday with no file in either segment. Almost certainly a holiday."""

    WEEKEND = "weekend"

    SUSPECT = "suspect"
    """One segment traded and the other did not.

    A real closure shuts both, so this is either a genuine single-segment
    holiday or a missing download. It is surfaced rather than assumed, because
    guessing either way would hide the other.
    """


@dataclass(frozen=True)
class CalendarDay:
    day: date
    kind: DayKind
    segments: frozenset[str]


class TradingCalendar:
    """Which days the market was open, according to the files we hold."""

    def __init__(self, observed: dict[date, frozenset[str]]) -> None:
        self._observed = observed

    @classmethod
    def from_observations(cls, rows: Iterable[tuple[date, str]]) -> TradingCalendar:
        """Build from (trade_date, segment) pairs — straight from the manifest."""
        seen: dict[date, set[str]] = {}
        for day, segment in rows:
            seen.setdefault(day, set()).add(segment)
        return cls({d: frozenset(s) for d, s in seen.items()})

    def is_trading_day(self, day: date) -> bool:
        """True only when a file exists. Never inferred from the weekday."""
        return day in self._observed

    def classify(
        self, day: date, *, expected: frozenset[str] = frozenset({"cm", "fo"})
    ) -> CalendarDay:
        segments = self._observed.get(day, frozenset())
        if segments:
            kind = DayKind.TRADING if segments >= expected else DayKind.SUSPECT
            return CalendarDay(day, kind, segments)
        if day.weekday() >= SATURDAY:
            return CalendarDay(day, DayKind.WEEKEND, segments)
        return CalendarDay(day, DayKind.CLOSED, segments)

    def trading_days(self, start: date, end: date) -> list[date]:
        return sorted(d for d in self._observed if start <= d <= end)

    def sessions_on_weekends(self) -> list[date]:
        """Special sessions — the case a weekday rule silently misses."""
        return sorted(d for d in self._observed if d.weekday() >= SATURDAY)

    def suspect_days(self, expected: frozenset[str] = frozenset({"cm", "fo"})) -> list[CalendarDay]:
        return [
            self.classify(d, expected=expected)
            for d in sorted(self._observed)
            if not self._observed[d] >= expected
        ]

    def previous_trading_day(self, day: date) -> date | None:
        earlier = [d for d in self._observed if d < day]
        return max(earlier) if earlier else None

    def next_trading_day(self, day: date) -> date | None:
        later = [d for d in self._observed if d > day]
        return min(later) if later else None

    def gaps_longer_than(self, days: int) -> Iterator[tuple[date, date]]:
        """Consecutive trading days more than `days` apart — long closures, or
        stretches we never downloaded. Both are worth seeing."""
        ordered = sorted(self._observed)
        for a, b in pairwise(ordered):
            if (b - a).days > days:
                yield a, b

    def __len__(self) -> int:
        return len(self._observed)


def expiry_weekday_counts(expiries: Iterable[date]) -> dict[str, int]:
    """Weekday distribution of expiries, for showing that a rule would fail.

    Measured on Kite's instrument master: 17 of 18 Nifty expiries fell on a
    Tuesday and one on a Monday. A weekday rule would mis-key that one contract
    in eighteen, silently.
    """
    names = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
    counts: dict[str, int] = {}
    for expiry in expiries:
        name = names[expiry.weekday()]
        counts[name] = counts.get(name, 0) + 1
    return counts


def business_days_between(start: date, end: date) -> Iterator[date]:
    """Weekdays in a range. Only for *planning* a download, never for deciding
    whether the market was open — that is what the calendar is for."""
    current = start
    while current <= end:
        if current.weekday() < SATURDAY:
            yield current
        current += timedelta(days=1)
