"""ISINs for price rows from before NSE's bhavcopy carried them (ADR-187).

The cash bhavcopy gained an ISIN column in late 2011. Every row before that
has only a ticker, and the panel, the factors and every engine join on the
ISIN-derived `InstrumentId`, never on a ticker. A ticker is not an identity:
companies change symbols, and a delisted company's symbol can be given to a
new one.

So a pre-ISIN row gets an identity only by a chain that can be checked, never
by a plain ticker join:

1. **Runs.** Each symbol's sessions are cut into runs at any gap over
   `MAX_GAP` sessions (a delisting and a reuse would look like that) and at
   every symbol change that names it.
2. **Links.** NSE's own symbol-change list (`symbolchange.csv`, landed raw)
   links the old symbol's run ending at a change to the new symbol's run
   starting there. A run with two predecessors or two successors (a merger, a
   split of one line into two) is not linked.
3. **Anchor.** A chain that reaches the first day its symbol appears *with* an
   ISIN takes that ISIN's key, if it shows one ISIN over its first
   `ANCHOR_SESSIONS` sessions; with two it is left out.
4. **Own id.** A chain that never reaches an ISIN (a company that stopped
   trading before late 2011) gets its own internal id, `NOISIN` plus a hash,
   recorded in a master of its own with no ISIN. No ISIN is guessed.
5. **One a day.** Two rows that reach the same key on one day are left out;
   one symbol's second series row (EQ and BE the same day) is dropped first.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import hashlib
import io
import itertools
import json
from collections import Counter, defaultdict
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

from eulerlab.master import store
from eulerlab.master.identity import InstrumentId
from eulerlab.master.registry import Registry
from eulerlab.master.store import BuildStamp
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
    no_isin: int = 0
    no_isin_ids: set[str] = field(default_factory=set)
    filled_ids: set[str] = field(default_factory=set)
    left_out: Counter[str] = field(default_factory=Counter)
    left_out_by_year: Counter[str] = field(default_factory=Counter)
    first_isin_day: str = ""

    def summary(self) -> str:
        lines = [
            f"rows read            : {self.rows_in:,}",
            f"first day with ISINs : {self.first_isin_day}",
            f"already had an ISIN  : {self.already_keyed:,}",
            f"ISIN filled          : {self.filled:,} rows, {len(self.filled_ids):,} instruments",
            f"own id, no ISIN      : {self.no_isin:,} rows, {len(self.no_isin_ids):,} instruments",
            f"left out             : {sum(self.left_out.values()):,}",
        ]
        lines += [f"  {why:<19}: {n:,}" for why, n in sorted(self.left_out.items())]
        lines += [f"  {y}: {n:,}" for y, n in sorted(self.left_out_by_year.items())]
        return "\n".join(lines)


NO_ISIN_PREFIX = "NOISIN"
"""Internal ids minted here start with this, never with "IN": no ISIN can
collide with one, and a reader can tell an instrument that has no ISIN."""


def no_isin_id(symbol: str, first_day: str) -> str:
    """A stable internal id for one checked chain that never reached an ISIN.

    Opaque on purpose (a hash, not the ticker), so nothing can join on it as a
    ticker. Deterministic, so two builds give the same id."""
    digest = hashlib.sha256(f"{symbol}|{first_day}".encode()).hexdigest()[:10].upper()
    return f"{NO_ISIN_PREFIX}{digest}"


@dataclass(frozen=True)
class Run:
    """One symbol trading with no gap over `max_gap` sessions, cut at every
    symbol change that touches it."""

    symbol: str
    start: int
    end: int


class Resolver:
    """Point-in-time ticker -> instrument key, from the rows themselves (ADR-187).

    A symbol's sessions are cut into runs at gaps and at symbol changes. A
    change links the old symbol's run ending there to the new symbol's run
    starting there. A chain of linked runs that reaches the ISIN era takes its
    anchor's key; one that does not gets its own `NOISIN` id. A run with two
    predecessors or two successors is not linked at all, so each chain is one
    company or it is cut."""

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
        self.anchors = anchors
        cuts: dict[str, set[int]] = defaultdict(set)
        moves: list[tuple[int, str, str]] = []
        for change in changes:
            at = bisect.bisect_left(self.sessions, change.effective.isoformat())
            cuts[change.old].add(at)
            cuts[change.new].add(at)
            moves.append((at, change.old, change.new))
        self.runs: dict[str, list[Run]] = {}
        for symbol, days in presence.items():
            self.runs[symbol] = _cut(symbol, days, cuts.get(symbol, set()), max_gap)
        self._starts = {sym: [r.start for r in runs] for sym, runs in self.runs.items()}
        successors: dict[Run, list[Run]] = defaultdict(list)
        predecessors: dict[Run, list[Run]] = defaultdict(list)
        for at, old, new in moves:
            before = self._run_ending(old, at, max_gap)
            after = self._run_starting(new, at, max_gap)
            if before is not None and after is not None and before != after:
                successors[before].append(after)
                predecessors[after].append(before)
        self.next: dict[Run, Run] = {
            r: nxt[0]
            for r, nxt in successors.items()
            if len(nxt) == 1 and len(predecessors[nxt[0]]) == 1
        }
        self._memo: dict[Run, tuple[str | None, str]] = {}

    def _run_ending(self, symbol: str, at: int, max_gap: int) -> Run | None:
        for run in self.runs.get(symbol, []):
            if run.start < at and at - max_gap <= run.end < at:
                return run
        return None

    def _run_starting(self, symbol: str, at: int, max_gap: int) -> Run | None:
        for run in self.runs.get(symbol, []):
            if at <= run.start <= at + max_gap:
                return run
        return None

    def run_at(self, symbol: str, at: int) -> Run | None:
        runs = self.runs.get(symbol, [])
        i = bisect.bisect_right(self._starts.get(symbol, []), at) - 1
        return runs[i] if i >= 0 and runs[i].start <= at <= runs[i].end else None

    def resolve(self, symbol: str, at: int) -> tuple[str | None, str]:
        """(key, "isin") or (key, "no isin"), or (None, reason)."""
        run = self.run_at(symbol, at)
        if run is None:
            return None, "not trading"
        if run not in self._memo:
            self._memo[run] = self._chain_key(run)
        return self._memo[run]

    def _chain_key(self, run: Run) -> tuple[str | None, str]:
        current = run
        for _ in range(64):  # a chain of renames is short; a loop is a data error
            anchor = self.anchors.get(current.symbol)
            if anchor is not None and current.start <= anchor[0] <= current.end:
                return (anchor[1], "isin") if anchor[1] else (None, "anchor has two ISINs")
            nxt = self.next.get(current)
            if nxt is None:
                return no_isin_id(current.symbol, self.sessions[current.start]), "no isin"
            current = nxt
        return None, "rename loop"


def _cut(symbol: str, days: list[int], cuts: set[int], max_gap: int) -> list[Run]:
    runs: list[Run] = []
    start = prev = days[0]
    for day in days[1:]:
        if day - prev > max_gap or any(prev < c <= day for c in cuts):
            runs.append(Run(symbol, start, prev))
            start = day
        prev = day
    runs.append(Run(symbol, start, prev))
    return runs


def _rows(path: Path) -> Iterator[dict[str, object]]:
    with path.open("rb") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def fill(
    staging: Path,
    out: Path,
    changes: Sequence[SymbolChange],
    *,
    max_gap: int = MAX_GAP,
    master_out: Path | None = None,
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

    registry = Registry()
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as handle:
        day_rows: list[dict[str, object]] = []
        current = ""
        end: dict[str, object] = {"d": ""}
        for row in itertools.chain(_rows(staging), [end]):
            if row["d"] != current and day_rows:
                _write_day(handle, day_rows, resolver, index, first_isin_day, report, registry)
                day_rows = []
            current = str(row["d"])
            if current:
                report.rows_in += 1
                day_rows.append(row)
    if master_out is not None:
        stamp = BuildStamp(
            built_at=datetime.now(UTC).isoformat(),
            source_files=len(sessions),
            first_date=sessions[0] if sessions else "",
            last_date=first_isin_day,
        )
        store.save(registry, stamp, master_out)
    return report


def _turnover(row: dict[str, object]) -> float:
    value = row.get("t") or 0.0
    return float(value) if isinstance(value, int | float | str) else 0.0


def _write_day(
    handle: io.TextIOBase,
    rows: list[dict[str, object]],
    resolver: Resolver,
    index: dict[str, int],
    first_isin_day: str,
    report: FillReport,
    registry: Registry,
) -> None:
    day = str(rows[0]["d"])
    keyed: list[tuple[dict[str, object], str]] = []
    # ASSUMPTION: A-145. Before about 2002 a stock often traded in both the EQ
    # and BE series on one day; the panel row carries no series, so the row
    # with the larger turnover (the EQ print) is kept and the other counted.
    best: dict[str, dict[str, object]] = {}
    for row in rows:
        symbol = str(row["s"])
        if symbol in best:
            report.left_out["second series row"] += 1
            report.left_out_by_year[day[:4]] += 1
            if _turnover(row) <= _turnover(best[symbol]):
                continue
        best[symbol] = row
    for row in best.values():
        isin = str(row.get("isin") or "")
        if isin:
            report.already_keyed += 1
            keyed.append((row, "as built"))
            continue
        if first_isin_day and day >= first_isin_day:
            keyed.append((row, "as built"))  # an ISIN-era row without one stays as built
            continue
        found, how = resolver.resolve(str(row["s"]), index[day])
        if found is None:
            report.left_out[how] += 1
            report.left_out_by_year[day[:4]] += 1
            continue
        keyed.append(({**row, "isin": found}, how))
    counts = Counter(str(r["isin"]) for r, _ in keyed if r["isin"])
    for row, how in keyed:
        key = str(row["isin"])
        if how != "as built" and counts[key] > 1:
            report.left_out["two symbols, one ISIN"] += 1
            report.left_out_by_year[day[:4]] += 1
            continue
        if how == "isin":
            report.filled += 1
            report.filled_ids.add(key)
        elif how == "no isin":
            report.no_isin += 1
            report.no_isin_ids.add(key)
            registry.observe(
                date.fromisoformat(day),
                instrument_id=InstrumentId(issuer=key),
                ticker=str(row["s"]),
                isin="",
            )
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
    master_out = args.out.with_name("instruments_no_isin.jsonl")
    print(fill(args.staging, args.out, changes, master_out=master_out).summary())
    print(f"instruments without an ISIN -> {master_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
