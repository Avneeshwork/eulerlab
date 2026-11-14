"""Unusual prices in the old years: checked against the bhavcopy, kept unless proved wrong.

The 2000-2014 rows hold 3,280 one-day moves over 40% (research 195). The
operator's rule (2026-11-14): check every unusual price, and keep it exactly
as NSE published it unless a check proves it wrong. Landing data is never
edited; a wrong row is excluded with its reason, and everything else stays.

For each move over `JUMP` between consecutive sessions of one instrument:

1. **A confirmed split or bonus.** A price factor whose ratio matches the
   close-to-close move within `RATIO_TOLERANCE`. Kept, no flag. A factor
   before 2015 that matches no move is dropped from the factor file.
2. **The day's own range.** Open and close must lie inside [low, high].
3. **Turnover.** Turnover divided by volume, the average traded price, must
   lie inside [low, high] (within `TURNOVER_SLACK`).
4. **The next file agrees.** The next session's PREVCLOSE must equal this
   close (within `PREV_CLOSE_SLACK`), unless a corporate action falls between.
   NSE's own next file disagreeing is evidence the printed close was wrong.

A row failing 2, 3 or 4 is **excluded**, with the failed check as its reason.
Every other unusual move is **flagged** "unusual, unverified": it stays in
what research reads, and the flag is there to be looked at, not acted on.
Universe rules such as a minimum price stay in each strategy, not here.

The mask is a dated file in the panel's own contract: each entry carries an
`event_time` (the session it concerns) and a `knowledge_time` (when its
evidence existed: the next session's close for check 4, the day's own close
otherwise). `MarketView` drops an excluded row only once `as_of` reaches that
time. Nothing reads the file unless it exists; the live panel has none
(ADR-188).
"""

from __future__ import annotations

import bisect
import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from eulerlab.paths import data_path

if TYPE_CHECKING:
    from eulerlab.features.panel import PanelRow

MASK_PATH = data_path("derived/panel_mask.jsonl")
IST = ZoneInfo("Asia/Kolkata")
CLOSE = time(15, 30)

# ASSUMPTION: A-146. Chosen by hand; recheck against the rows they exclude.
JUMP = 0.40
RATIO_TOLERANCE = 0.10
TURNOVER_SLACK = 0.01
PREV_CLOSE_SLACK = 0.005
CONFIRM_BEFORE = date(2015, 1, 1)
"""Factors from this day on are never touched: the live panel's years."""

UNVERIFIED = "unusual, unverified"


def _at_close(day: date) -> datetime:
    return datetime.combine(day, CLOSE, IST)


@dataclass(frozen=True)
class Day:
    """One instrument on one session, as the panel row and the bhavcopy give it."""

    day: date
    open: float
    high: float
    low: float
    close: float
    volume: float
    turnover: float
    prev_close: float | None = None
    """The PREVCLOSE NSE printed in this session's file."""


@dataclass(frozen=True)
class Entry:
    instrument: str
    day: date
    reason: str
    exclude: bool
    known: datetime

    def to_json(self) -> dict[str, object]:
        return {
            "instrument": self.instrument,
            "day": self.day.isoformat(),
            "reason": self.reason,
            "exclude": self.exclude,
            "event_time": _at_close(self.day).isoformat(),
            "knowledge_time": self.known.isoformat(),
        }


@dataclass
class MaskReport:
    jumps: int = 0
    classes: Counter[str] = field(default_factory=Counter)
    factors_kept: int = 0
    factors_dropped: int = 0

    def summary(self) -> str:
        return "\n".join(
            [
                f"one-day moves over {JUMP:.0%}: {self.jumps:,}",
                *(f"  {n:>6,}  {c}" for c, n in self.classes.most_common()),
                f"pre-2015 factors kept (ratio matches within {RATIO_TOLERANCE:.0%}): "
                f"{self.factors_kept:,}; dropped: {self.factors_dropped:,}",
            ]
        )


def _inside(value: float, low: float, high: float, slack: float = 0.0) -> bool:
    return low * (1 - slack) <= value <= high * (1 + slack)


def failed_check(today: Day, tomorrow: Day | None, action_between: bool) -> str | None:
    """The first check this session's row fails, or None."""
    if today.low > today.high or not (
        _inside(today.open, today.low, today.high) and _inside(today.close, today.low, today.high)
    ):
        return "open or close outside the day's range"
    if today.volume > 0 and today.turnover > 0:
        average = today.turnover / today.volume
        if not _inside(average, today.low, today.high, TURNOVER_SLACK):
            return "turnover does not match volume times a price in the range"
    if (
        tomorrow is not None
        and tomorrow.prev_close
        and not action_between
        and abs(tomorrow.prev_close / today.close - 1) > PREV_CLOSE_SLACK
    ):
        return "next session's PREVCLOSE differs from this close"
    return None


