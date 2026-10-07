"""`make market-history` — derived tables from the files landed in research 065.

Four outputs under `data/derived/`, caches of the landing zone (which stays the
source of truth):

- `index_history.jsonl` — one line per day holding every NSE index: open,
  high, low, close, volume, turnover, P/E, P/B and dividend yield. India VIX
  is one of them.
- `delivery.jsonl` — one line per day: per EQ-series stock, the traded
  quantity, deliverable quantity and delivery percent.

The two daily tables are extended, not rebuilt: a day already on file is not
read again. `make daily` prunes the local landing zone after mirroring it, and
re-reading eleven years of both files from B2 would spend the bucket's 2,500
downloads a day several times over. `--full` rebuilds them from scratch.
- `nse_calendar.json` — trading days (from the cash bhavcopy manifest) and the
  weekdays the exchange was shut between them.
- `nifty_expiries.json` — every Nifty futures expiry, read from F&O
  bhavcopies fetched from NSE's archive (not B2: the bucket's 2,500
  downloads a day are kept for the panel).

Every stored day carries `event_time` (the session close) and `knowledge_time`
(the evening the file was published, `bitemporal.provenance.knowable_at`), as
`CLAUDE.md` requires of every stored record.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import zipfile
from bisect import bisect_right
from collections.abc import Callable, Iterator, Sequence
from datetime import UTC, date, datetime, timedelta
from functools import cache
from pathlib import Path
from typing import Any

from eulerlab.bitemporal.provenance import knowable_at, session_close

MANIFEST = Path("data/landing/nse/manifest.jsonl")
INDEX_HISTORY = Path("data/derived/index_history.jsonl")
DELIVERY = Path("data/derived/delivery.jsonl")
CALENDAR = Path("data/derived/nse_calendar.json")
EXPIRIES = Path("data/derived/nifty_expiries.json")


def _entries(segment: str) -> list[dict[str, Any]]:
    """Landed files of one segment, one per trade date, oldest first."""
    if not MANIFEST.exists():
        return []
    latest: dict[str, dict[str, Any]] = {}
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            if row.get("segment") == segment:
                latest[row["trade_date"]] = row
    return [latest[d] for d in sorted(latest)]


def _read(entry: dict[str, Any]) -> bytes:
    from eulerlab.ingest import landing_reader

    return landing_reader.read(f"nse/{entry['path']}")


def _number(text: str | None) -> float | None:
    value = (text or "").strip()
    if value in ("", "-"):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _times(trade_date: str, segment: str) -> dict[str, str]:
    return {
        "event_time": session_close(trade_date).isoformat(),
        "knowledge_time": knowable_at(trade_date, segment).isoformat(),
    }


# --- index closes -------------------------------------------------------------


RENAMED = {
    # NSE dropped the "CNX" and other early names between 2015-11-06 and
    # 2015-11-09. Each pair was matched by closing level across that weekend
    # (every one within 2.2%); a "CNX X" not listed here became "Nifty X".
    "CNX Nifty": "Nifty 50",
    "CNX Nifty Junior": "Nifty Next 50",
    "CNX Midcap": "Nifty Midcap 100",
    "CNX Smallcap": "Nifty Smallcap 100",
    "CNX Alpha Index": "Nifty Alpha 50",
    "CNX DEFTY": "Nifty50 USD",
    "CNX Consumption": "Nifty India Consumption",
    "CNX Finance": "Nifty Financial Services",
    "CNX Service Sector": "Nifty Services Sector",
    "CNX Shariah25": "Nifty Shariah 25",
    "CNX Nifty Shariah": "Nifty50 Shariah",
    "CNX 500 Shariah": "Nifty500 Shariah",
    "CNX 100 Equal Weight": "Nifty100 Equal Weight",
    "CNX Nifty Dividend": "Nifty50 Dividend Points",
    "CNX Dividend Opportunities": "Nifty Dividend Opportunities 50",
    "CNX High Beta": "Nifty High Beta 50",
    "CNX Low Volatility": "Nifty Low Volatility 50",
    "S&P CNX 500": "Nifty 500",
    "CPSE": "Nifty CPSE",
    "LIX 15": "Nifty100 Liquid 15",
    "LIX15 Midcap": "Nifty Midcap Liquid 15",
    "NI15": "Nifty Growth Sectors 15",
    "NV 20": "Nifty50 Value 20",
    "NSE Quality 30": "Nifty Quality 30",
    "NIFTY Midcap 50": "Nifty Midcap 50",
    "NIFTY PR 1X Inverse": "Nifty50 PR 1x Inverse",
    "NIFTY PR 2x Leverage": "Nifty50 PR 2x Leverage",
    "NIFTY TR 1X Inverse": "Nifty50 TR 1x Inverse",
    "NIFTY TR 2X Leverage": "Nifty50 TR 2x Leverage",
    "GSEC10 NSE Index": "Nifty 8-13 yr G-Sec",
    "GSECBM NSE Index": "Nifty 10 yr Benchmark G-Sec",
    "NSE GSECBM Clean Price Index": "Nifty 10 yr Benchmark G-Sec (Clean Price)",
    # From April 2016 the files call the Midcap and Smallcap 100 "Free Float"
    # on some days and "NIFTY ..." on others, beside separate full-cap
    # versions ("Nifty Full Midcap 100"), which are different indices.
    "Nifty Free Float Midcap 100": "Nifty Midcap 100",
    "NIFTY Midcap 100": "Nifty Midcap 100",
    "Nifty Free Float Smallcap 100": "Nifty Smallcap 100",
    "NIFTY Smallcap 100": "Nifty Smallcap 100",
}


def canonical_index(name: str) -> str:
    """Today's name for an index, so that one index is one series. NSE renamed
    most indices in late 2015 ("CNX Bank" became "Nifty Bank") and has spelled
    some differently from file to file since."""
    if name in RENAMED:
        return RENAMED[name]
    if name.startswith("CNX "):
        return "Nifty " + name.removeprefix("CNX ")
    return name


def index_rows(payload: bytes, trade_date: str) -> Iterator[dict[str, Any]]:
    reader = csv.DictReader(io.StringIO(payload.decode("utf-8", errors="replace")))
    for row in reader:
        name = (row.get("Index Name") or "").strip()
        close = _number(row.get("Closing Index Value"))
        if not name or close is None:
            continue
        yield {
            "d": trade_date,
            "index": canonical_index(name),
            "raw_index": name,
            "o": _number(row.get("Open Index Value")),
            "h": _number(row.get("High Index Value")),
            "l": _number(row.get("Low Index Value")),
            "c": close,
            "v": _number(row.get("Volume")),
            "turnover_cr": _number(row.get("Turnover (Rs. Cr.)")),
            "pe": _number(row.get("P/E")),
            "pb": _number(row.get("P/B")),
            "dy": _number(row.get("Div Yield")),
            **_times(trade_date, "indices"),
        }


# --- delivery -------------------------------------------------------------------


def delivery_rows(payload: bytes, trade_date: str) -> Iterator[dict[str, Any]]:
    """Record type 20 lines: 20,serial,symbol,series,traded,deliverable,pct."""
    for line in payload.decode("utf-8", errors="replace").splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 7 or parts[0] != "20" or parts[3] != "EQ":
            continue
        traded, deliverable, pct = _number(parts[4]), _number(parts[5]), _number(parts[6])
        if traded is None:
            continue
        yield {
            "d": trade_date,
            "s": parts[2],
            "traded": traded,
            "deliverable": deliverable,
            "pct": pct,
            **_times(trade_date, "delivery"),
        }


def index_day(payload: bytes, trade_date: str) -> dict[str, Any]:
    """One stored line: every index that day, keyed by its canonical name."""
    indices = {}
    for row in index_rows(payload, trade_date):
        fields = {k: row[k] for k in ("o", "h", "l", "c", "v", "turnover_cr", "pe", "pb", "dy")}
        indices[row["index"]] = {"raw_index": row["raw_index"], **fields}
    return {"d": trade_date, **_times(trade_date, "indices"), "indices": indices}


def delivery_day(payload: bytes, trade_date: str) -> dict[str, Any]:
    """One stored line: symbol -> [traded, deliverable, delivery %]."""
    stocks = {
        row["s"]: [row["traded"], row["deliverable"], row["pct"]]
        for row in delivery_rows(payload, trade_date)
    }
    return {"d": trade_date, **_times(trade_date, "delivery"), "stocks": stocks}


def _days_on_file(path: Path) -> set[str]:
    """Days already stored. A line cut short by an interrupted run is dropped
    (the file is rewritten without it) so that day is read again."""
    if not path.exists():
        return set()
    days: set[str] = set()
    broken = False
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                days.add(json.loads(line)["d"])
            except (ValueError, KeyError):
                broken = True
            if not line.endswith("\n"):
                broken = True
    if broken:
        tmp = path.with_suffix(".partial")
        with path.open(encoding="utf-8") as src, tmp.open("w", encoding="utf-8") as out:
            for line in src:
                try:
                    json.loads(line)["d"]
                except (ValueError, KeyError):
                    continue
                out.write(line if line.endswith("\n") else line + "\n")
        tmp.replace(path)
        days = _days_on_file(path)
    return days


def _extend(
    path: Path, segment: str, to_line: Callable[[bytes, str], dict[str, Any]], *, full: bool
) -> tuple[int, int]:
    """Append the landed days not yet stored. Returns (added, total)."""
    if full:
        path.unlink(missing_ok=True)
    have = _days_on_file(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    added = 0
    with path.open("a", encoding="utf-8") as handle:
        for entry in _entries(segment):
            if entry["trade_date"] in have:
                continue
            line = to_line(_read(entry), entry["trade_date"])
            handle.write(json.dumps(line, sort_keys=True) + "\n")
            handle.flush()
            added += 1
    return added, len(have) + added


def build_indices(*, full: bool = False) -> tuple[int, int]:
    return _extend(INDEX_HISTORY, "indices", index_day, full=full)


def build_delivery(*, full: bool = False) -> tuple[int, int]:
    return _extend(DELIVERY, "delivery", delivery_day, full=full)


# --- calendars --------------------------------------------------------------------


def build_calendar() -> dict[str, Any]:
    """Trading days are the dates with a landed cash bhavcopy; a holiday is a
    weekday between the first and last of them with none. A day whose download
    failed would read as a holiday, so the count is printed to be checked."""
    days = sorted({date.fromisoformat(e["trade_date"]) for e in _entries("cm")})
    trading = set(days)
    holidays = []
    if days:
        day = days[0]
        while day <= days[-1]:
            if day.weekday() < 5 and day not in trading:
                holidays.append(day.isoformat())
            day += timedelta(days=1)
    out = {
        "trading_days": [d.isoformat() for d in days],
        "holidays": holidays,
        "source": "dates with a landed NSE cash bhavcopy",
    }
    CALENDAR.parent.mkdir(parents=True, exist_ok=True)
    CALENDAR.write_text(json.dumps(out, indent=1), encoding="utf-8")
    return out


def _fo_expiries(payload: bytes) -> set[str]:
    """Nifty index-futures expiry dates in one F&O bhavcopy, either format."""
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        text = archive.read(archive.namelist()[0]).decode("utf-8", errors="replace")
    found: set[str] = set()
    for row in csv.DictReader(io.StringIO(text)):
        legacy = (row.get("INSTRUMENT") or "").strip() == "FUTIDX" and (
            row.get("SYMBOL") or ""
        ).strip() == "NIFTY"
        udiff = (row.get("FinInstrmTp") or "").strip() == "IDF" and (
            row.get("TckrSymb") or ""
        ).strip() == "NIFTY"
        if legacy:
            raw = (row.get("EXPIRY_DT") or "").strip()
            try:
                found.add(datetime.strptime(raw, "%d-%b-%Y").replace(tzinfo=UTC).date().isoformat())
            except ValueError:
                continue
        elif udiff:
            raw = (row.get("XpryDt") or "").strip()
            try:
                found.add(date.fromisoformat(raw).isoformat())
            except ValueError:
                continue
    return found


def confirm_expiries(
    candidates: Sequence[str],
    trading_days: Sequence[date],
    listed_on: Callable[[date], set[str]],
) -> list[str]:
    """Keep the dates a contract actually expired on.

    A file lists each contract's *scheduled* expiry, and a schedule can change
    after the file: June 2023's expiry moved from the 29th to the 28th when the
    Bakri Id holiday moved, and September 2025's from the 25th to the 30th when
    expiry moved to Tuesday. The union of sampled files holds both dates. A
    contract trades on its expiry day, so a date is real when that day's own
    file lists it; a stale date is replaced by the trading day on or before it
    whose file lists itself, if there is one within a week. Dates after the
    last trading day are kept as scheduled.
    """
    days = sorted(trading_days)
    last = days[-1] if days else date.min
    found: set[str] = set()
    for text in candidates:
        scheduled = date.fromisoformat(text)
        if scheduled > last:
            found.add(text)
            continue
        position = bisect_right(days, scheduled) - 1
        for day in days[max(position - 4, 0) : position + 1][::-1]:
            if day.isoformat() in listed_on(day):
                found.add(day.isoformat())
                break
    return sorted(found)


def build_expiries(every: int = 15) -> list[str]:
    """Sample every `every`-th trading day's F&O file from NSE's archive; each
    lists the next three monthly Nifty futures, so the union is every scheduled
    expiry. `confirm_expiries` then checks each against its own day's file."""
    from eulerlab.ingest.fetch import Fetcher, FetchPolicy, Outcome, UrllibTransport
    from eulerlab.ingest.nse_urls import Segment, candidates

    days = [date.fromisoformat(d) for d in build_calendar()["trading_days"]]
    transport = UrllibTransport()
    transport.establish_session()
    fetcher = Fetcher(transport, FetchPolicy(min_interval_s=0.5))

    @cache
    def listed_on(day: date) -> set[str]:
        for _fmt, url in candidates(day, Segment.FO):
            result = fetcher.get(url)
            if result.outcome is Outcome.ABSENT or result.payload is None:
                continue
            try:
                return _fo_expiries(result.payload)
            except zipfile.BadZipFile:
                continue
        return set()

    scheduled: set[str] = set()
    for day in days[::every] + days[-1:]:
        scheduled |= listed_on(day)
    expiries = confirm_expiries(sorted(scheduled), days, listed_on)
    EXPIRIES.parent.mkdir(parents=True, exist_ok=True)
    EXPIRIES.write_text(
        json.dumps(
            {
                "expiries": expiries,
                "source": "NIFTY index futures, NSE F&O bhavcopy; each date confirmed "
                "by that day's own file",
            }
        ),
        encoding="utf-8",
    )
    return expiries


