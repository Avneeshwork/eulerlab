"""Backfill NSE end-of-day bhavcopy files into the landing zone.

Run it twice; the second run downloads nothing. Interrupt it; restart it and it
resumes. Both properties come from the manifest in ``landing.py`` rather than
from anything clever here.

**On telling a holiday from a failure.** These must never be conflated: one is
normal, the other is silent data loss. Deriving "holiday" from "no file" is
circular reasoning, so this module does not do it. Instead:

* A transport failure or non-404 error is ``FAILED`` — always data loss, never
  a holiday.
* A 404 is ``ABSENT`` — the file is genuinely not published.
* ``ABSENT`` is then classified by *cross-checking the two segments against each
  other*: if both cash and F&O are absent on a weekday, that is a market
  closure. If one is absent while the other is present, that is an **anomaly**
  and gets flagged, because it is exactly the shape of a silent gap.
* Where NSE's holiday list covers the date, a likely closure is upgraded to a
  confirmed one. That list only covers the current year, so most historical
  closures stay "likely" — which is the honest label, not a defect.
"""

from __future__ import annotations

import argparse
import io
import zipfile
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from zoneinfo import ZoneInfo

from eulerlab.ingest.fetch import Fetcher, FetchPolicy, Outcome, UrllibTransport
from eulerlab.ingest.holidays import load_holidays
from eulerlab.ingest.landing import Landing
from eulerlab.ingest.nse_urls import FileFormat, Segment, candidates

DEFAULT_LANDING = Path("data/landing/nse")
SATURDAY = 5

IST = ZoneInfo("Asia/Kolkata")
"""A trading day is defined in exchange time, never in the machine's time.

Running this from a different timezone must not shift which day 'today' means.
"""


def today_ist() -> date:
    return datetime.now(IST).date()


class DayStatus(StrEnum):
    DOWNLOADED = "downloaded"
    SKIPPED = "skipped"
    """Already in the landing zone. The idempotency path."""
    ABSENT = "absent"
    """404 from every candidate format. The market was probably shut."""
    FAILED = "failed"
    """Could not be retrieved. Data loss until re-run."""


class ClosureKind(StrEnum):
    HOLIDAY_CONFIRMED = "holiday (confirmed)"
    HOLIDAY_LIKELY = "holiday (likely)"
    ANOMALY = "ANOMALY — one segment missing, the other present"
    DOWNLOAD_FAILED = "DOWNLOAD FAILED"


@dataclass(frozen=True)
class DayOutcome:
    trade_date: date
    segment: Segment
    status: DayStatus
    file_format: FileFormat | None = None
    rows: int = 0
    detail: str = ""


@dataclass
class Summary:
    outcomes: list[DayOutcome] = field(default_factory=list)

    interrupted: bool = False
    """True when the operator pressed Ctrl-C.

    An interrupted run is not a failed run: everything already written is
    valid and the manifest is the resume point. Saying so plainly stops a
    partial backfill from looking like data loss.
    """

    def count(self, status: DayStatus) -> int:
        return sum(1 for o in self.outcomes if o.status is status)

    @property
    def rows(self) -> int:
        return sum(o.rows for o in self.outcomes)

    @property
    def dates(self) -> list[date]:
        return sorted({o.trade_date for o in self.outcomes})

    def by_date(self, trade_date: date) -> list[DayOutcome]:
        return [o for o in self.outcomes if o.trade_date == trade_date]

    def classify_closures(self, holidays: frozenset[date]) -> dict[date, ClosureKind]:
        """Explain every date that did not fully land."""
        report: dict[date, ClosureKind] = {}
        for day in self.dates:
            outcomes = self.by_date(day)
            if any(o.status is DayStatus.FAILED for o in outcomes):
                report[day] = ClosureKind.DOWNLOAD_FAILED
                continue
            absent = [o for o in outcomes if o.status is DayStatus.ABSENT]
            if not absent:
                continue
            if len(absent) < len(outcomes):
                report[day] = ClosureKind.ANOMALY
            elif day in holidays:
                report[day] = ClosureKind.HOLIDAY_CONFIRMED
            else:
                report[day] = ClosureKind.HOLIDAY_LIKELY
        return report


