"""`make check-crypto` — is the Binance archive worth trusting?

Two questions, answered separately because they fail differently.

**Does it agree with an independent venue?** Compares landed closes against
Coinbase for the same minutes. Needs the `crypto` extra (`ccxt`) and a network.

**Is it internally coherent?** OHLC bounds, monotonic time, positive prices,
and the 1,440-a-day count crypto uniquely permits. Needs neither network nor
second source, so it runs anywhere and covers symbols no other venue lists.

A gap shared across symbols at identical timestamps is an **exchange outage**,
not data loss, and the report says which it found rather than counting both as
"missing".
"""

from __future__ import annotations

import argparse
import gzip
import json
from collections.abc import Sequence
from datetime import datetime

from eulerlab.ingest import crypto
from eulerlab.quality import crypto_reconcile as reconcile


def _landed() -> tuple[list[str], list[str]]:
    root = crypto.LANDING
    if not root.exists():
        return [], []
    symbols = sorted(p.name for p in root.iterdir() if p.is_dir())
    months = sorted(
        {p.name.split("-1m-")[1].replace(".jsonl.gz", "") for p in root.glob("*/*.jsonl.gz")}
    )
    return symbols, months


def missing_minutes(symbol: str, year_month: str) -> set[datetime]:
    """Exactly which minutes are absent, not merely how many."""
    from datetime import UTC, timedelta

    path = crypto.month_path(symbol, year_month)
    if not path.exists():
        return set()
    have: set[datetime] = set()
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                have.add(datetime.fromisoformat(json.loads(line)["event_time"]))

    year, month = (int(part) for part in year_month.split("-"))
    cursor = datetime(year, month, 1, tzinfo=UTC)
    end = datetime(year + (month == 12), (month % 12) + 1, 1, tzinfo=UTC)
    want: set[datetime] = set()
    while cursor < end:
        want.add(cursor)
        cursor += timedelta(minutes=1)
    return want - have


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check the crypto archive.")
    parser.add_argument("--no-cross", action="store_true", help="skip the Coinbase comparison")
    parser.add_argument("--symbols", type=int, default=4, help="how many to cross-check")
    args = parser.parse_args(argv)

    symbols, months = _landed()
    if not symbols:
        print("nothing landed under data/landing/crypto — run `make crypto`")
        return 1
    print(f"landed: {len(symbols)} symbols x {len(months)} months\n")

    # --- 1. internal coherence -------------------------------------------
    print("== internal checks (no network, no second source) ==")
    violations = 0
    short_months: list[tuple[str, str, int]] = []
    for symbol in symbols:
        for year_month in months:
            problems = [
                p for p in reconcile.sanity_checks(symbol, year_month) if "not landed" not in p
            ]
            for problem in problems:
                if "minutes absent" in problem:
                    check = crypto.verify_month(symbol, year_month)
                    short_months.append((symbol, year_month, check.missing))
                else:
                    violations += 1
                    if violations <= 10:
                        print(f"  {symbol} {year_month}: {problem}")
    print(f"  OHLC / ordering / positivity violations: {violations}")

    # Stale feeds and bad prints — the two failures a bounds check cannot see.
    stale = corroborated = isolated = 0
    isolated_examples: list[str] = []
    for symbol in symbols:
        for year_month in months:
            if not crypto.is_readable(symbol, year_month):
                continue
            stale += len(reconcile.stale_runs(symbol, year_month))
            for finding in reconcile.extreme_moves(symbol, year_month):
                if finding.kind == "extreme-corroborated":
                    corroborated += 1
                else:
                    isolated += 1
                    if len(isolated_examples) < 5:
                        isolated_examples.append(f"{symbol} {finding.at}: {finding.detail}")

    print(f"  stale runs (>=30 identical closes):       {stale}")
    print(f"  large moves corroborated by volume:       {corroborated}")
    print(f"  large moves with NO volume (bad prints?): {isolated}")
    for example in isolated_examples:
        print(f"      {example}")

    # --- 2. are the gaps shared? -----------------------------------------
    print(f"\n== gaps ({len(short_months)} symbol-months are short) ==")
    by_month: dict[str, list[str]] = {}
    for symbol, year_month, _ in short_months:
        by_month.setdefault(year_month, []).append(symbol)

    for year_month, affected in sorted(by_month.items()):
        if len(affected) < 2:
            print(f"  {year_month}: only {affected[0]} — symbol-specific, NOT an outage")
            continue
        first, second = affected[0], affected[1]
        shared = missing_minutes(first, year_month) & missing_minutes(second, year_month)
        one = missing_minutes(first, year_month)
        verdict = (
            "exchange outage (identical across symbols)"
            if shared == one
            else f"partially shared ({len(shared)}/{len(one)})"
        )
        gaps = sorted(one)
        window = f"{gaps[0]:%Y-%m-%d %H:%M} to {gaps[-1]:%H:%M} UTC" if gaps else ""
        print(f"  {year_month}: {len(affected)} symbols, {len(one):,} min — {verdict}")
        if window:
            print(f"      {window}")

    # --- 3. cross-source --------------------------------------------------
    if args.no_cross:
        print("\n(cross-source comparison skipped)")
        return 0

    print(f"\n== cross-source vs {reconcile.REFERENCE_EXCHANGE} ==")
    try:
        import ccxt
    except ImportError:
        print("  ccxt is not installed. `uv sync --extra crypto` to enable this check.")
        return 0

    exchange = ccxt.coinbase({"enableRateLimit": True})
    month = months[len(months) // 2] if months else ""
    disagreements = 0
    for symbol in symbols[: args.symbols]:
        result = reconcile.compare(symbol, month, exchange, samples=3, per_sample=60)
        if not result.usable:
            print(f"  {symbol:<10} {month}  unusable: {result.note}")
            continue
        flag = "" if result.agrees else "   <-- DISAGREES"
        disagreements += 0 if result.agrees else 1
        print(
            f"  {symbol:<10} {month}  n={result.compared:>4}  median "
            f"{result.median_diff_pct:.4f}%  p95 {result.p95_diff_pct:.4f}%{flag}"
        )

    print(
        "\nTwo venues never agree exactly — Binance quotes USDT, Coinbase quotes USD,\n"
        "and a minute bar samples a continuous process. Under 0.5% median is\n"
        "microstructure; this project's own equity vendor comparison sits at 0.181%."
    )
    return 1 if (violations or disagreements or isolated) else 0


if __name__ == "__main__":
    raise SystemExit(main())
