"""Rows the research reader must not see: unexplained jumps in the old years (A-146).

The 2000-2014 rows hold 3,280 one-day moves over 40% (research 195). Some are
splits and bonuses, some one-day misprints, some unexplained. Landing data is
never edited, so nothing is corrected in place. Instead:

1. **Factors are confirmed.** A price factor before 2015 is kept only when the
   observed close-to-close ratio across its ex-date matches it within
   `RATIO_TOLERANCE`. One that matches nothing is dropped (the share count did
   not move the price, so the record is doubtful).
2. **One-day prints are excluded.** A move over `JUMP` that comes back within
   `REVERT` of the earlier close the next session excludes that one row.
3. **Every other unexplained jump is masked.** The instrument is excluded for
   `WINDOW` sessions either side of the jump.
4. **A minimum price.** In 2000-2003 a row closing under Rs 10 is excluded:
   one tick there was a move of 5% or more.

The mask is a dated file in the panel's own contract. Each entry carries an
`event_time` (the first excluded session) and a `knowledge_time` (when the
evidence existed: the jump's close, or the next session's for a print that
reverted). `MarketView` applies an entry only once `as_of` reaches its
knowledge time, so a strategy standing before a jump still sees what was
printed then.

Nothing reads this file unless it exists; the live panel has none (ADR-188).
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

# ASSUMPTION: A-146. Chosen by hand from the 3,280 moves counted on 2026-11-14.
JUMP = 0.40
RATIO_TOLERANCE = 0.10
REVERT = 0.15
WINDOW = 20
MIN_PRICE = 10.0
MIN_PRICE_FROM, MIN_PRICE_TO = date(2000, 1, 1), date(2003, 12, 31)
CONFIRM_BEFORE = date(2015, 1, 1)
"""Factors from this day on are never touched: the live panel's years."""


def _at_close(day: date) -> str:
    return datetime.combine(day, CLOSE, IST).isoformat()


@dataclass(frozen=True)
class Exclusion:
    instrument: str
    first: date
    last: date
    reason: str
    known: datetime

    def to_json(self) -> dict[str, str]:
        return {
            "instrument": self.instrument,
            "from": self.first.isoformat(),
            "to": self.last.isoformat(),
            "reason": self.reason,
            "event_time": _at_close(self.first),
            "knowledge_time": self.known.isoformat(),
        }


@dataclass
class MaskReport:
    jumps: int = 0
    classes: Counter[str] = field(default_factory=Counter)
    factors_kept: int = 0
    factors_dropped: int = 0

    def summary(self) -> str:
        lines = [
            f"one-day moves over {JUMP:.0%}: {self.jumps:,}",
            *(f"  {n:>6,}  {c}" for c, n in self.classes.most_common()),
            f"pre-2015 factors kept (ratio matches within {RATIO_TOLERANCE:.0%}): "
            f"{self.factors_kept:,}; dropped: {self.factors_dropped:,}",
        ]
        return "\n".join(lines)


Bar = tuple[date, float]


