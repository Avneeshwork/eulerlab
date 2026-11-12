"""`make nse-reports` — NSE's daily market reports the platform did not hold.

Research 130 records where each one was found and how far back it goes.

Dated reports, one file per trading day:

- **`bulk_deals`**, **`block_deals`**, **`short_selling`** — NSE's archive API
  in its CSV form. The JSON form stops at 70 rows, so it is never used.
- **`fo_ban`** — the securities in the F&O ban period for that trade date.
- **`slbm`** — the stock lending and borrowing bhavcopy.
- **`mtf`** — margin trading funding, per stock (a zipped CSV).
- **`insider`** — SEBI PIT insider-trading disclosures (`corporates-pit-gg`).
  NSE serves nothing before about May 2026 here; the older endpoint answers
  empty for every date (checked 2026-10-30).
- **`sast`** — SEBI SAST regulation 29 acquisition disclosures.

Snapshots, today's state only (NSE publishes no history):

- **`pledges`** — promoter pledge data for every listed company.
- **`ipo_current`**, **`ipo_past`** — open issues and the past-issue list.
- **`nifty50_list`** — NSE's Nifty 50 constituent file, so membership on each
  date is on record.
- **`asm`**, **`gsm`** — NSE's additional and graded surveillance lists, and
  **`sec_list`** — every security's series and price band (BE/BZ =
  trade-for-trade). An intraday short must avoid all three (research 174).

Everything lands raw and unedited through the rate-limited `Fetcher` and an
append-only manifest, under `data/landing/nse_reports/`. A report already in
the manifest is never fetched again, even after `prune` has removed the local
copy, because B2 holds it (ADR-095). A day is fetched only once it is over:
deals, ban list, SLBM and MTF from 21:00 IST; insider and SAST filings, which
NSE broadcasts until late, only the next day.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import zipfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from eulerlab.ingest.fetch import Fetcher, FetchPolicy, Outcome, UrllibTransport
from eulerlab.ingest.landing import Landing, ManifestEntry
from eulerlab.ingest.nse_eod import IST, session_days
from eulerlab.paths import data_path

DEFAULT_LANDING = data_path("landing/nse_reports")
API = "https://www.nseindia.com/api"
ARCHIVE = "https://nsearchives.nseindia.com"
EVENING_CUTOFF = (21, 0)
"""IST time after which today's end-of-day reports count as complete."""


def _dmy(day: date, sep: str = "-") -> str:
    return f"{day.day:02d}{sep}{day.month:02d}{sep}{day.year:04d}"


def _text(payload: bytes) -> str:
    return payload.decode("utf-8-sig", errors="replace")


def _csv_rows(header: str) -> Callable[[bytes], int | None]:
    """A CSV whose first cell starts with `header`: rows after the header."""

    def check(payload: bytes) -> int | None:
        text = _text(payload)
        rows = list(csv.reader(io.StringIO(text)))
        if not rows or not rows[0] or not rows[0][0].strip().startswith(header):
            return None
        return sum(1 for row in rows[1:] if any(cell.strip() for cell in row))

    return check


def _ban_rows(payload: bytes) -> int | None:
    lines = [line for line in _text(payload).splitlines() if line.strip()]
    if not lines or not lines[0].startswith("Securities in Ban"):
        return None
    return len(lines) - 1


def _slbm_rows(payload: bytes) -> int | None:
    text = _text(payload)
    if text.lstrip().startswith("<"):
        return None
    rows = [line for line in text.splitlines() if line.count(",") >= 10]
    return len(rows) or None


def _mtf_rows(payload: bytes) -> int | None:
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            names = [n for n in archive.namelist() if n.lower().endswith(".csv")]
            if not names:
                return None
            text = archive.read(names[0]).decode("utf-8", errors="replace")
    except zipfile.BadZipFile:
        return None
    return sum(1 for line in text.splitlines() if line.strip()) or None


def _json_list(key: str | None) -> Callable[[bytes], int | None]:
    """JSON holding a list, at `key` or at the top level: its length."""

    def check(payload: bytes) -> int | None:
        try:
            body = json.loads(payload)
        except ValueError:
            return None
        items = body.get(key) if key and isinstance(body, dict) else body
        return len(items) if isinstance(items, list) else None

    return check


