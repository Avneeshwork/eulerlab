"""ISINs for price rows from before NSE's bhavcopy carried them (ADR-187).

The cash bhavcopy gained an ISIN column in late 2011. Every row before that
has only a ticker, and the panel, the factors and every engine join on the
ISIN-derived `InstrumentId`, never on a ticker. A ticker is not an identity:
companies change symbols, and a delisted company's symbol can be given to a
new one.

So a pre-ISIN row gets an identity only by a chain that can be checked, never
by a plain ticker join:

1. **Anchor.** The first day a symbol appears *with* an ISIN. It must show one
   ISIN only over its first `ANCHOR_SESSIONS` sessions.
2. **Walk.** From the row's day, follow NSE's own symbol-change list
   (`symbolchange.csv`, landed raw) forward, old symbol to new, until the
   symbol reaching the anchor day.
3. **Continuity.** At every step the symbol must trade with no gap longer than
   `MAX_GAP` sessions; a longer silence may be a delisting and a reuse.
4. **No takeover.** If another company's change gives it the symbol this
   chain still holds, the chain is ambiguous.
5. **One a day.** Two symbols that resolve to the same ISIN on one day are
   both left out.

A row failing any of these is left out and counted, not guessed. The cost is
survivorship: a company that stopped trading before late 2011 never reaches an
anchor, so it is missing from the old years (research 195).
"""

from __future__ import annotations

import argparse
import bisect
import csv
import io
import itertools
import json
from collections import Counter, defaultdict
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from eulerlab.paths import data_path

SYMBOL_CHANGES_URL = "https://nsearchives.nseindia.com/content/equities/symbolchange.csv"
SEGMENT = "symbol_changes"
LANDING = data_path("landing/nse")

# ASSUMPTION: A-144. Chosen by hand: about three months of sessions. Longer
# than a suspension seen in practice, shorter than a relisting under the same
# symbol. Recheck against the rows it leaves out.
MAX_GAP = 60
ANCHOR_SESSIONS = 20


@dataclass(frozen=True)
class SymbolChange:
    old: str
    new: str
    effective: date


_MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")


def _nse_date(text: str) -> date | None:
    """DD-MON-YYYY, month in English whatever the machine's locale."""
    parts = text.upper().split("-")
    if len(parts) != 3 or parts[1] not in _MONTHS or not (parts[0] + parts[2]).isdigit():
        return None
    return date(int(parts[2]), _MONTHS.index(parts[1]) + 1, int(parts[0]))


def parse_symbol_changes(payload: bytes) -> list[SymbolChange]:
    """NSE's `symbolchange.csv`: company, old symbol, new symbol, DD-MON-YYYY."""
    text = payload.decode("latin-1")
    out: list[SymbolChange] = []
    for row in csv.reader(io.StringIO(text)):
        if len(row) < 4 or row[1].strip().upper() == "OLD SYMBOL":
            continue
        old, new, when = row[1].strip(), row[2].strip(), row[3].strip()
        effective = _nse_date(when)
        if effective is None:
            continue
        if old and new and old != new:
            out.append(SymbolChange(old, new, effective))
    return sorted(out, key=lambda c: (c.effective, c.old))


@dataclass
class FillReport:
    rows_in: int = 0
    already_keyed: int = 0
    filled: int = 0
    left_out: Counter[str] = field(default_factory=Counter)
    left_out_by_year: Counter[str] = field(default_factory=Counter)
    first_isin_day: str = ""

    def summary(self) -> str:
        lines = [
            f"rows read            : {self.rows_in:,}",
            f"first day with ISINs : {self.first_isin_day}",
            f"already had an ISIN  : {self.already_keyed:,}",
            f"ISIN filled          : {self.filled:,}",
            f"left out             : {sum(self.left_out.values()):,}",
        ]
        lines += [f"  {why:<19}: {n:,}" for why, n in sorted(self.left_out.items())]
        lines += [f"  {y}: {n:,}" for y, n in sorted(self.left_out_by_year.items())]
        return "\n".join(lines)