# --- readers ------------------------------------------------------------------------


@cache
def nifty_expiries() -> tuple[date, ...]:
    """Every Nifty futures expiry on record, or empty when not built."""
    if not EXPIRIES.exists():
        return ()
    data = json.loads(EXPIRIES.read_text(encoding="utf-8"))
    return tuple(date.fromisoformat(d) for d in data.get("expiries", []))


def _stored_days(path: Path) -> Iterator[dict[str, Any]]:
    if not path.exists():
        return
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            yield json.loads(line)


def index_series(name: str) -> list[tuple[date, float]]:
    """One index's daily closes, oldest first, under today's name."""
    out = []
    for day in _stored_days(INDEX_HISTORY):
        bar = day["indices"].get(name)
        if bar is not None:
            out.append((date.fromisoformat(day["d"]), float(bar["c"])))
    return sorted(out)


def delivery_series(symbol: str) -> list[tuple[date, float | None]]:
    """One stock's delivery percent by day, oldest first."""
    out = []
    for day in _stored_days(DELIVERY):
        row = day["stocks"].get(symbol)
        if row is not None:
            out.append((date.fromisoformat(day["d"]), row[2]))
    return sorted(out)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="market-history")
    parser.add_argument("--skip-expiries", action="store_true")
    parser.add_argument("--full", action="store_true", help="rebuild the daily tables")
    args = parser.parse_args(argv)
    for label, build, path in (
        ("index", build_indices, INDEX_HISTORY),
        ("delivery", build_delivery, DELIVERY),
    ):
        added, total = build(full=args.full)
        print(f"{label} days: {added:,} added, {total:,} stored -> {path}")
    calendar = build_calendar()
    print(
        f"calendar: {len(calendar['trading_days']):,} trading days, "
        f"{len(calendar['holidays'])} weekday closures -> {CALENDAR}"
    )
    if not args.skip_expiries:
        expiries = build_expiries()
        print(f"Nifty expiries: {len(expiries)} -> {EXPIRIES}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
