"""`make quality-options` — no-arbitrage checks over stored option chains.

Reads F&O bhavcopy from B2 at one download per day, against the 2,500/day cap
that has already stopped two builds. So the day count is explicit, it reports
what it intends to spend before spending it, and it stops cleanly when the cap
is reached rather than dumping a traceback.

Defaults to traded contracts only. NSE computes a settlement price for every
listed contract including strikes that never traded, so including them makes
the report a measurement of NSE's pricing model rather than of the market —
`--include-untraded` asks for that deliberately.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from eulerlab.options.arbitrage import check_calendar_monotonicity, run_chain_checks
from eulerlab.options.chain import build_chains, quotes_from_fo_bhavcopy
from eulerlab.paths import data_path
from eulerlab.quality.findings import Report, Severity

MANIFEST = data_path("landing/nse/manifest.jsonl")


def _fo_files(manifest: Path) -> list[tuple[str, str]]:
    """(trade_date, path) for every F&O bhavcopy, newest first."""
    if not manifest.exists():
        return []
    seen: dict[str, str] = {}
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("segment") == "fo":
            seen[str(row["trade_date"])] = str(row["path"])
    return sorted(seen.items(), reverse=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="quality-options", description=__doc__)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--days", type=int, default=5, help="how many recent F&O days to check")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument(
        "--include-untraded",
        action="store_true",
        help="also check contracts that never traded, whose price is NSE's model output",
    )
    parser.add_argument(
        "--underlying",
        default="",
        help="restrict to one underlying, e.g. NIFTY",
    )
    args = parser.parse_args(argv)

    chosen = _fo_files(args.manifest)[: args.days]
    if not chosen:
        print(f"no F&O files in {args.manifest} - nothing to check")
        return 0

    print(f"options quality: {len(chosen)} F&O bhavcopy files to download from B2")
    print("  (2,500 downloads/day free - see docs/RUNBOOKS/b2-transaction-cap.md)")

    import boto3

    from eulerlab.env import require

    client = boto3.client(
        "s3",
        endpoint_url="https://s3.us-west-004.backblazeb2.com",
        aws_access_key_id=require("B2_KEY_ID"),
        aws_secret_access_key=require("B2_APP_KEY"),
    )

    def fetch(item: tuple[str, str]) -> tuple[str, bytes]:
        trade_date, path = item
        return trade_date, client.get_object(Bucket="eulerdata", Key=f"nse/{path}")["Body"].read()

    report = Report()
    traded_only = not args.include_untraded
    chains_seen = fetched = 0
    note = ""

    try:
        with cf.ThreadPoolExecutor(max_workers=8) as pool:
            for trade_date, payload in pool.map(fetch, chosen):
                day = date.fromisoformat(trade_date)
                quotes = list(quotes_from_fo_bhavcopy(payload))
                chains = build_chains(quotes, day)
                if args.underlying:
                    chains = [c for c in chains if c.underlying == args.underlying]
                for chain in chains:
                    report.extend(run_chain_checks(chain, traded_only=traded_only))
                report.extend(check_calendar_monotonicity(chains, traded_only=traded_only))
                chains_seen += len(chains)
                fetched += 1
    except Exception as exc:
        if "cap exceeded" not in str(exc).lower():
            raise
        note = (
            f"stopped after {fetched} of {len(chosen)} days: B2 daily download cap "
            f"reached. See docs/RUNBOOKS/b2-transaction-cap.md"
        )

    mode = "traded contracts only" if traded_only else "including untraded (NSE model prices)"
    print(f"  {fetched} days, {chains_seen:,} chains, {mode}")
    print(report.render(limit=args.limit))
    if note:
        print(f"\nincomplete: {note}")
    return 1 if report.count(Severity.ERROR) else 0


if __name__ == "__main__":
    raise SystemExit(main())