class Resolver:
    """Point-in-time ticker -> instrument key, from the rows themselves."""

    def __init__(
        self,
        sessions: Sequence[str],
        presence: dict[str, list[int]],
        anchors: dict[str, tuple[int, str | None]],
        changes: Sequence[SymbolChange],
        *,
        max_gap: int = MAX_GAP,
    ) -> None:
        self.sessions = list(sessions)
        self.presence = presence
        self.anchors = anchors
        self.max_gap = max_gap
        self.by_old: dict[str, list[tuple[int, str]]] = defaultdict(list)
        self.by_new: dict[str, list[tuple[int, str]]] = defaultdict(list)
        for change in changes:
            at = bisect.bisect_left(self.sessions, change.effective.isoformat())
            self.by_old[change.old].append((at, change.new))
            self.by_new[change.new].append((at, change.old))
        self._memo: dict[tuple[str, int], tuple[str | None, str]] = {}

    def _continuous(self, symbol: str, start: int, end: int) -> bool:
        """`symbol` trades from session `start` to `end` with no gap over max_gap."""
        days = self.presence.get(symbol, [])
        i = bisect.bisect_left(days, start)
        j = bisect.bisect_right(days, end)
        inside = days[i:j]
        if not inside:
            return end - start <= self.max_gap
        points = [start, *inside, end]
        return all(b - a <= self.max_gap for a, b in itertools.pairwise(points))

    def resolve(self, symbol: str, at: int) -> tuple[str | None, str]:
        """(instrument key, "") or (None, reason)."""
        key = (symbol, at)
        if key not in self._memo:
            self._memo[key] = self._walk(symbol, at)
        return self._memo[key]

    def _walk(self, symbol: str, at: int) -> tuple[str | None, str]:
        current, since = symbol, at
        for _ in range(32):  # a chain of renames is short; a loop is a data error
            anchor = self.anchors.get(current)
            moves = [m for m in self.by_old.get(current, []) if m[0] >= since]
            move = min(moves) if moves else None
            stop = anchor[0] if anchor and (move is None or anchor[0] < move[0]) else None
            until = stop if stop is not None else (move[0] if move else None)
            if until is None:
                return None, "no anchor"
            takers = [t for t, old in self.by_new.get(current, []) if since < t <= until]
            if takers:
                return None, "symbol taken over"
            if not self._continuous(current, since, until):
                return None, "gap in trading"
            if stop is not None and anchor is not None:
                isin = anchor[1]
                return (isin, "") if isin else (None, "anchor has two ISINs")
            assert move is not None
            current, since = move[1], move[0]
        return None, "rename loop"


def _rows(path: Path) -> Iterator[dict[str, object]]:
    with path.open("rb") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def fill(
    staging: Path, out: Path, changes: Sequence[SymbolChange], *, max_gap: int = MAX_GAP
) -> FillReport:
    """Copy `staging` (panel rows, date order) to `out`, giving pre-ISIN rows an
    instrument key by `Resolver`, leaving out and counting the rest."""
    report = FillReport()
    days: set[str] = set()
    first_isin_day = ""
    for row in _rows(staging):
        day = str(row["d"])
        days.add(day)
        if row.get("isin") and (not first_isin_day or day < first_isin_day):
            first_isin_day = day
    sessions = sorted(days)
    index = {d: i for i, d in enumerate(sessions)}
    presence: dict[str, list[int]] = defaultdict(list)
    seen: dict[str, tuple[int, set[str]]] = {}
    for row in _rows(staging):
        i, symbol, isin = index[str(row["d"])], str(row["s"]), str(row.get("isin") or "")
        if not presence[symbol] or presence[symbol][-1] != i:
            presence[symbol].append(i)
        if isin:
            first, isins = seen.setdefault(symbol, (i, set()))
            if i - first < ANCHOR_SESSIONS:
                isins.add(isin)
    anchors = {s: (first, next(iter(i)) if len(i) == 1 else None) for s, (first, i) in seen.items()}
    resolver = Resolver(sessions, presence, anchors, changes, max_gap=max_gap)
    report.first_isin_day = first_isin_day

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as handle:
        day_rows: list[dict[str, object]] = []
        current = ""
        end: dict[str, object] = {"d": ""}
        for row in itertools.chain(_rows(staging), [end]):
            if row["d"] != current and day_rows:
                _write_day(handle, day_rows, resolver, index, first_isin_day, report)
                day_rows = []
            current = str(row["d"])
            if current:
                report.rows_in += 1
                day_rows.append(row)
    return report


