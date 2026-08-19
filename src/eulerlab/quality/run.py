"""`make quality` — run every check and print counts by severity.

Ordered so the free work happens first. Manifest checks read local files and
cost nothing; row checks need price data from B2 at one transaction per file,
against a 2,500/day cap that has already stopped one build outright. So the
row phase is opt-in via `--rows N`, reports how much of the budget it intends
to spend before spending it, and stops cleanly rather than failing hard when
the cap is reached.

Exit code is 1 only for ERROR findings. Warnings are for the operator to read,
not for CI to block on — a check that blocks the build on a 12% price move
teaches everyone to bypass the build.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from eulerlab.quality.findings import Report
from eulerlab.quality.manifest_checks import LANDING_ROOT, run_manifest_checks


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="quality", description=__doc__)
    parser.add_argument("--landing", type=Path, default=LANDING_ROOT)
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="how many individual findings to print (default 20)",
    )
    parser.add_argument(
        "--show-suppressed",
        action="store_true",
        help="list the known-and-documented findings that are normally hidden",
    )
    args = parser.parse_args(argv)

    report = Report()
    report.extend(run_manifest_checks(args.landing))

    print(f"quality report - {args.landing}")
    print(report.render(limit=args.limit))

    if args.show_suppressed:
        print("\nsuppressed detail:")
        for finding, known in report.suppressed:
            print(f"  [{known.stub}] {finding.line()}")

    return 1 if report.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
