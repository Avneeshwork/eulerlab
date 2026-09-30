"""`make audit` — run every pass and print what it found."""

from __future__ import annotations

import argparse
from pathlib import Path

from eulerlab.audit import Report, Severity
from eulerlab.audit.rules import REPO

MARK = {Severity.FAIL: "FAIL", Severity.WARN: "warn", Severity.NOTE: "note"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="audit", description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO)
    parser.add_argument(
        "--review",
        action="store_true",
        help="also ask a model to read the diff. Advisory, never gates.",
    )
    parser.add_argument("--against", default="HEAD", help="what --review diffs against")
    parser.add_argument("--provider", default=None, help="override the model provider")
    parser.add_argument(
        "--inventory",
        action="store_true",
        help="print every strategy with the file and function behind it",
    )
    args = parser.parse_args(argv)

    from eulerlab.audit import inventory as inv
    from eulerlab.audit import rules, smoke

    if args.inventory:
        print(inv.render())
        return 0

    report = Report()

    found, files = rules.run(args.root)
    report.findings.extend(found)
    report.checked += files
    print(f"rules     {files:>4d} files")

    found, strategies = smoke.run()
    report.findings.extend(found)
    print(f"smoke     {strategies:>4d} strategies invoked")

    entries = inv.inventory()
    report.findings.extend(inv.check_names(entries))
    print(f"inventory {len(entries):>4d} strategies in {len({e.module for e in entries})} files")

    if args.review:
        from eulerlab.audit import review

        found, skipped = review.run(args.root, against=args.against, provider_name=args.provider)
        report.findings.extend(found)
        report.review_skipped = skipped
        print(f"review    {'skipped: ' + skipped if skipped else f'{len(found)} notes'}")

    print()
    for severity in (Severity.FAIL, Severity.WARN, Severity.NOTE):
        group = report.by_severity(severity)
        if not group:
            continue
        print(f"--- {severity.value} ({len(group)}) ---")
        for finding in group:
            where = f"  {finding.where()}" if finding.where() else ""
            print(f"{MARK[severity]}  {finding.rule}{where}")
            print(f"      {finding.message}")
            if finding.because and severity is not Severity.NOTE:
                print(f"      why: {finding.because}")
        print()

    if report.failed:
        print(f"{len(report.by_severity(Severity.FAIL))} failing. Fix or justify each.")
        return 1
    print("no failures.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
