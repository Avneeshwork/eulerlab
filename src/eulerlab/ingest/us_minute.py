"""Backfill US minute bars without filling the disk.

Sized before it was written. One symbol-month is about 8,900 bars and 1 MB of
raw JSON, so a symbol-year is roughly 2 MB gzipped and the whole S&P 500 across
the window this feed serves is about **3 GB** — against 4 GB of free disk when
this was written. Landing it all and syncing afterwards would run out partway
through and leave a half-archive with no record of where it stopped.

So the loop is fetch → sync → prune, a batch at a time. Each batch is uploaded
and its local copy released before the next is fetched, which keeps the local
footprint at roughly one batch regardless of how many batches there are. The
bucket is the store of record; the disk is scratch.

A batch that fails to sync is **not** pruned. Pruning verifies against the
bucket first, so an upload failure leaves the bytes on disk rather than losing
them — the one ordering that makes the whole loop safe to interrupt.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from collections.abc import Sequence

from eulerlab.ingest import alpaca

BATCH = 25
"""Symbols per fetch-sync-prune cycle. Small enough that one cycle's local
footprint is tens of megabytes, large enough that the sync's per-run overhead
is not most of the work."""


def _run(command: list[str]) -> tuple[bool, str]:
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=3600)
    except subprocess.TimeoutExpired:
        return False, "timed out"
    return done.returncode == 0, (done.stderr or done.stdout)[-200:]


def backfill(
    symbols: Sequence[str],
    *,
    start: str = alpaca.MINUTE_FIRST,
    batch: int = BATCH,
    sync: bool = True,
) -> int:
    """Fetch minute bars in batches, syncing and pruning between them."""
    total_new = 0
    began = time.time()
    for index in range(0, len(symbols), batch):
        group = list(symbols[index : index + batch])
        written, new, error = alpaca.land_minute(group, start=start)
        total_new += new
        done = index + len(group)
        print(
            f"  [{done:>3}/{len(symbols)}] {written:>3} symbols, {new:>9,} bars"
            f"{'  ' + error if error else ''}",
            flush=True,
        )
        if error:
            print("  stopping: the feed returned an error", flush=True)
            break

        if not sync:
            continue

        ok, note = _run([sys.executable, "-m", "eulerlab.ingest.sync_cloud"])
        if not ok:
            # Not pruned. The bytes stay on disk until they are safely in the
            # bucket, because a prune after a failed upload is data loss.
            print(f"  sync failed, keeping local copy: {note.strip()[:120]}", flush=True)
            continue
        _run([sys.executable, "-m", "eulerlab.ingest.prune_local"])

    print(f"done: {total_new:,} bars in {time.time() - began:.0f}s")
    return total_new


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="us-minute")
    parser.add_argument("--start", default=alpaca.MINUTE_FIRST)
    parser.add_argument("--limit", type=int, default=0, help="first N symbols only")
    parser.add_argument("--batch", type=int, default=BATCH)
    parser.add_argument("--no-sync", action="store_true")
    args = parser.parse_args(argv)

    symbols = alpaca.sp500_symbols()
    if not symbols:
        print("no S&P 500 snapshot landed — run `make us-sp500` first")
        return 1
    if args.limit:
        symbols = symbols[: args.limit]

    print(f"US minute bars: {len(symbols)} symbols from {args.start}, batches of {args.batch}")
    backfill(symbols, start=args.start, batch=args.batch, sync=not args.no_sync)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