def build(
    series: Mapping[str, Sequence[Day]],
    factors: Mapping[str, Sequence[tuple[date, float]]],
    actions: Mapping[str, Sequence[date]] | None = None,
) -> tuple[list[Entry], dict[str, list[tuple[date, float]]], MaskReport]:
    """Mask entries for every unusual move, and the factors a matching move confirms.

    `actions` are the ex-dates of every NSE corporate action of each instrument,
    of any kind, so a scheme or demerger with no ratio still explains a gap
    between this close and the next session's PREVCLOSE."""
    report = MaskReport()
    kept: dict[str, list[tuple[date, float]]] = defaultdict(list)
    out: list[Entry] = []
    for key, rows in series.items():
        days = [r.day for r in rows]
        confirmed: set[date] = set()
        action_days = [ex for ex, _ in factors.get(key, [])] + list((actions or {}).get(key, []))
        for ex, factor in factors.get(key, []):
            if ex >= CONFIRM_BEFORE:
                kept[key].append((ex, factor))
                continue
            i = bisect.bisect_left(days, ex)
            ok = 0 < i < len(rows) and rows[i].close > 0
            if ok and abs(rows[i - 1].close / rows[i].close / factor - 1) <= RATIO_TOLERANCE:
                kept[key].append((ex, factor))
                confirmed.add(rows[i].day)
                report.factors_kept += 1
            else:
                report.factors_dropped += 1
        before = rows[0]
        for k in range(1, len(rows)):
            # Measured from the last row kept: after an excluded misprint, the
            # next day's return to normal is not a second unusual move.
            today = rows[k]
            if today.day >= CONFIRM_BEFORE or before.close <= 0:
                before = today
                continue
            if abs(today.close / before.close - 1) <= JUMP:
                before = today
                continue
            report.jumps += 1
            if today.day in confirmed:
                report.classes["confirmed split or bonus"] += 1
                before = today
                continue
            tomorrow = rows[k + 1] if k + 1 < len(rows) else None
            between = tomorrow is not None and any(
                today.day < a <= tomorrow.day for a in action_days
            )
            reason = failed_check(today, tomorrow, between)
            if reason is None:
                report.classes[UNVERIFIED] += 1
                out.append(Entry(key, today.day, UNVERIFIED, False, _at_close(today.day)))
                before = today
                continue
            report.classes[f"excluded: {reason}"] += 1
            when = tomorrow.day if tomorrow is not None and "PREVCLOSE" in reason else today.day
            out.append(Entry(key, today.day, reason, True, _at_close(when)))
    return out, dict(kept), report


def write(path: Path, entries: Iterable[Entry]) -> int:
    rows = sorted(
        (e.to_json() for e in entries), key=lambda r: (str(r["instrument"]), str(r["day"]))
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    return len(rows)


@dataclass(frozen=True)
class Mask:
    excluded: Mapping[tuple[str, date], date]
    """(instrument, day) -> the day its exclusion became known."""
    flagged: Mapping[tuple[str, date], str]
    """(instrument, day) -> reason, for rows kept as published."""

    def hides(self, row: PanelRow, as_of: date) -> bool:
        known = self.excluded.get((row.isin, row.day))
        return known is not None and known <= as_of

    def flag(self, row: PanelRow) -> str | None:
        return self.flagged.get((row.isin, row.day))

    def apply(
        self, history: Mapping[str, Sequence[PanelRow]], as_of: date
    ) -> dict[str, list[PanelRow]]:
        """Each symbol's rows without the excluded ones known by `as_of`."""
        return {
            symbol: [r for r in rows if not self.hides(r, as_of)]
            for symbol, rows in history.items()
        }


def load(path: Path = MASK_PATH) -> Mask | None:
    """The mask, or None when there is none (the live panel has none)."""
    if not path.exists():
        return None
    excluded: dict[tuple[str, date], date] = {}
    flagged: dict[tuple[str, date], str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        key = (str(row["instrument"]), date.fromisoformat(row["day"]))
        if row["exclude"]:
            excluded[key] = datetime.fromisoformat(row["knowledge_time"]).astimezone(IST).date()
        else:
            flagged[key] = str(row["reason"])
    return Mask(excluded, flagged)


_CACHE: dict[str, tuple[float, Mask | None]] = {}


def active(path: Path = MASK_PATH) -> Mask | None:
    """The mask beside the panel, re-read only when the file changes."""
    stamp = path.stat().st_mtime if path.exists() else -1.0
    cached = _CACHE.get(str(path))
    if cached is None or cached[0] != stamp:
        _CACHE[str(path)] = (stamp, load(path))
    return _CACHE[str(path)][1]
