"""`make mf-ingest` — land the AMFI snapshot, then backfill NAV history.

Order matters. The snapshot is one request and gives the full universe, so it
runs first and is always current even if the backfill is interrupted. The
backfill is ~14,000 requests and is the part that takes hours, so everything
about it is built to survive being stopped: it skips what is already landed,
paces itself, and reports what it did rather than what it attempted.

Direct-growth schemes are fetched first. Not a filter — every scheme is
eventually landed — but the ordering means the subset actually worth analysing
is complete early, so an interrupted run is still useful.
"""

from __future__ import annotations

import argparse
import time
from collections.abc import Sequence
from datetime import date

from eulerlab.ingest import amfi


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest mutual fund NAVs.")
    parser.add_argument("--snapshot-only", action="store_true", help="skip the history backfill")
    parser.add_argument("--limit", type=int, default=0, help="stop after N schemes (0 = all)")
    parser.add_argument(
        "--direct-growth-only",
        action="store_true",
        help="only the direct-plan growth-option variants",
    )
    parser.add_argument(
        "--pace",
        type=float,
        default=0.25,
        help="seconds between history requests; mfapi.in is a free community mirror",
    )
    args = parser.parse_args(argv)

    print("== AMFI snapshot ==")
    path, written = amfi.land_snapshot()
    if written:
        print(f"  landed {written:,} schemes -> {path}")
    else:
        print(f"  {path} already exists; the landing zone is immutable, nothing rewritten")

    schemes = amfi.fetch_universe()
    nav_date = max(s.nav_date for s in schemes)
    direct = [s for s in schemes if s.is_direct_growth]
    print(f"  {len(schemes):,} schemes, NAV date {nav_date}, {len(direct):,} direct-growth")

    if args.snapshot_only:
        return 0

    # Direct-growth first so an interrupted run still leaves the analysable
    # subset complete.
    ordered = direct + [s for s in schemes if not s.is_direct_growth]
    if args.limit:
        ordered = ordered[: args.limit]

    print(f"\n== NAV history backfill ({len(ordered):,} schemes) ==")
    fetched = skipped = failed = rows = 0
    started = time.time()

    for index, scheme in enumerate(ordered, start=1):
        through = amfi.landed_through(scheme.scheme_code)
        if through is not None and through >= nav_date:
            skipped += 1
        else:
            try:
                written_rows = amfi.land_history(scheme.scheme_code)
            except Exception as exc:
                failed += 1
                print(f"  [{index}/{len(ordered)}] {scheme.scheme_code} FAILED {exc}")
            else:
                fetched += 1
                rows += written_rows
            time.sleep(args.pace)

        if index % 250 == 0 or index == len(ordered):
            elapsed = time.time() - started
            rate = index / elapsed if elapsed else 0
            remaining = (len(ordered) - index) / rate if rate else 0
            print(
                f"  [{index:>6}/{len(ordered)}] fetched {fetched:,} skipped {skipped:,} "
                f"failed {failed:,} rows {rows:,} — {remaining / 60:.0f} min left"
            )

    print(f"\n{fetched:,} fetched, {skipped:,} already current, {failed:,} failed")
    print(f"{rows:,} NAV rows landed under {amfi.HISTORY_DIR}")
    print(
        "\nRe-running costs nothing: a scheme already current is skipped without a "
        "request. Nothing here is synced to B2 yet — run `make sync-cloud`."
    )
    return 0 if failed < len(ordered) else 1


def coverage() -> dict[str, object]:
    """What is on disk, for the daily report."""
    snapshots = sorted(amfi.SNAPSHOT_DIR.glob("*.jsonl.gz")) if amfi.SNAPSHOT_DIR.exists() else []
    histories = list(amfi.HISTORY_DIR.glob("*.jsonl.gz")) if amfi.HISTORY_DIR.exists() else []
    newest: date | None = None
    if snapshots:
        newest = date.fromisoformat(snapshots[-1].stem.replace(".jsonl", ""))
    return {
        "snapshots": len(snapshots),
        "newest_snapshot": newest.isoformat() if newest else None,
        "schemes_with_history": len(histories),
        "bytes": sum(p.stat().st_size for p in [*snapshots, *histories]),
    }


if __name__ == "__main__":
    raise SystemExit(main())
