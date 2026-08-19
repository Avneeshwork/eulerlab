"""`make quality` — run every check and print counts by severity.

Ordered so the free work happens first. Manifest checks read local files and
cost nothing. Row checks need price data from B2 at one transaction per file,
against a 2,500/day cap that has already stopped one build outright, so they
are opt-in via `--rows N`, they say how much of the budget they intend to
spend before spending it, and they stop cleanly when the cap is reached rather
than dumping a boto traceback.

Exit code is 1 only for ERROR findings. Warnings are for the operator to read,
not for CI to block on — a check that blocks the build on a 12% price move
teaches everyone to bypass the build.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

from eulerlab.corp_actions.build_factors import load_actions
from eulerlab.quality.findings import Finding, Report, Severity
from eulerlab.quality.manifest_checks import LANDING_ROOT, run_manifest_checks
from eulerlab.quality.row_checks import Bar, run_row_checks
from eulerlab.quality.sources import bars_from_bhavcopy

NSE_MANIFEST = Path("data/landing/nse/manifest.jsonl")


def _cash_files(manifest: Path) -> list[tuple[str, str]]:
    """(trade_date, path) for every cash bhavcopy, newest first."""
    if not manifest.exists():
        return []
    rows = [
        json.loads(line)
        for line in manifest.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    seen: dict[str, str] = {}
    for row in rows:
        if row.get("segment") == "cm":
            seen[str(row["trade_date"])] = str(row["path"])
    return sorted(seen.items(), reverse=True)


def _load_bars(paths: Sequence[tuple[str, str]], *, workers: int = 8) -> tuple[list[Bar], str]:
    """Fetch and parse bhavcopy files from B2. Returns (bars, note).

    `note` is empty on success, or an explanation when the run stopped early.
    Stopping early is normal here, not a failure: the cap is shared with
    `make build-factors` and whichever runs second gets less of it.
    """
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

    bars: list[Bar] = []
    fetched = 0
    try:
        with cf.ThreadPoolExecutor(max_workers=workers) as pool:
            for trade_date, payload in pool.map(fetch, paths):
                bars.extend(bars_from_bhavcopy(payload, date.fromisoformat(trade_date)))
                fetched += 1
    except Exception as exc:
        if "cap exceeded" not in str(exc).lower():
            raise
        return bars, (
            f"stopped after {fetched} of {len(paths)} files: B2 daily download cap "
            f"reached. See docs/RUNBOOKS/b2-transaction-cap.md"
        )
    return bars, ""


def _corporate_action_days() -> set[tuple[str, date]]:
    """(symbol, day) for every known corporate action, +/- one day.

    Sprint 5 already knows why most large price moves happened. Without this,
    the extreme-move check reports every split and bonus as a suspicious jump
    - measured on 250 real days, 97 of 235 findings were actions we had
    recorded all along. Reporting a known event as an anomaly is how a report
    trains its reader to skim.

    The one-day window absorbs the ordinary disagreement between an ex-date
    and the session the price actually gapped on.
    """
    try:
        actions, _ = load_actions(Path("data/landing/nse"))
    except (OSError, ValueError):
        return set()
    out: set[tuple[str, date]] = set()
    for action in actions:
        if not action.symbol:
            continue
        for offset in (-1, 0, 1):
            out.add((action.symbol, action.ex_date + timedelta(days=offset)))
    return out


def _row_findings(bars: Sequence[Bar]) -> list[Finding]:
    """Row checks need one instrument's history in order, so bars are grouped
    by symbol before checking — a spike is only meaningful against the same
    instrument's own past."""
    by_symbol: dict[str, list[Bar]] = defaultdict(list)
    for bar in bars:
        by_symbol[bar.symbol].append(bar)

    known = _corporate_action_days()

    out: list[Finding] = []
    for symbol in sorted(by_symbol):
        history = sorted(by_symbol[symbol], key=lambda b: b.day)
        for finding in run_row_checks(history):
            if (
                finding.check == "extreme-move"
                and finding.symbol
                and finding.day
                and (finding.symbol, finding.day) in known
            ):
                # Explained, so it is context rather than a problem. Kept at
                # INFO rather than dropped: a reader comparing the two counts
                # can see how much of the market's movement we can account
                # for, and a sudden fall in that ratio is itself a signal.
                out.append(
                    replace(
                        finding,
                        severity=Severity.INFO,
                        check="extreme-move-explained",
                        detail=finding.detail.split(";")[0] + "; matches a known corporate action",
                    )
                )
            else:
                out.append(finding)
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="quality", description=__doc__)
    parser.add_argument("--landing", type=Path, default=LANDING_ROOT)
    parser.add_argument("--manifest", type=Path, default=NSE_MANIFEST)
    parser.add_argument(
        "--rows",
        type=int,
        default=0,
        help=(
            "also check price rows, using the N most recent cash bhavcopy files. "
            "Costs one B2 download each against a 2,500/day cap"
        ),
    )
    parser.add_argument("--limit", type=int, default=20, help="findings to print (default 20)")
    parser.add_argument(
        "--show-suppressed",
        action="store_true",
        help="list the known-and-documented findings that are normally hidden",
    )
    args = parser.parse_args(argv)

    report = Report()
    report.extend(run_manifest_checks(args.landing))
    note = ""

    if args.rows:
        available = _cash_files(args.manifest)
        chosen = available[: args.rows]
        print(f"row checks: {len(chosen)} cash bhavcopy files to download from B2")
        print("  (2,500 downloads/day free - see docs/RUNBOOKS/b2-transaction-cap.md)")
        bars, note = _load_bars(chosen)
        print(f"  parsed {len(bars):,} bars")
        report.extend(_row_findings(bars))

    print(f"\nquality report - {args.landing}")
    print(report.render(limit=args.limit))
    if note:
        print(f"\nincomplete: {note}")

    if args.show_suppressed:
        print("\nsuppressed detail:")
        for finding, known in report.suppressed:
            print(f"  [{known.stub}] {finding.line()}")

    if not args.rows:
        print(
            "\nrow-level checks not run. Add --rows N (e.g. `make quality ROWS=30`) "
            "to check OHLC bounds, spikes and stale prices against real data."
        )

    return 1 if report.count(Severity.ERROR) else 0


if __name__ == "__main__":
    raise SystemExit(main())
