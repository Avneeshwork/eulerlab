"""`make crypto` — five years of minute bars for the top coins by volume.

Resumable in the way that matters: a symbol-month already on disk is skipped
without a request, so an interrupted run costs nothing to restart and a daily
re-run only fetches the newly published month.

The universe is written to `config/universe_crypto.txt` with its ranking date,
the same discipline `config/universe_top250.txt` follows. A universe file
without an `as_of` is a bias waiting to be reused on the wrong period.
"""

from __future__ import annotations

import argparse
import time
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from eulerlab.ingest import crypto


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backfill minute-level crypto history.")
    parser.add_argument("--coins", type=int, default=20, help="how many, by traded volume")
    parser.add_argument("--years", type=float, default=5.0)
    parser.add_argument("--pace", type=float, default=0.3, help="seconds between downloads")
    parser.add_argument("--verify", action="store_true", help="count candles against 1440/day")
    parser.add_argument(
        "--universe-only",
        action="store_true",
        help="resolve and write the coin list, fetch nothing",
    )
    args = parser.parse_args(argv)

    today = datetime.now(UTC).date()
    start = today - timedelta(days=int(args.years * 365.25))
    history_from = f"{start.year:04d}-{start.month:02d}"

    print("== universe ==")
    print(f"  ranking by Binance USDT volume, requiring history back to {history_from}")
    chosen = crypto.top_symbols(args.coins, history_from=history_from)
    if not chosen:
        print("  no symbols resolved — the ticker endpoint or the archive is unreachable")
        return 1

    for index, (base, pair, volume) in enumerate(chosen, start=1):
        print(f"  {index:>2}. {base:<8} {pair:<12} ${volume / 1e6:>9,.0f}M 24h")

    crypto.UNIVERSE_FILE.parent.mkdir(parents=True, exist_ok=True)
    crypto.UNIVERSE_FILE.write_text(
        "# Top crypto by Binance USDT quote volume, filtered to those with\n"
        f"# minute history back to {history_from}.\n"
        f"# as_of: {today.isoformat()}\n"
        f"# count: {len(chosen)}\n"
        "#\n"
        "# SURVIVORSHIP: these are the coins that survived to today with volume\n"
        "# today. The top twenty of 2021 included names now delisted, so a\n"
        "# backtest over this list is selected on hindsight (see ADR-008 for the\n"
        "# same argument in equities).\n" + "".join(f"{pair}\n" for _, pair, _ in chosen),
        encoding="utf-8",
    )
    print(f"  written to {crypto.UNIVERSE_FILE}")

    if args.universe_only:
        return 0

    months = crypto.months_between(start, today)
    pairs = [pair for _, pair, _ in chosen]
    print(f"\n== backfill ==\n  {len(pairs)} symbols x {len(months)} months")

    downloaded = skipped = missing = 0
    candles = 0
    began = time.time()
    # Pruned months are in the bucket, not on disk; without this every daily
    # run fetched and re-uploaded them (T-4391).
    landed = crypto.landed_names(crypto.LANDING)

    for index, pair in enumerate(pairs, start=1):
        got = 0
        for year_month in months:
            try:
                count, fetched = crypto.land_month(pair, year_month, landed=landed)
            except FileNotFoundError:
                # The archive has no such month: the symbol was not listed yet,
                # or the month has not been published. Neither is an error.
                missing += 1
                continue
            except Exception as exc:
                print(f"    {pair} {year_month} FAILED {type(exc).__name__}: {exc}")
                missing += 1
                continue

            if fetched:
                downloaded += 1
                candles += count
                got += count
                time.sleep(args.pace)
            else:
                skipped += 1

        elapsed = time.time() - began
        rate = index / elapsed if elapsed else 0
        left = (len(pairs) - index) / rate / 60 if rate else 0
        print(
            f"  [{index:>2}/{len(pairs)}] {pair:<12} +{got:>9,} candles  "
            f"({candles:,} total, ~{left:.0f} min left)"
        )

    print(f"\n{downloaded:,} months downloaded, {skipped:,} already landed, {missing:,} absent")
    print(f"{candles:,} new candles under {crypto.LANDING}")

    gap_from, gap_to = crypto.recent_gap()
    print(
        f"\nThe monthly archive does not cover {gap_from} to {gap_to} yet. Anything\n"
        f"reading 'up to today' is really reading up to the last month-end until\n"
        f"that window is filled from the REST API."
    )

    if args.verify:
        print("\n== verify (crypto trades 24/7, so 1,440 bars a day is exact) ==")
        incomplete = 0
        for pair in pairs:
            for year_month in months:
                check = crypto.verify_month(pair, year_month)
                if check.candles and not check.complete:
                    incomplete += 1
                    if incomplete <= 10:
                        print(
                            f"  {pair} {year_month}: {check.candles:,}/{check.expected:,} "
                            f"({check.missing:,} minutes absent)"
                        )
        print(f"  {incomplete:,} month(s) short of a full count")

    print("\nNothing is synced to B2 yet — run `make sync-cloud`.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
