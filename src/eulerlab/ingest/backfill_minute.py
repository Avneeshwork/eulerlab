"""`make ingest-minute` — backfill 1-minute candles for a universe."""

from __future__ import annotations

import argparse
import json
import os
import time
from collections.abc import Sequence
from datetime import date, timedelta
from pathlib import Path

from eulerlab.ingest.kite_minute import (
    Chunk,
    KiteError,
    KiteHistorical,
    MinuteStore,
    candles_to_table,
    chunks_for,
    read_universe,
)

DEFAULT_ROOT = Path("data/landing/kite_minute")
DEFAULT_UNIVERSE = Path("config/universe_top250_union.txt")
SESSION_FILE = Path(".kite_session.json")

MIN_INTERVAL_S = 0.34
"""Kite allows 3 requests/second for historical data. Sit just under it."""


def _access_token() -> str:
    if SESSION_FILE.exists():
        token = json.loads(SESSION_FILE.read_text(encoding="utf-8")).get("access_token")
        if isinstance(token, str) and token:
            return token
    env = os.environ.get("ZERODHA_ACCESS_TOKEN", "").strip()
    if env:
        return env
    print("No access token. Run `make kite-login` first.")
    raise SystemExit(2)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ingest-minute",
        description="Backfill 1-minute candles from Kite into the landing zone.",
    )
    parser.add_argument("--universe", type=Path, default=DEFAULT_UNIVERSE)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--years", type=int, default=5)
    parser.add_argument("--to", dest="end", type=date.fromisoformat, default=None)
    parser.add_argument("--limit", type=int, default=0, help="stop after N symbols (for testing)")
    args = parser.parse_args(argv)

    end = args.end or date.today()  # noqa: DTZ011 - a bar range, not a trading-day decision
    start = end - timedelta(days=365 * args.years)

    symbols = read_universe(args.universe)
    if args.limit:
        symbols = symbols[: args.limit]

    client = KiteHistorical(os.environ["ZERODHA_API_KEY"], _access_token())
    store = MinuteStore(args.root)

    print(f"universe   : {args.universe} ({len(symbols)} symbols)")
    print(f"range      : {start} .. {end}")
    print("resolving instrument tokens...")
    try:
        tokens = client.instruments()
    except KiteError as exc:
        print(f"could not fetch the instrument list: {exc}")
        return 1

    resolved = {s: tokens[s] for s in symbols if s in tokens}
    missing = [s for s in symbols if s not in tokens]
    for symbol in missing:
        store.mark_unresolvable(symbol, "not in Kite's current instrument list")
    print(f"resolved   : {len(resolved)}/{len(symbols)}  (missing {len(missing)} — logged)")

    planned: list[Chunk] = [
        chunk
        for symbol, token in resolved.items()
        for chunk in chunks_for(symbol, token, start, end)
    ]
    todo = [c for c in planned if not store.has(c)]
    print(f"chunks     : {len(planned)} total, {len(todo)} to fetch")
    print(f"estimate   : {len(todo) * MIN_INTERVAL_S / 60:.0f} min at 3 req/s\n")

    fetched = rows = failed = 0
    last = 0.0
    for index, chunk in enumerate(todo, start=1):
        gap = MIN_INTERVAL_S - (time.monotonic() - last)
        if gap > 0:
            time.sleep(gap)
        last = time.monotonic()
        try:
            candles = client.candles(chunk)
        except KiteError as exc:
            failed += 1
            store.mark_unresolvable(chunk.symbol, f"{chunk.start}: {exc}")
            continue
        except Exception as exc:  # nothing unforeseen may abort a multi-hour run
            failed += 1
            store.mark_unresolvable(
                chunk.symbol, f"{chunk.start}: unexpected {type(exc).__name__}: {exc}"
            )
            continue

        table = candles_to_table(candles)
        store.write(chunk, table)
        fetched += 1
        rows += table.num_rows
        if index % 200 == 0:
            print(f"  {index}/{len(todo)} chunks, {rows:,} bars, {failed} failed")

    print(f"\ndone: {fetched} chunks, {rows:,} bars, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
