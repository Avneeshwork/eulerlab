"""`make fii-dii-history MONTHS=12` — backfill FII/DII cash flows from aggregators.

NSE serves the latest FII/DII day only (research 004), so `fii_dii_cash`
captures forward from its first run and has no past. The operator decided on
2026-10-30 to fill the past from public aggregator pages (ADR-089), the same
decision ADR-009 made for Trendlyne, with the same limits: one thread, a gap of
at least 2 s between requests, a normal browser User-Agent, stop on 403 or 429
rather than push, no evasion, no redistribution.

Three sources, one role each (research 127):

- **Trendlyne** is the history. One page per month,
  `.../cash-pastmonth/DD-Mon-YYYY/`, carries about 20 trading days of FII and
  DII gross buy, gross sell and net in a JSON attribute on the table
  `cash-table-main-pastmonth`. Figures are rounded to 0.1 crore.
- **Groww** (`/fii-dii-data`, about 20 days, 0.01 crore) and **stockezee**
  (`/fii-dii-historical-data`, about a year, net only) are cross-checks. They
  are landed and compared, never written to the table.

Rules:

1. Every page lands unedited through `Landing.write`, which records its SHA-256
   and knowledge time. A page already in the manifest is not fetched again.
2. A backfilled row's knowledge time is when its page was scraped. It was not
   known to us before then, so `rows(as_of=...)` stays honest.
3. A day the table already holds (NSE's own capture, or an earlier backfill) is
   never overwritten.
4. A row is refused when net is not buy minus sell, when its date is in the
   future, or when it is not a trading day by the bhavcopy manifest.
"""

from __future__ import annotations

import argparse
import html
import json
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from eulerlab.ingest import fii_dii_cash as cash
from eulerlab.ingest.fetch import Fetcher, FetchPolicy, Outcome, UrllibTransport
from eulerlab.ingest.landing import Landing

TRENDLYNE = "trendlyne"
GROWW = "groww"
STOCKEZEE = "stockezee"
SEGMENTS = (TRENDLYNE, GROWW, STOCKEZEE)

TRENDLYNE_URL = "https://trendlyne.com/macro-data/fii-dii/latest/cash-pastmonth/{day}/"
GROWW_URL = "https://groww.in/fii-dii-data"
STOCKEZEE_URL = "https://stockezee.com/fii-dii-historical-data"

BHAVCOPY_MANIFEST = Path("data/landing/nse/manifest.jsonl")

TRENDLYNE_TOLERANCE = 0.15
"""Trendlyne rounds buy, sell and net to 0.1 crore each, so a correct row can
be off by up to 0.15 (three roundings of 0.05). NSE's own 0.05 would refuse
correct rows: 15-Sep-2026 is 13194.8 - 16172.6 = -2977.8 against -2977.9."""

DISAGREEMENT_CRORE = 1.0
"""Two sources further apart than this on one figure are reported."""

STOP_STATUS = frozenset({403, 429})
"""Refused or rate limited: stop the run, do not push."""

TRENDLYNE_HEADERS = [
    "date",
    "FII Gross Purchase",
    "FII Gross Sales",
    "FII Net Purchase / Sales",
    "DII Net Purchase / Sales",
    "DII Gross Sales",
    "DII Gross Purchase",
    "details",
]
"""The cash table's columns as read on 2026-10-30. Any other layout is refused."""

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}")


# --- parsing -----------------------------------------------------------------------


@dataclass(frozen=True)
class Parsed:
    """What one page said: full days, net-only days, and rows it refused."""

    days: list[cash.FlowDay] = field(default_factory=list)
    nets: dict[date, tuple[float, float]] = field(default_factory=dict)
    """day → (FII net, DII net), for a source that publishes nets only."""
    refused: list[str] = field(default_factory=list)


def _flow(buy: object, sell: object, net: object, tolerance: float) -> cash.Flow | None:
    b, s, n = (cash._number(v) for v in (buy, sell, net))
    if b is None or s is None or n is None or b < 0 or s < 0:
        return None
    if abs(b - s - n) > tolerance:
        return None
    return cash.Flow(buy=b, sell=s, net=n)