def business_days(start: date, end: date, *, include_weekends: bool = False) -> Iterator[date]:
    """Dates from start to end inclusive.

    Weekends are skipped by default. NSE occasionally runs a special session on
    a non-weekday (Muhurat trading on Diwali), so ``include_weekends`` exists to
    sweep for those without making every backfill pay for ~1,100 extra requests.
    The nightly job passes it (a week's window costs four extra requests), and
    the other NSE feeds follow the landed result through `session_days`.
    # ASSUMPTION: skipping weekends misses special sessions. See A-011.
    """
    current = start
    while current <= end:
        if include_weekends or current.weekday() < SATURDAY:
            yield current
        current += timedelta(days=1)


def weekend_sessions(landing_root: Path = DEFAULT_LANDING) -> frozenset[date]:
    """Saturdays and Sundays with a landed cash bhavcopy: NSE's special sessions.

    Read from the manifest, not the files, because the nightly job deletes the
    local copy once B2 holds it. The bhavcopy step probes weekends
    (`--include-weekends`), so every other NSE feed can follow it here instead
    of probing again (ADR-157).
    """
    found: set[date] = set()
    for trade_day, segment in Landing(landing_root).entries():
        if segment != Segment.CM.value:
            continue
        day = date.fromisoformat(trade_day)
        if day.weekday() >= SATURDAY:
            found.add(day)
    return frozenset(found)


def session_days(start: date, end: date, landing_root: Path = DEFAULT_LANDING) -> list[date]:
    """Weekdays from start to end, plus any weekend session the bhavcopy proved."""
    extra = weekend_sessions(landing_root)
    return [
        d
        for d in business_days(start, end, include_weekends=True)
        if d.weekday() < SATURDAY or d in extra
    ]


def count_rows(payload: bytes) -> tuple[int, str]:
    """Rows and inner filename of a zipped bhavcopy, without unpacking to disk.

    The landing zone stores the exchange's bytes untouched; this reads them in
    memory purely so the summary can report row counts and so a zero-row or
    corrupt file is caught at download time rather than months later.
    """
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = [n for n in archive.namelist() if n.lower().endswith(".csv")]
        if not names:
            msg = f"no .csv inside archive; contents: {archive.namelist()}"
            raise ValueError(msg)
        name = names[0]
        with archive.open(name) as handle:
            total = sum(1 for _ in handle)
    return max(total - 1, 0), name


def fetch_day(
    fetcher: Fetcher,
    landing: Landing,
    trade_date: date,
    segment: Segment,
) -> DayOutcome:
    """One date, one segment. Tries each candidate format until one answers."""
    if landing.has(trade_date, segment.value):
        return DayOutcome(trade_date, segment, DayStatus.SKIPPED)

    failure: str = ""
    for file_format, url in candidates(trade_date, segment):
        result = fetcher.get(url)

        if result.outcome is Outcome.OK and result.payload is not None:
            rows, inner = count_rows(result.payload)
            landing.write(
                trade_date=trade_date,
                segment=segment.value,
                file_format=file_format.value,
                url=url,
                payload=result.payload,
                rows=rows,
                inner_name=inner,
            )
            return DayOutcome(trade_date, segment, DayStatus.DOWNLOADED, file_format, rows)

        if result.outcome is Outcome.FAILED:
            failure = result.detail

    if failure:
        return DayOutcome(trade_date, segment, DayStatus.FAILED, detail=failure)
    return DayOutcome(trade_date, segment, DayStatus.ABSENT)


def ingest(
    *,
    start: date,
    end: date,
    landing: Landing,
    fetcher: Fetcher,
    segments: Sequence[Segment] = (Segment.CM, Segment.FO),
    include_weekends: bool = False,
) -> Summary:
    summary = Summary()
    try:
        for trade_date in business_days(start, end, include_weekends=include_weekends):
            for segment in segments:
                summary.outcomes.append(fetch_day(fetcher, landing, trade_date, segment))
    except KeyboardInterrupt:
        # Ctrl-C must not look like a crash. Every file already landed is
        # complete and recorded; the next run picks up from the manifest.
        summary.interrupted = True
    return summary


