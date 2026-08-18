"""`make ingest-oi` — backfill NSE participant-wise F&O open interest."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from eulerlab.ingest.fetch import Fetcher, FetchPolicy, UrllibTransport
from eulerlab.ingest.landing import Landing
from eulerlab.ingest.nse_eod import business_days, today_ist
from eulerlab.ingest.participant_oi import fetch_day

DEFAULT_LANDING = Path("data/landing/nse")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ingest-oi")
    parser.add_argument("--from", dest="start", type=date.fromisoformat, required=True)
    parser.add_argument("--to", dest="end", type=date.fromisoformat, default=today_ist())
    parser.add_argument("--landing", type=Path, default=DEFAULT_LANDING)
    parser.add_argument("--min-interval", type=float, default=1.0)
    args = parser.parse_args(argv)

    landing = Landing(args.landing)
    transport = UrllibTransport()
    transport.establish_session()
    fetcher = Fetcher(transport, FetchPolicy(min_interval_s=args.min_interval))

    counts: dict[str, int] = {}
    days = list(business_days(args.start, args.end))
    print(f"participant-wise OI: {args.start} .. {args.end}  ({len(days)} weekdays)")

    for index, day in enumerate(days, start=1):
        outcome = fetch_day(fetcher, landing, day)
        counts[outcome] = counts.get(outcome, 0) + 1
        if index % 100 == 0:
            done = counts.get("downloaded", 0) + counts.get("skipped", 0)
            print(f"  {index}/{len(days)}  landed={done}  absent={counts.get('absent', 0)}")

    print("\nsummary")
    for name in ("downloaded", "skipped", "absent", "failed", "malformed"):
        print(f"  {name:<11} {counts.get(name, 0)}")
    print("\n  'absent' is expected on market holidays.")
    if counts.get("malformed"):
        print("  'malformed' means the server returned something that was not the report.")
    return 1 if counts.get("failed") else 0


if __name__ == "__main__":
    raise SystemExit(main())