def _write_day(
    handle: io.TextIOBase,
    rows: list[dict[str, object]],
    resolver: Resolver,
    index: dict[str, int],
    first_isin_day: str,
    report: FillReport,
) -> None:
    day = str(rows[0]["d"])
    keyed: list[tuple[dict[str, object], str]] = []
    for row in rows:
        isin = str(row.get("isin") or "")
        if isin:
            report.already_keyed += 1
            keyed.append((row, isin))
            continue
        if first_isin_day and day >= first_isin_day:
            keyed.append((row, ""))  # an ISIN-era row without one stays as built
            continue
        found, why = resolver.resolve(str(row["s"]), index[day])
        if found is None:
            report.left_out[why] += 1
            report.left_out_by_year[day[:4]] += 1
            continue
        keyed.append(({**row, "isin": found}, "filled"))
    counts = Counter(str(r["isin"]) for r, _ in keyed if r["isin"])
    for row, how in keyed:
        if row["isin"] and counts[str(row["isin"])] > 1 and how == "filled":
            report.left_out["two symbols, one ISIN"] += 1
            report.left_out_by_year[day[:4]] += 1
            continue
        if how == "filled":
            report.filled += 1
        handle.write(json.dumps(row, sort_keys=True) + "\n")


def land_symbol_changes(today: date) -> Path:
    """Land NSE's symbol-change list raw, once a day, like every other source."""
    from eulerlab.ingest.fetch import Fetcher, FetchPolicy, Outcome, UrllibTransport
    from eulerlab.ingest.landing import Landing

    landing = Landing(LANDING)
    if not landing.has(today, SEGMENT):
        transport = UrllibTransport()
        transport.establish_session()
        result = Fetcher(transport, FetchPolicy(min_interval_s=1.0)).get(SYMBOL_CHANGES_URL)
        if result.outcome is not Outcome.OK or result.payload is None:
            msg = f"{SYMBOL_CHANGES_URL}: {result.outcome} {result.detail}"
            raise RuntimeError(msg)
        changes = parse_symbol_changes(result.payload)
        if not changes:
            raise RuntimeError("symbolchange.csv parsed to nothing; not landed")
        landing.write(
            trade_date=today,
            segment=SEGMENT,
            file_format="csv",
            url=SYMBOL_CHANGES_URL,
            payload=result.payload,
            rows=len(changes),
            inner_name="symbolchange.csv",
            suffix="csv",
        )
    entry = landing.entries()[(today.isoformat(), SEGMENT)]
    return LANDING / entry.path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="legacy-isin", description=__doc__.splitlines()[0])
    parser.add_argument("staging", type=Path, help="panel rows built without ISINs")
    parser.add_argument("out", type=Path)
    parser.add_argument("--changes", type=Path, default=None, help="a landed symbolchange.csv")
    args = parser.parse_args(argv)
    from eulerlab.ingest.nse_eod import today_ist

    source = args.changes or land_symbol_changes(today_ist())
    changes = parse_symbol_changes(source.read_bytes())
    print(f"{len(changes):,} symbol changes from {source}")
    print(fill(args.staging, args.out, changes).summary())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
