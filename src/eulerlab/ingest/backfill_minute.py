"""`make ingest-minute` — backfill 1-minute candles for a universe."""

from __future__ import annotations

import argparse
import json
import os
import time
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from eulerlab.env import load_env, require
from eulerlab.ingest.kite_minute import (
    Chunk,
    KiteError,
    KiteHistorical,
    MinuteStore,
    candles_to_table,
    read_universe,
    uncovered_chunks,
)
from eulerlab.ingest.nse_eod import weekend_sessions

DEFAULT_ROOT = Path("data/landing/kite_minute")
DEFAULT_UNIVERSE = Path("config/universe_top250_union.txt")
SESSION_FILE = Path(".kite_session.json")

MIN_INTERVAL_S = 0.34
"""Kite allows 3 requests/second for historical data. Sit just under it."""


def last_complete_session(now: datetime | None = None) -> date:
    """Today from 15:31 IST, otherwise yesterday.

    Was 15:45, because a chunk ending on a day still trading holds half a
    session and its landed key meant the rest of that day was never fetched.
    `complete_days` now refuses to land today until its last candle is in, so
    the cut-off can sit one minute after the close (ADR-079).
    """
    ist = (now or datetime.now(UTC)).astimezone(ZoneInfo("Asia/Kolkata"))
    closed = (ist.hour, ist.minute) >= (15, 31)
    return ist.date() if closed else ist.date() - timedelta(days=1)


def complete_days(
    chunk: Chunk, candles: list[list[object]], today: date
) -> tuple[Chunk | None, list[list[object]]]:
    """Drop today from a chunk until today's session is complete.

    Complete means a candle at the session's last minute: 15:29, or 15:14 for
    an F&O stock, whose continuous trading ends at 15:15 for the closing
    auction (`provisional_daily.session_ends`, HISTORY #29). Only today is
    checked: an older day is landed as Kite serves it, since refetching it
    would never change it. Returns (None, []) when nothing is left to land.
    """
    from eulerlab.ingest.provisional_daily import session_ends

    if chunk.end != today:
        return chunk, candles
    stamp = today.isoformat()
    todays = sorted(str(c[0]) for c in candles if str(c[0]).startswith(stamp))
    if todays and todays[-1][11:16] in session_ends(today):
        return chunk, candles
    if chunk.start >= today:
        return None, []
    kept = [c for c in candles if not str(c[0]).startswith(stamp)]
    return replace(chunk, end=today - timedelta(days=1)), kept


def _access_token() -> str:
    if SESSION_FILE.exists():
        token = json.loads(SESSION_FILE.read_text(encoding="utf-8")).get("access_token")
        if isinstance(token, str) and token:
            return token
    load_env()
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

    end = args.end or last_complete_session()
    start = end - timedelta(days=365 * args.years)

    symbols = read_universe(args.universe)
    if args.limit:
        symbols = symbols[: args.limit]

    client = KiteHistorical(require("ZERODHA_API_KEY"), _access_token())
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

    # Planned from what each symbol already holds, not from a window whose
    # start moves every day: that re-fetched the whole year on every run
    # (T-4036). `has` still guards a key landed by an older, shifted window.
    held = store.covered()
    specials = weekend_sessions()
    planned: list[Chunk] = [
        chunk
        for symbol, token in resolved.items()
        for chunk in uncovered_chunks(
            symbol, token, start, end, held.get(symbol, ()), weekend_sessions=specials
        )
    ]
    todo = [c for c in planned if not store.has(c)]
    current = sum(1 for symbol in resolved if not any(c.symbol == symbol for c in planned))
    print(
        f"chunks     : {len(todo)} to fetch ({current} of {len(resolved)} symbols already current)"
    )
    print(f"estimate   : {len(todo) * MIN_INTERVAL_S / 60:.0f} min at 3 req/s\n")

    fetched = rows = failed = unfinished = 0
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

        landing, candles = complete_days(chunk, candles, end)
        if landing is None:
            unfinished += 1
            continue
        table = candles_to_table(candles)
        store.write(landing, table)
        fetched += 1
        rows += table.num_rows
        if index % 200 == 0:
            print(f"  {index}/{len(todo)} chunks, {rows:,} bars, {failed} failed")

    print(f"\ndone: {fetched} chunks, {rows:,} bars, {failed} failed")
    if unfinished:
        print(f"{unfinished} symbol(s) not complete today; fetched again next run")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