def _iso_day(value: object) -> date | None:
    text = str(value or "")
    if not _ISO.match(text):
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def parse_trendlyne(payload: bytes) -> Parsed | None:
    """Trendlyne's monthly page, or None when the cash table is not there.

    # ASSUMPTION: the cash table is `<table id="cash-table-main-pastmonth">`
    # with its rows in a `data-jsondata` attribute and the columns in
    # TRENDLYNE_HEADERS (A-071). Read from live pages on 2026-10-30.
    """
    text = payload.decode("utf-8", errors="replace")
    tag = re.search(r"<table[^>]*\bid=\"cash-table-main-pastmonth\"[^>]*>", text, re.DOTALL)
    if tag is None:
        return None
    attr = re.search(r"data-jsondata=\"([^\"]*)\"", tag.group(0))
    if attr is None:
        return None
    try:
        table = json.loads(html.unescape(attr.group(1)))
    except json.JSONDecodeError:
        return None
    if not isinstance(table, dict) or table.get("headers") != TRENDLYNE_HEADERS:
        return None
    out = Parsed()
    for row in table.get("data") or []:
        if not isinstance(row, list) or len(row) < 7:
            continue
        day = _iso_day(row[0])
        if day is None:
            continue  # "Last 30 Days" and the other summary rows
        fii = _flow(row[1], row[2], row[3], TRENDLYNE_TOLERANCE)
        dii = _flow(row[6], row[5], row[4], TRENDLYNE_TOLERANCE)
        if fii is None or dii is None:
            out.refused.append(f"{day}: net is not buy minus sell, or a figure is blank")
            continue
        out.days.append(cash.FlowDay(trade_date=day, fii=fii, dii=dii))
    return out


def _next_data(payload: bytes) -> Any:
    text = payload.decode("utf-8", errors="replace")
    match = re.search(r"<script id=\"__NEXT_DATA__\"[^>]*>(.*?)</script>", text, re.DOTALL)
    if match is None:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None


def _initial_data(payload: bytes) -> list[Any] | None:
    data = _next_data(payload)
    try:
        rows = data["props"]["pageProps"]["initialData"]
    except (TypeError, KeyError):
        return None
    return rows if isinstance(rows, list) else None


def parse_groww(payload: bytes) -> Parsed | None:
    """Groww's page: `initialData` rows with fii/dii grossBuy, grossSell, netBuySell.

    # ASSUMPTION: field names as read from the live page on 2026-10-30 (A-071).
    """
    rows = _initial_data(payload)
    if rows is None:
        return None
    out = Parsed()
    for row in rows:
        if not isinstance(row, dict):
            continue
        day = _iso_day(row.get("date"))
        groups = [row.get(k) for k in ("fii", "dii")]
        if day is None or not all(isinstance(g, dict) for g in groups):
            continue
        fii, dii = (
            _flow(g.get("grossBuy"), g.get("grossSell"), g.get("netBuySell"), cash.TOLERANCE_CRORE)
            for g in groups
            if isinstance(g, dict)
        )
        if fii is None or dii is None:
            out.refused.append(f"{day}: net is not buy minus sell, or a figure is missing")
            continue
        out.days.append(cash.FlowDay(trade_date=day, fii=fii, dii=dii))
    return out


def parse_stockezee(payload: bytes) -> Parsed | None:
    """stockezee's page: `initialData` rows with `fii_cash` nets per category.

    # ASSUMPTION: field names as read from the live page on 2026-10-30 (A-071).
    """
    rows = _initial_data(payload)
    if rows is None:
        return None
    out = Parsed()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("fii_cash"), list):
            continue
        day = _iso_day(row.get("date"))
        nets: dict[str, float] = {}
        for item in row["fii_cash"]:
            if not isinstance(item, dict):
                continue
            group = cash._group(str(item.get("category") or ""))
            value = cash._number(item.get("net_value"))
            if group is not None and value is not None:
                nets[group] = value
        if day is not None and set(nets) == {"FII", "DII"}:
            out.nets[day] = (nets["FII"], nets["DII"])
    return out


PARSERS: dict[str, Callable[[bytes], Parsed | None]] = {
    TRENDLYNE: parse_trendlyne,
    GROWW: parse_groww,
    STOCKEZEE: parse_stockezee,
}


# --- which days are real -------------------------------------------------------------


def trading_days(manifest: Path = BHAVCOPY_MANIFEST) -> frozenset[date]:
    """Days NSE published a cash bhavcopy for. Empty when the manifest is missing."""
    if not manifest.exists():
        return frozenset()
    days: set[date] = set()
    for line in manifest.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and row.get("segment") == "cm":
            day = _iso_day(row.get("trade_date"))
            if day is not None:
                days.add(day)
    return frozenset(days)


def is_trading_day(day: date, known: frozenset[date], today: date) -> bool:
    """Not in the future, and a bhavcopy day where the manifest reaches.

    Past the manifest's last day (the bhavcopy is not landed yet) only a
    weekday is required. A muhurat Sunday is a bhavcopy day, so it passes.
    """
    if day > today:
        return False
    if known and day <= max(known):
        return day in known
    return day.weekday() < 5


# --- pages ---------------------------------------------------------------------------


