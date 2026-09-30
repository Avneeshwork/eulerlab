"""Fill the crypto month-end gap from Binance's daily archive.

The monthly archive only appears once a month has ended, so on any day but the
first the landed corpus stops at the previous month-end. On 2026-08-24 that was
a twenty-four day hole that read as staleness and was really the shape of the
source — `crypto_backfill` had just downloaded 10.4 million candles and still
could not reach August.

Binance publishes the same data daily, on the same host, in the same format.
This lands those days beside the months; readers glob the folder and pick them
up without knowing the difference.
"""

from __future__ import annotations

import sys
from datetime import UTC, date, datetime

from eulerlab.ingest import crypto


def _main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    since: date | None = None
    for arg in args:
        if arg.startswith("--since="):
            try:
                since = date.fromisoformat(arg.split("=", 1)[1])
            except ValueError:
                print(f"bad --since: {arg}")
                return 2

    symbols = crypto.landed_symbols() if hasattr(crypto, "landed_symbols") else []
    if not symbols:
        from eulerlab.intraday import crypto_store

        symbols = crypto_store.symbols()
    if not symbols:
        print("no crypto symbols landed — run `make crypto` first")
        return 1

    start = since or datetime.now(UTC).date().replace(day=1)
    print(f"filling {len(symbols)} symbols from {start} to yesterday")
    days, candles, missing = crypto.fill_days(symbols, since=start)
    print(f"  landed  : {days} symbol-days, {candles:,} candles")
    if missing:
        # Named, not counted. A day Binance genuinely has not published looks
        # exactly like one that failed to download, and only the symbol tells
        # them apart.
        print(f"  missing : {len(missing)} (first few: {', '.join(missing[:5])})")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
