"""`make fx-bulk` - land FX minute bars for the top ten pairs, by the week.

Replaces the per-hour Dukascopy path for backfilling. That path measured 810
seconds per pair-day over a real run, which is 245 days for ten pairs across ten
years; this fetches a week at a time and finishes in an afternoon.

Resumable on the same principle: a day already on disk is never rewritten, so
stopping and restarting costs only the weeks in flight.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from eulerlab.ingest import fx, fx_bulk

WEEK_WORKERS = 8
"""Concurrent weekly fetches.

The Dukascopy lesson applies: the win is concurrency, and the ceiling is the
local resolver rather than the server. Eight is well under where DNS started
failing at twelve on the hourly path, and each request here is a hundred times
rarer.
"""


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pairs", default=",".join(fx.PAIRS))
    parser.add_argument("--from-year", type=int, default=fx_bulk.FIRST_YEAR)
    parser.add_argument("--to-year", type=int, default=0)
    args = parser.parse_args(argv)

    pairs = [p.strip().upper() for p in args.pairs.split(",") if p.strip()]
    last = args.to_year or datetime.now(UTC).year
    years = list(range(args.from_year, last + 1))
    jobs = [(p, y, w) for p in pairs for y in years for w in range(1, 54)]

    print(f"pairs : {len(pairs)} ({', '.join(pairs)})")
    print(f"years : {years[0]}..{years[-1]}")
    print(f"weeks : {len(jobs):,} requests at {WEEK_WORKERS} concurrent\n")

    landed = absent = existing = 0
    bars = 0
    done = 0

    def one(job: tuple[str, int, int]) -> tuple[int, int, bool]:
        pair, year, week = job
        try:
            return fx_bulk.land_week(pair, year, week)
        except Exception as exc:
            # One bad week must not end the run. Nothing was written for it, so
            # the next invocation retries it for free.
            print(f"  {pair} {year} wk{week}: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 0, 0, False

    with ThreadPoolExecutor(max_workers=WEEK_WORKERS) as pool:
        for days, wrote, had in pool.map(one, jobs):
            done += 1
            bars += wrote
            if had:
                existing += 1
            elif days:
                landed += days
            else:
                absent += 1
            if done % 200 == 0:
                print(f"  {done:>5}/{len(jobs)}  days={landed:,} bars={bars:,} absent={absent}")

    print(f"\ndone: {landed:,} days, {bars:,} bars, {existing} weeks already held, {absent} absent")
    for pair in pairs:
        print(f"  {pair}: {fx.landed_days(pair):,} days on disk")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