def _asm_rows(payload: bytes) -> int | None:
    """NSE's ASM report: {"longterm": {"data": [...]}, "shortterm": {"data": [...]}}."""
    try:
        body = json.loads(payload)
    except ValueError:
        return None
    if not isinstance(body, dict) or not ({"longterm", "shortterm"} & set(body)):
        return None
    return sum(len((body.get(k) or {}).get("data") or []) for k in ("longterm", "shortterm"))


def _deals(kind: str) -> Callable[[date], str]:
    return lambda d: (
        f"{API}/historicalOR/bulk-block-short-deals?optionType={kind}"
        f"&from={_dmy(d)}&to={_dmy(d)}&csv=true"
    )


@dataclass(frozen=True)
class Report:
    name: str
    url: Callable[[date], str]
    suffix: str
    check: Callable[[bytes], int | None]
    """Rows when the payload is the report asked for, else None. A page that
    parses but is not the report (NSE's HTML error page) must not land."""
    late_filings: bool = False
    """Filed until late at night: a day is complete only the day after."""
    snapshot: bool = False
    """No date in the URL: today's state, landed under today's date."""


# ASSUMPTION: A-075 - these addresses are where NSE served the reports on
# 2026-10-30. A moved one shows as malformed or failed, never as a quiet gap.
REPORTS: dict[str, Report] = {
    r.name: r
    for r in (
        Report("bulk_deals", _deals("bulk_deals"), "csv", _csv_rows("Date")),
        Report("block_deals", _deals("block_deals"), "csv", _csv_rows("Date")),
        Report("short_selling", _deals("short_selling"), "csv", _csv_rows("Date")),
        Report(
            "fo_ban",
            lambda d: f"{ARCHIVE}/archives/fo/sec_ban/fo_secban_{_dmy(d, '')}.csv",
            "csv",
            _ban_rows,
        ),
        Report(
            "slbm",
            lambda d: f"{ARCHIVE}/archives/slbs/bhavcopy/SLBM_BC_{_dmy(d, '')}.DAT",
            "dat",
            _slbm_rows,
        ),
        Report(
            "mtf",
            lambda d: (
                f"{ARCHIVE}/content/equities/mrg_trading_{d.day:02d}{d.month:02d}{d.year % 100:02d}.zip"
            ),
            "zip",
            _mtf_rows,
        ),
        Report(
            "insider",
            lambda d: (
                f"{API}/corporates-pit-gg?index=equities&from_date={_dmy(d)}&to_date={_dmy(d)}"
            ),
            "json",
            _json_list("data"),
            late_filings=True,
        ),
        Report(
            "sast",
            lambda d: (
                f"{API}/corporate-sast-reg29?index=equities&from_date={_dmy(d)}&to_date={_dmy(d)}"
            ),
            "json",
            _json_list("data"),
            late_filings=True,
        ),
        Report(
            "pledges",
            lambda d: f"{API}/corporate-pledgedata?index=equities",
            "json",
            _json_list("data"),
            snapshot=True,
        ),
        Report(
            "ipo_current",
            lambda d: f"{API}/ipo-current-issue",
            "json",
            _json_list(None),
            snapshot=True,
        ),
        Report(
            "ipo_past",
            lambda d: f"{API}/public-past-issues",
            "json",
            _json_list(None),
            snapshot=True,
        ),
        # Research 174: the surveillance lists an intraday short must avoid.
        # Fetched and checked 2026-11-07; NSE publishes no history of them.
        Report("asm", lambda d: f"{API}/reportASM", "json", _asm_rows, snapshot=True),
        Report("gsm", lambda d: f"{API}/reportGSM", "json", _json_list(None), snapshot=True),
        Report(
            "sec_list",
            lambda d: f"{ARCHIVE}/content/equities/sec_list.csv",
            "csv",
            _csv_rows("Symbol"),
            snapshot=True,
        ),
        Report(
            "nifty50_list",
            lambda d: f"{ARCHIVE}/content/indices/ind_nifty50list.csv",
            "csv",
            _csv_rows("Company Name"),
            snapshot=True,
        ),
    )
}


