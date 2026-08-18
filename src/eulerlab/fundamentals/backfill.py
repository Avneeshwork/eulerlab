"""`make ingest-fundamentals` — fetch screener.in fundamentals for a universe.

Re-runnable by design. A company already fetched *today* is skipped, so running
this daily costs nothing for names already done and picks up only what is new
or stale. That is what makes it safe to schedule (see `make daily`).
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from eulerlab.fundamentals.screener_fetch import (
    FundamentalsStore,
    RefusedError,
    ScreenerClient,
    ScreenerError,
)
from eulerlab.ingest.kite_minute import read_universe

DEFAULT_ROOT = Path("data/landing/fundamentals")
DEFAULT_UNIVERSE = Path("config/universe_all_liquid.txt")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ingest-fundamentals")
    parser.add_argument("--universe", type=Path, default=DEFAULT_UNIVERSE)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--min-interval", type=float, default=2.5)
    parser.add_argument(
        "--refresh-days",
        type=int,
        default=1,
        help="re-fetch a company only if its last snapshot is older than this",
    )
    args = parser.parse_args(argv)

    symbols = read_universe(args.universe)
    if args.limit:
        symbols = symbols[: args.limit]

    today = datetime.now(UTC).date().isoformat()
    store = FundamentalsStore(args.root)
    client = ScreenerClient(min_interval_s=args.min_interval)

    print(f"universe : {args.universe} ({len(symbols)} symbols)")
    print(f"target   : {args.root}")
    print(
        f"estimate : {len(symbols) * args.min_interval / 60:.0f} min at {args.min_interval}s/req\n"
    )

    fetched = skipped = failed = empty = 0
    for index, symbol in enumerate(symbols, start=1):
        if store.has(symbol, today):
            skipped += 1
            continue
        try:
            result = client.fetch(symbol)
        except RefusedError as exc:
            # Being refused is a stop signal, not something to retry around.
            print(f"\nSTOPPING at {symbol}: {exc}")
            print(f"  progress: {fetched} fetched, {failed} failed")
            return 2
        except ScreenerError as exc:
            failed += 1
            print(f"  {symbol}: {exc}")
            continue
        except Exception as exc:
            failed += 1
            print(f"  {symbol}: unexpected {type(exc).__name__}: {exc}")
            continue

        if not result.cells:
            empty += 1
            continue

        store.write(result, today)
        fetched += 1
        if index % 25 == 0:
            print(f"  {index}/{len(symbols)}  fetched={fetched} skipped={skipped} failed={failed}")

    print(f"\ndone: {fetched} fetched, {skipped} already current, {empty} no data, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