def render(summary: Summary, holidays: frozenset[date], start: date, end: date) -> str:
    """The operator-facing report. Plain, and honest about what it does not know."""
    lines: list[str] = []
    dates = summary.dates
    span = f"{start} to {end}"
    covered = f"{dates[0]} to {dates[-1]}" if dates else "no dates in range"

    lines.append(f"NSE EOD ingest — requested {span}, walked {covered}")
    lines.append("")
    lines.append(f"  downloaded  {summary.count(DayStatus.DOWNLOADED):>6}")
    lines.append(f"  skipped     {summary.count(DayStatus.SKIPPED):>6}  (already landed)")
    lines.append(f"  absent      {summary.count(DayStatus.ABSENT):>6}  (404 — market shut)")
    lines.append(f"  failed      {summary.count(DayStatus.FAILED):>6}")
    lines.append(f"  rows parsed {summary.rows:>6}")

    closures = summary.classify_closures(holidays)
    failed = {d: k for d, k in closures.items() if k is ClosureKind.DOWNLOAD_FAILED}
    anomalies = {d: k for d, k in closures.items() if k is ClosureKind.ANOMALY}
    confirmed = sum(1 for k in closures.values() if k is ClosureKind.HOLIDAY_CONFIRMED)
    likely = sum(1 for k in closures.values() if k is ClosureKind.HOLIDAY_LIKELY)

    lines.append("")
    lines.append("Missing days")
    lines.append(f"  market holidays, confirmed against NSE's list  {confirmed:>5}")
    lines.append(f"  market holidays, likely (both segments absent) {likely:>5}")
    lines.append(f"  anomalies (one segment missing)                {len(anomalies):>5}")
    lines.append(f"  download failures                              {len(failed):>5}")

    if anomalies:
        lines.append("")
        lines.append("  ANOMALIES — one segment absent while the other landed:")
        lines.extend(f"    {d}" for d in sorted(anomalies))
    if failed:
        lines.append("")
        lines.append("  FAILED — data loss, re-run to retry:")
        lines.extend(f"    {d}" for d in sorted(failed))

    if not holidays:
        lines.append("")
        lines.append("  Note: no NSE holiday list was available, so every closure above is")
        lines.append("  'likely' rather than confirmed. That is a gap in corroboration,")
        lines.append("  not evidence that the data is wrong.")

    if summary.interrupted:
        lines.append("")
        lines.append("  INTERRUPTED by Ctrl-C. Everything above is safely landed.")
        lines.append("  Re-run the same command to resume from where it stopped.")

    verdict = "CLEAN" if not failed and not anomalies else "NEEDS ATTENTION"
    if summary.interrupted:
        verdict = "PARTIAL — resume by re-running"
    lines.append("")
    lines.append(f"Result: {verdict}")
    return "\n".join(lines)


def _parse_date(text: str) -> date:
    return date.fromisoformat(text)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ingest-eod",
        description="Download NSE equity and F&O bhavcopy files into the landing zone.",
    )
    parser.add_argument("--from", dest="start", type=_parse_date, required=True)
    parser.add_argument("--to", dest="end", type=_parse_date, default=today_ist())
    parser.add_argument("--landing", type=Path, default=DEFAULT_LANDING)
    parser.add_argument("--min-interval", type=float, default=1.5)
    parser.add_argument("--include-weekends", action="store_true")
    parser.add_argument(
        "--segments",
        nargs="+",
        choices=[s.value for s in Segment],
        default=[s.value for s in Segment],
    )
    args = parser.parse_args(argv)

    if args.end < args.start:
        parser.error("--to must not be earlier than --from")

    landing = Landing(args.landing)
    transport = UrllibTransport()
    transport.establish_session()
    fetcher = Fetcher(transport, FetchPolicy(min_interval_s=args.min_interval))

    summary = ingest(
        start=args.start,
        end=args.end,
        landing=landing,
        fetcher=fetcher,
        segments=[Segment(s) for s in args.segments],
        include_weekends=args.include_weekends,
    )

    holidays = load_holidays(args.landing.parent / "reference")
    print(render(summary, holidays, args.start, args.end))
    if summary.interrupted:
        return 130  # conventional exit code for SIGINT
    return 1 if summary.count(DayStatus.FAILED) else 0


if __name__ == "__main__":
    raise SystemExit(main())
