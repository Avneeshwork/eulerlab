"""`make index-minute` — Kite 1-minute candles for the NSE indices themselves.

The stock minute archive (`kite_minute`) holds NIFTYBEES as a stand-in for
the Nifty, because its universe is equities. This job lands the index series:
NIFTY 50, NIFTY BANK and INDIA VIX. Kite lists them on NSE with instrument
type EQ in the INDICES segment, so `parse_instruments` already maps them.

An index has no traded volume: Kite's volume column is 0 for every candle.
Landing is append-only Parquet, one folder per index, under
`data/landing/kite_index_minute/`, and the manifest makes a re-run fetch only
sessions not yet held. Research 130.
"""

from __future__ import annotations

import argparse
import time
from collections.abc import Sequence
from datetime import date, timedelta
from pathlib import Path
from typing import Protocol

from eulerlab.env import load_env, require
from eulerlab.ingest.backfill_minute import last_complete_session
from eulerlab.ingest.kite_mcx_indices import _access_token
from eulerlab.ingest.kite_minute import (
    Chunk,
    KiteError,
    KiteHistorical,
    MinuteStore,
    candles_to_table,
    uncovered_chunks,
)
from eulerlab.ingest.nse_eod import weekend_sessions

LANDING_ROOT = Path("data/landing/kite_index_minute")
MIN_INTERVAL_S = 0.34
"""Kite allows 3 historical requests a second."""

# ASSUMPTION: A-076 - Kite lists these on NSE as instrument type EQ.
INDICES = {"NIFTY50": "NIFTY 50", "NIFTYBANK": "NIFTY BANK", "INDIAVIX": "INDIA VIX"}
"""Folder name -> Kite tradingsymbol. Folders carry no spaces, so B2 keys do not."""


class HistoricalClient(Protocol):
    def instruments(self, exchange: str = "NSE") -> dict[str, int]: ...

    def candles(self, chunk: Chunk, interval: str = "minute") -> list[list[object]]: ...


def backfill(
    client: HistoricalClient,
    store: MinuteStore,
    *,
    end: date,
    years: int,
    sleep_s: float = MIN_INTERVAL_S,
) -> dict[str, int]:
    tokens = client.instruments(exchange="NSE")
    start = end - timedelta(days=365 * years)
    held = store.covered()
    specials = weekend_sessions()
    totals = {"downloaded": 0, "rows": 0, "failed": 0, "missing": 0}
    for folder, kite_name in INDICES.items():
        token = tokens.get(kite_name)
        if token is None:
            totals["missing"] += 1
            print(f"{kite_name}: not in Kite's NSE instrument list")
            continue
        planned = list(
            uncovered_chunks(
                folder, token, start, end, held.get(folder, ()), weekend_sessions=specials
            )
        )
        print(f"{kite_name}: {start} .. {end}, {len(planned)} chunks to fetch")
        for chunk in planned:
            try:
                table = candles_to_table(client.candles(chunk))
            except KiteError as exc:
                totals["failed"] += 1
                print(f"  {chunk.start}..{chunk.end}: FAILED: {exc}")
                continue
            store.write(chunk, table)
            totals["downloaded"] += 1
            totals["rows"] += table.num_rows
            print(f"  {chunk.start}..{chunk.end}: {table.num_rows:,} candles")
            if sleep_s:
                time.sleep(sleep_s)
    return totals


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="index-minute")
    parser.add_argument("--years", type=int, default=1)
    parser.add_argument("--to", dest="end", type=date.fromisoformat, default=None)
    parser.add_argument("--root", type=Path, default=LANDING_ROOT)
    args = parser.parse_args(argv)
    if args.years < 1:
        parser.error("--years must be at least 1")
    load_env()
    try:
        client = KiteHistorical(require("ZERODHA_API_KEY"), _access_token())
        totals = backfill(
            client,
            MinuteStore(args.root),
            end=args.end or last_complete_session(),
            years=args.years,
        )
    except (KiteError, RuntimeError, SystemExit) as exc:
        print(f"index-minute: {exc}")
        return 1
    print(
        f"index minute bars: {totals['downloaded']} chunks, {totals['rows']:,} candles, "
        f"{totals['failed']} failed, {totals['missing']} index(es) not listed"
    )
    return 1 if totals["failed"] or totals["missing"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
