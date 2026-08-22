"""`make fx` - land FX minute bars for the top ten pairs.

Resumable by construction: a day already on disk costs zero requests, so this
can be stopped and restarted freely and picks up where it left off. That is not
a convenience, it is the only way a backfill of this size is possible at all.

**The size is the point.** Ten pairs across ten years is roughly 26,000
pair-days and 624,000 hourly requests. At the pace the feed tolerates that is
days of wall-clock time, not minutes. The default is therefore one year, and
reaching ten is a matter of running it repeatedly rather than one heroic
invocation - which is also the only shape that survives a laptop closing.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta

from eulerlab.ingest import fx


def days_between(start: date, end: date) -> list[date]:
    """Weekdays only. FX is closed over the weekend and the feed has no files
    for it, so fetching them is 48 wasted requests per pair-week."""
    out: list[date] = []
    cursor = start
    while cursor <= end:
        if cursor.weekday() < 5:
            out.append(cursor)
        cursor += timedelta(days=1)
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pairs", default=",".join(fx.PAIRS))
    parser.add_argument("--years", type=float, default=1.0)
    parser.add_argument("--to", dest="end", type=date.fromisoformat, default=None)
    parser.add_argument("--pace", type=float, default=0.0, help="extra delay per request")
    parser.add_argument("--limit", type=int, default=0, help="stop after N pair-days")
    args = parser.parse_args(argv)

    pairs = [p.strip().upper() for p in args.pairs.split(",") if p.strip()]
    end = args.end or datetime.now(UTC).date()
    start = end - timedelta(days=int(args.years * 365.25))
    wanted = days_between(start, end)

    total = len(pairs) * len(wanted)
    print(f"pairs   : {len(pairs)} ({', '.join(pairs)})")
    print(f"range   : {start} .. {end}  ({len(wanted)} weekdays)")
    print(f"pair-days: {total:,}")
    per_day = 24 / fx.HOUR_WORKERS * (10.0 + args.pace)
    print(
        f"estimate : {total * per_day / 3600:.1f} h at {fx.HOUR_WORKERS} concurrent connections\n"
    )

    landed = skipped = empty = 0
    bars = 0
    done = 0
    for pair in pairs:
        for day in wanted:
            if args.limit and done >= args.limit:
                break
            try:
                count, had = fx.land_day(pair, day, pace=args.pace)
            except Exception as exc:
                # One bad day must not end a multi-hour backfill; the next run
                # picks it up because nothing was written for it.
                print(f"  {pair} {day}: {type(exc).__name__}: {exc}", file=sys.stderr)
                continue
            done += 1
            if had:
                skipped += 1
            elif count:
                landed += 1
                bars += count
            else:
                empty += 1
            if done % 25 == 0:
                print(f"  {done:>6}/{total}  landed={landed} skipped={skipped} bars={bars:,}")

    print(f"\ndone: {landed} days landed, {skipped} already had, {empty} empty, {bars:,} bars")
    for pair in pairs:
        print(f"  {pair}: {fx.landed_days(pair)} days on disk")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