def last_complete_day(report: Report, now: datetime) -> date:
    """The latest date whose report will not change any more."""
    ist = now.astimezone(IST)
    if report.snapshot:
        return ist.date()
    evening = (ist.hour, ist.minute) >= EVENING_CUTOFF
    if report.late_filings or not evening:
        return ist.date() - timedelta(days=1)
    return ist.date()


PROVISIONAL_DAYS = 3
"""An empty answer this soon after the day may only mean NSE has not published
yet: short selling for 2026-10-30 was still empty a day later. Such an answer
is not landed; one older than this is a day with nothing to report."""


def _provisional(entry: ManifestEntry) -> bool:
    known = datetime.fromisoformat(entry.knowledge_time).astimezone(IST).date()
    young = (known - date.fromisoformat(entry.trade_date)).days < PROVISIONAL_DAYS
    return entry.rows == 0 and entry.url.startswith(API) and young


def landed(landing: Landing, day: date, name: str) -> bool:
    """In the manifest, whether or not the local copy has been pruned.

    `Landing.has` also wants the file on disk, which turns every pruned day
    into a re-download. These reports are pruned the same night they land,
    so the manifest is the record (ADR-095). An empty file landed within
    `PROVISIONAL_DAYS` of its day (before this rule existed) does not count.
    """
    entry = landing.entries().get((day.isoformat(), name))
    return entry is not None and not _provisional(entry)


def fetch_one(
    fetcher: Fetcher, landing: Landing, report: Report, day: date, today: date | None = None
) -> str:
    """Returns one of: downloaded, skipped, absent, failed, malformed, not-yet."""
    if landed(landing, day, report.name):
        return "skipped"
    url = report.url(day)
    result = fetcher.get(url)
    if result.outcome is Outcome.ABSENT:
        return "absent"
    if result.outcome is Outcome.FAILED or result.payload is None:
        return "failed"
    rows = report.check(result.payload)
    if rows is None:
        return "malformed"
    today = today or datetime.now(IST).date()
    # Only NSE's API answers an unpublished day with an empty 200; the archive 404s.
    early = url.startswith(API) and not report.snapshot
    if rows == 0 and early and (today - day).days < PROVISIONAL_DAYS:
        return "not-yet"
    # A second file beside an early empty one, never over it: landed files are immutable.
    replaced = (day.isoformat(), report.name) in landing.entries()
    landing.write(
        trade_date=day,
        segment=report.name,
        file_format="recheck" if replaced else "raw",
        url=url,
        payload=result.payload,
        rows=rows,
        inner_name=url.rsplit("/", 1)[-1].split("?", 1)[0],
        suffix=report.suffix,
    )
    return "downloaded"


def days_for(report: Report, start: date, now: datetime) -> list[date]:
    end = last_complete_day(report, now)
    if report.snapshot:
        return [end]
    return session_days(start, end)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nse-reports")
    parser.add_argument("--from", dest="start", type=date.fromisoformat, required=True)
    parser.add_argument("--only", nargs="+", choices=sorted(REPORTS), default=None)
    parser.add_argument("--landing", type=Path, default=DEFAULT_LANDING)
    parser.add_argument("--min-interval", type=float, default=1.0)
    args = parser.parse_args(argv)

    landing = Landing(args.landing)
    transport = UrllibTransport()
    transport.establish_session()
    fetcher = Fetcher(transport, FetchPolicy(min_interval_s=args.min_interval))
    now = datetime.now(IST)
    failed = 0
    for name in args.only or list(REPORTS):
        report = REPORTS[name]
        days = days_for(report, args.start, now)
        counts: dict[str, int] = {}
        print(f"{name}: {len(days)} day(s) to {days[-1] if days else '-'}", flush=True)
        for index, day in enumerate(days, start=1):
            outcome = fetch_one(fetcher, landing, report, day, now.date())
            counts[outcome] = counts.get(outcome, 0) + 1
            if index % 50 == 0:
                print(f"  {index}/{len(days)}  {counts}", flush=True)
        print(
            f"  done: {counts}  ('absent' is a holiday; 'not-yet' is retried next run)", flush=True
        )
        failed += counts.get("failed", 0) + counts.get("malformed", 0)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
