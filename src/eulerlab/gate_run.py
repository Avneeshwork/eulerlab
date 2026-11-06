"""`make gate H=H-0001` — apply the mandate to a hypothesis's evidence."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from eulerlab import gates
from eulerlab.validation import ledger

EVIDENCE = Path("data/derived/evidence")
HYPOTHESES = Path("hypotheses")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gate", description=__doc__)
    parser.add_argument("--hypothesis", default="H-0001")
    parser.add_argument(
        "--read-holdout",
        default="",
        metavar="OPERATOR",
        help="spend the single holdout read, attributed to this person. Irreversible.",
    )
    args = parser.parse_args(argv)

    pack_path = EVIDENCE / f"{args.hypothesis}.json"
    if not pack_path.exists():
        print(f"no evidence at {pack_path}. Run `make validate H={args.hypothesis}` first.")
        return 2

    pack = json.loads(pack_path.read_text(encoding="utf-8"))
    decision = gates.decide(pack, hypothesis_path=HYPOTHESES / f"{args.hypothesis}.yaml")
    print(decision.render())

    allowed, reason = gates.may_read_holdout(decision)
    print(f"\nholdout: {reason}")

    if args.read_holdout:
        if not allowed:
            print("REFUSED. The holdout is not read on request; it is read on a passing gate.")
            return 1
        gates.record_holdout_read(args.hypothesis, authorised_by=args.read_holdout)
        print(f"holdout read recorded for {args.hypothesis}, authorised by {args.read_holdout}.")
        print("That read cannot be returned.")

    # A gate decision is itself an evaluation and belongs in the ledger, so a
    # resubmission under a new id is visible rather than silent.
    entry = ledger.append(
        kind="gate",
        subject=args.hypothesis,
        params={"mandate_version": gates.load_mandate().get("version")},
        outcome={
            "verdict": str(decision.verdict),
            "failed_rules": [f.rule for f in decision.failures],
        },
    )
    print(f"ledger entry #{entry.seq} {entry.entry_hash[:16]}...")
    if decision.verdict is gates.Verdict.PAPER:
        return 3
    return 0 if decision.verdict is gates.Verdict.PROMOTE else 1


if __name__ == "__main__":
    raise SystemExit(main())