def build(
    series: Mapping[str, Sequence[Bar]],
    factors: Mapping[str, Sequence[tuple[date, float]]],
    sessions: Sequence[date],
) -> tuple[list[Exclusion], dict[str, list[tuple[date, float]]], MaskReport]:
    """The mask, and the pre-2015 factors that a matching jump confirms.

    `series` is each instrument's (day, raw close), oldest first; `factors` its
    (ex-date, price factor); `sessions` every trading day."""
    report = MaskReport()
    pos = {d: i for i, d in enumerate(sessions)}
    kept: dict[str, list[tuple[date, float]]] = defaultdict(list)
    out: list[Exclusion] = []
    for key, bars in series.items():
        days = [d for d, _ in bars]
        confirmed: set[date] = set()
        for ex, factor in factors.get(key, []):
            if ex >= CONFIRM_BEFORE:
                kept[key].append((ex, factor))
                continue
            i = bisect.bisect_left(days, ex)
            ratio = bars[i - 1][1] / bars[i][1] if 0 < i < len(bars) and bars[i][1] > 0 else None
            if ratio is not None and abs(ratio / factor - 1) <= RATIO_TOLERANCE:
                kept[key].append((ex, factor))
                confirmed.add(bars[i][0])
                report.factors_kept += 1
            else:
                report.factors_dropped += 1
        for k in range(1, len(bars)):
            (_, c0), (d1, c1) = bars[k - 1], bars[k]
            if d1 >= CONFIRM_BEFORE or c0 <= 0 or abs(c1 / c0 - 1) <= JUMP:
                continue
            report.jumps += 1
            if d1 in confirmed:
                report.classes["confirmed split or bonus"] += 1
                continue
            nxt = bars[k + 1] if k + 1 < len(bars) else None
            if nxt is not None and abs(nxt[1] / c0 - 1) < REVERT:
                report.classes["one-day print, row excluded"] += 1
                known = datetime.combine(nxt[0], CLOSE, IST)
                out.append(Exclusion(key, d1, d1, "one-day print", known))
                continue
            report.classes[f"unexplained, {WINDOW} sessions each side excluded"] += 1
            centre = pos.get(d1, 0)
            first = sessions[max(0, centre - WINDOW)]
            last = sessions[min(len(sessions) - 1, centre + WINDOW)]
            known = datetime.combine(d1, CLOSE, IST)
            out.append(Exclusion(key, first, last, "unexplained jump", known))
    return out, dict(kept), report


def write(path: Path, exclusions: Iterable[Exclusion]) -> int:
    rule = {
        "rule": "min_price",
        "value": MIN_PRICE,
        "from": MIN_PRICE_FROM.isoformat(),
        "to": MIN_PRICE_TO.isoformat(),
        "event_time": _at_close(MIN_PRICE_FROM),
        "knowledge_time": _at_close(MIN_PRICE_FROM),
    }
    rows = sorted((e.to_json() for e in exclusions), key=lambda r: (r["instrument"], r["from"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in [rule, *rows]:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    return len(rows)


@dataclass(frozen=True)
class Mask:
    by_instrument: Mapping[str, Sequence[tuple[date, date, date]]]
    """instrument -> (first, last, known day), sorted by first."""
    min_price: tuple[float, date, date] | None

    def hides(self, row: PanelRow, as_of: date) -> bool:
        if self.min_price is not None:
            floor, first, last = self.min_price
            if first <= row.day <= last and row.close < floor:
                return True
        for first, last, known in self.by_instrument.get(row.isin, ()):
            if first > row.day:
                break
            if row.day <= last and known <= as_of:
                return True
        return False

    def apply(
        self, history: Mapping[str, Sequence[PanelRow]], as_of: date
    ) -> dict[str, list[PanelRow]]:
        """Each symbol's rows without those the mask hides by `as_of`."""
        return {
            symbol: [r for r in rows if not self.hides(r, as_of)]
            for symbol, rows in history.items()
        }


def load(path: Path = MASK_PATH) -> Mask | None:
    """The mask, or None when there is none (the live panel has none)."""
    if not path.exists():
        return None
    by: dict[str, list[tuple[date, date, date]]] = defaultdict(list)
    floor: tuple[float, date, date] | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("rule") == "min_price":
            first, last = date.fromisoformat(row["from"]), date.fromisoformat(row["to"])
            floor = (float(row["value"]), first, last)
            continue
        known = datetime.fromisoformat(row["knowledge_time"]).astimezone(IST).date()
        by[str(row["instrument"])].append(
            (date.fromisoformat(row["from"]), date.fromisoformat(row["to"]), known)
        )
    return Mask({k: sorted(v) for k, v in by.items()}, floor)


_CACHE: dict[str, tuple[float, Mask | None]] = {}


def active(path: Path = MASK_PATH) -> Mask | None:
    """The mask beside the panel, re-read only when the file changes."""
    stamp = path.stat().st_mtime if path.exists() else -1.0
    cached = _CACHE.get(str(path))
    if cached is None or cached[0] != stamp:
        _CACHE[str(path)] = (stamp, load(path))
    return _CACHE[str(path)][1]