def _month_end(year: int, month: int) -> date:
    first_next = date(year + month // 12, month % 12 + 1, 1)
    return first_next - timedelta(days=1)


def page_dates(today: date, months: int) -> list[date]:
    """The month ends of the last `months` whole months, then today. Oldest first.

    Each Trendlyne page reaches back about a month from its date, so these
    pages cover the span with a day or so of overlap.
    """
    out: list[date] = []
    year, month = today.year, today.month
    for _ in range(months):
        year, month = (year - 1, 12) if month == 1 else (year, month - 1)
        out.append(_month_end(year, month))
    return [*reversed(out), today]


def trendlyne_url(day: date) -> str:
    return TRENDLYNE_URL.format(day=f"{day.day:02d}-{_MONTHS[day.month - 1]}-{day.year}")


@dataclass
class Report:
    fetched: int = 0
    skipped: int = 0
    failed: list[str] = field(default_factory=list)
    stopped: str = ""
    written: int = 0
    held: int = 0
    refused: list[str] = field(default_factory=list)
    disagreements: list[str] = field(default_factory=list)
    compared: dict[str, int] = field(default_factory=dict)


def land(
    fetcher: Fetcher,
    landing: Landing,
    *,
    segment: str,
    key: date,
    url: str,
    report: Report,
) -> bool:
    """Fetch one page unless the manifest has it. False when the run must stop."""
    if (key.isoformat(), segment) in landing.entries():
        report.skipped += 1
        return True
    result = fetcher.get(url)
    if result.outcome is not Outcome.OK or result.payload is None:
        if result.status in STOP_STATUS:
            report.stopped = f"{segment} answered HTTP {result.status} at {url}; stopped"
            return False
        report.failed.append(f"{segment} {url}: {result.detail or result.outcome}")
        return True
    parsed = PARSERS[segment](result.payload)
    if parsed is None:
        # Land nothing we cannot read: the layout changed, or it is a block page.
        report.failed.append(f"{segment} {url}: page has no table we know")
        return True
    landing.write(
        trade_date=key,
        segment=segment,
        file_format="html",
        url=url,
        payload=result.payload,
        rows=len(parsed.days) + len(parsed.nets),
        inner_name=url,
        suffix="html",
    )
    report.fetched += 1
    return True


def landed(
    landing: Landing, read: Callable[[str], bytes], segment: str
) -> list[tuple[str, Parsed]]:
    """Every landed page of one source, oldest page first, with its knowledge time."""
    out: list[tuple[str, Parsed]] = []
    for (_, seg), entry in sorted(landing.entries().items()):
        if seg != segment:
            continue
        parsed = PARSERS[segment](read(f"{cash.TREE}/{entry.path}"))
        if parsed is not None:
            out.append((entry.knowledge_time, parsed))
    return out


def history_rows(
    landing: Landing,
    read: Callable[[str], bytes],
    *,
    today: date,
    known: frozenset[date],
    refused: list[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Table rows from the landed Trendlyne pages: the first page to show a day wins."""
    out: dict[str, dict[str, Any]] = {}
    for knowledge_time, parsed in landed(landing, read, TRENDLYNE):
        if refused is not None:
            refused.extend(parsed.refused)
        for day in parsed.days:
            iso = day.trade_date.isoformat()
            if iso in out:
                continue
            if not is_trading_day(day.trade_date, known, today):
                if refused is not None:
                    refused.append(f"{iso}: not a trading day, or in the future")
                continue
            out[iso] = cash.to_row(day, knowledge_time, source=TRENDLYNE)
    return out


# --- comparing -----------------------------------------------------------------------

_FIELDS = ("fii_buy", "fii_sell", "fii_net", "dii_buy", "dii_sell", "dii_net")


def compare(
    left_name: str,
    left: Mapping[str, Mapping[str, Any]],
    right_name: str,
    right: Mapping[str, Mapping[str, Any]],
    report: Report,
) -> None:
    """Report each figure two sources disagree on by more than DISAGREEMENT_CRORE."""
    shared = sorted(set(left) & set(right))
    report.compared[f"{left_name}~{right_name}"] = len(shared)
    for day in shared:
        for name in _FIELDS:
            a, b = left[day].get(name), right[day].get(name)
            if a is None or b is None:
                continue
            if abs(float(a) - float(b)) > DISAGREEMENT_CRORE:
                report.disagreements.append(
                    f"{day} {name}: {left_name} {float(a):.2f} vs {right_name} {float(b):.2f}"
                )


def _as_table(days: Iterable[cash.FlowDay]) -> dict[str, dict[str, Any]]:
    return {d.trade_date.isoformat(): cash.to_row(d, "", source="") for d in days}


def _nets_table(nets: Mapping[date, tuple[float, float]]) -> dict[str, dict[str, Any]]:
    return {d.isoformat(): {"fii_net": f, "dii_net": i} for d, (f, i) in nets.items()}


def cross_check(
    landing: Landing,
    read: Callable[[str], bytes],
    history: Mapping[str, Mapping[str, Any]],
    nse: Mapping[str, Mapping[str, Any]],
    report: Report,
) -> None:
    compare(TRENDLYNE, history, "nse", nse, report)
    groww: dict[str, dict[str, Any]] = {}
    for _, parsed in landed(landing, read, GROWW):
        groww.update(_as_table(parsed.days))
    compare(TRENDLYNE, history, GROWW, groww, report)
    compare(GROWW, groww, "nse", nse, report)
    ezee: dict[str, dict[str, Any]] = {}
    for _, parsed in landed(landing, read, STOCKEZEE):
        ezee.update(_nets_table(parsed.nets))
    compare(TRENDLYNE, history, STOCKEZEE, ezee, report)


# --- the run -------------------------------------------------------------------------


class SiteTransport(UrllibTransport):
    """The stdlib transport without NSE's Referer: these are not NSE's pages."""

    def _headers(self) -> dict[str, str]:
        return {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }


def backfill(
    fetcher: Fetcher,
    landing: Landing,
    read: Callable[[str], bytes],
    *,
    today: date,
    months: int,
    derived: Path = cash.DERIVED,
    known: frozenset[date] = frozenset(),
) -> Report:
    report = Report()
    pages = [(TRENDLYNE, d, trendlyne_url(d)) for d in page_dates(today, months)]
    pages += [(GROWW, today, GROWW_URL), (STOCKEZEE, today, STOCKEZEE_URL)]
    for segment, key, url in pages:
        if not land(fetcher, landing, segment=segment, key=key, url=url, report=report):
            break

    history = history_rows(landing, read, today=today, known=known, refused=report.refused)
    held = {r["day"]: r for r in cash.rows(derived, as_of=cash._far_future())}
    nse = {d: r for d, r in held.items() if r.get("source", "nse") == "nse"}
    cross_check(landing, read, history, nse, report)

    new = [history[d] for d in sorted(history) if d not in held]
    if new:
        derived.parent.mkdir(parents=True, exist_ok=True)
        with derived.open("a", encoding="utf-8") as handle:
            for row in new:
                handle.write(json.dumps(row, sort_keys=True) + "\n")
    report.written = len(new)
    report.held = len(history) - len(new)
    return report


def render(report: Report, derived: Path) -> str:
    held = cash.rows(derived)
    by_source: dict[str, int] = {}
    for row in held:
        by_source[str(row.get("source", "nse"))] = (
            by_source.get(str(row.get("source", "nse")), 0) + 1
        )
    lines = [
        f"fii-dii-history: {report.fetched} page(s) fetched, {report.skipped} already landed",
        f"  table: {report.written} day(s) added, {report.held} already held",
        f"  table now: {len(held)} day(s), "
        f"{held[0]['day'] if held else '-'} to {held[-1]['day'] if held else '-'}, by source {by_source}",
        f"  compared (days in common): {report.compared}",
    ]
    if report.stopped:
        lines.append(f"  STOPPED: {report.stopped}")
    lines += [f"  failed: {f}" for f in report.failed]
    lines += [f"  refused: {r}" for r in report.refused]
    if report.disagreements:
        lines.append(
            f"  disagreements over {DISAGREEMENT_CRORE:.0f} crore: {len(report.disagreements)}"
        )
        lines += [f"    {d}" for d in report.disagreements]
    else:
        lines.append(f"  disagreements over {DISAGREEMENT_CRORE:.0f} crore: none")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fii-dii-history")
    parser.add_argument("--months", type=int, default=12)
    parser.add_argument("--landing", type=Path, default=cash.DEFAULT_LANDING)
    parser.add_argument("--derived", type=Path, default=cash.DERIVED)
    parser.add_argument("--min-interval", type=float, default=2.5)
    args = parser.parse_args(argv)
    if args.min_interval < 2.0:
        parser.error("--min-interval may not be under 2 seconds (ADR-089)")

    from eulerlab.ingest import landing_reader

    def read(relative: str) -> bytes:
        local = args.landing.parent / relative
        return local.read_bytes() if local.exists() else landing_reader.read(relative)

    # One attempt per page: a refusal is an answer, not something to retry past.
    fetcher = Fetcher(
        SiteTransport(), FetchPolicy(min_interval_s=args.min_interval, max_attempts=1)
    )
    report = backfill(
        fetcher,
        Landing(args.landing),
        read,
        today=datetime.now(cash.IST).date(),
        months=args.months,
        derived=args.derived,
        known=trading_days(),
    )
    print(render(report, args.derived))
    return 1 if report.stopped or report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
