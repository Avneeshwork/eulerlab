"""`make ingest-nse-daily` — two daily NSE files the platform did not hold.

- **`indices`** — `ind_close_all_DDMMYYYY.csv`: open, high, low and close of
  every NSE index that day, with volume, turnover, P/E, P/B and dividend
  yield. About 60 indices in 2016 and more since: the sectoral indices,
  Midcap and Smallcap, and India VIX. One ~8 KB file a day.
- **`delivery`** — `MTO_DDMMYYYY.DAT`: per security, the traded quantity, the
  deliverable quantity and delivery as a percent of traded.

Both are landed raw and unedited, like every other source (`ingest/landing`),
through the same rate-limited `Fetcher` and append-only manifest, so a backfill
is resumable and a re-run downloads nothing it already has. Research note 065
records where each was found and what it unlocks.
"""

from __future__ import annotations

import argparse
import csv
import io
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from eulerlab.ingest.fetch import Fetcher, FetchPolicy, Outcome, UrllibTransport
from eulerlab.ingest.landing import Landing
from eulerlab.ingest.nse_eod import session_days, today_ist
from eulerlab.paths import data_path

DEFAULT_LANDING = data_path("landing/nse")


def _ddmmyyyy(day: date) -> str:
    return f"{day.day:02d}{day.month:02d}{day.year:04d}"


@dataclass(frozen=True)
class DailyFile:
    segment: str
    url: Callable[[date], str]
    suffix: str
    check: Callable[[bytes], int | None]
    """Rows in the file when it is the report asked for, else None. A page that
    parses but is not the report must not be landed."""


def _index_rows(payload: bytes) -> int | None:
    text = payload.decode("utf-8", errors="replace")
    if not text.lstrip().startswith("Index Name"):
        return None
    rows = list(csv.DictReader(io.StringIO(text)))
    names = {(r.get("Index Name") or "").strip() for r in rows}
    # "CNX Nifty" until NSE renamed its indices in late 2015.
    return len(rows) if names & {"Nifty 50", "CNX Nifty"} else None


def _delivery_rows(payload: bytes) -> int | None:
    text = payload.decode("utf-8", errors="replace")
    if "Security Wise Delivery Position" not in text[:200]:
        return None
    count = sum(1 for line in text.splitlines() if line.startswith("20,"))
    return count or None


FILES: dict[str, DailyFile] = {
    "indices": DailyFile(
        "indices",
        lambda d: (
            f"https://nsearchives.nseindia.com/content/indices/ind_close_all_{_ddmmyyyy(d)}.csv"
        ),
        "csv",
        _index_rows,
    ),
    "delivery": DailyFile(
        "delivery",
        lambda d: f"https://nsearchives.nseindia.com/archives/equities/mto/MTO_{_ddmmyyyy(d)}.DAT",
        "dat",
        _delivery_rows,
    ),
}


def fetch_day(fetcher: Fetcher, landing: Landing, spec: DailyFile, trade_date: date) -> str:
    """Returns one of: downloaded, skipped, absent, failed, malformed."""
    if landing.has(trade_date, spec.segment):
        return "skipped"
    url = spec.url(trade_date)
    result = fetcher.get(url)
    if result.outcome is Outcome.ABSENT:
        return "absent"
    if result.outcome is Outcome.FAILED or result.payload is None:
        return "failed"
    rows = spec.check(result.payload)
    if rows is None:
        return "malformed"
    landing.write(
        trade_date=trade_date,
        segment=spec.segment,
        file_format=spec.suffix,
        url=url,
        payload=result.payload,
        rows=rows,
        inner_name=url.rsplit("/", 1)[-1],
        suffix=spec.suffix,
    )
    return "downloaded"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ingest-nse-daily")
    parser.add_argument("--from", dest="start", type=date.fromisoformat, required=True)
    parser.add_argument("--to", dest="end", type=date.fromisoformat, default=today_ist())
    parser.add_argument("--only", choices=sorted(FILES), default=None)
    parser.add_argument("--landing", type=Path, default=DEFAULT_LANDING)
    parser.add_argument("--min-interval", type=float, default=0.5)
    args = parser.parse_args(argv)

    landing = Landing(args.landing)
    transport = UrllibTransport()
    transport.establish_session()
    fetcher = Fetcher(transport, FetchPolicy(min_interval_s=args.min_interval))
    specs = [FILES[args.only]] if args.only else list(FILES.values())
    days = session_days(args.start, args.end, args.landing)
    failed = 0
    for spec in specs:
        counts: dict[str, int] = {}
        print(f"{spec.segment}: {args.start} .. {args.end} ({len(days)} sessions)", flush=True)
        for index, day in enumerate(days, start=1):
            outcome = fetch_day(fetcher, landing, spec, day)
            counts[outcome] = counts.get(outcome, 0) + 1
            if index % 200 == 0:
                print(f"  {index}/{len(days)}  {counts}", flush=True)
        print(f"  done: {counts}  ('absent' is expected on holidays)", flush=True)
        failed += counts.get("failed", 0)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
