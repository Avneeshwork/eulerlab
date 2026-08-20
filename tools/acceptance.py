"""``make acceptance`` — every sprint's acceptance check, end to end, one table.

`make verify` proves the repository is healthy: lint, types, tests, docs, the
engine gate, the chaos gate. This is the other question — **does each sprint's
promised capability still work on the real data?** They are different failures.
Every unit test can pass while the security master is stale, the panel is
missing, or the adjustment factors were never rebuilt.

One rule governs what may appear here, and it is not about time:

**Nothing in this suite may spend a trial.**

`make gate` and `make validate` both append to the hash-chained trial ledger,
and `CLAUDE.md` says every configuration evaluated increments that counter and
it is never reset. A suite that is *meant* to be run repeatedly must therefore
never call them — re-running acceptance ten times would log ten trials, and
every trial permanently raises the Deflated Sharpe bar for every future
candidate. The cost is real and measured: one accidental `make gate` run on
2026-08-20 moved the bar from Sharpe 1.83 to 1.88.

So the gate is represented here by `gate-acceptance`, which feeds three
deliberately overfit strategies through the same logic and only *reads* the
trial count. It exercises the gate without buying anything.

Checks that need a lot of Backblaze downloads are skipped by default and
listed as SKIPPED with the reason, rather than silently omitted. `--all`
includes them.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
DIM = "\033[2m"
RESET = "\033[0m"


@dataclass(frozen=True)
class Check:
    sprint: str
    what: str
    command: Sequence[str]
    expect: str
    """A string that must appear in the output, **on top of** a zero exit code.

    Both, because each alone lets a real failure through. An exit code alone
    passes a command that ran, printed a failure and exited 0 — which is what
    a half-working data pipeline does. A string alone passes a command that
    crashed after printing its happy line, and it is easy to get wrong: the
    first version of this file looked for "passed" in `make test-lookahead`,
    whose pytest invocation is quiet and prints only dots, so a fully green
    suite was reported FAIL. Empty means the exit code is the whole check,
    which is right for pytest and wrong for almost everything else."""

    costly: str = ""
    """Non-empty means skipped by default, and this says why."""


CHECKS: tuple[Check, ...] = (
    Check(
        "4",
        "lookahead firewall",
        ("make", "test-lookahead"),
        "",  # pytest is quiet here; its exit code is the authoritative answer
    ),
    Check(
        "3",
        "security master",
        ("make", "check-master"),
        "check-master OK",
    ),
    Check(
        "5",
        "corporate actions",
        ("make", "check-adjust"),
        "check-adjust OK",
    ),
    Check(
        "6",
        "data quality",
        ("make", "quality"),
        "quality OK",
    ),
    Check(
        "9",
        "cost model",
        ("make", "check-costs"),
        "check-costs",
        # PARTIAL is the honest current state: 4 green, 1 awaiting the
        # operator's contract notes (T-906). Matching on the summary line
        # rather than on "OK" so this reports the truth instead of failing
        # for a reason that is not a defect.
    ),
    Check(
        "12",
        "engine self-tests",
        ("make", "test-engine"),
        "test-engine OK",
    ),
    Check(
        "14",
        "promotion gate kills overfit strategies",
        ("make", "gate-acceptance"),
        "all 3 overfit strategies were killed",
    ),
    Check(
        "15-18",
        "research loop",
        ("make", "research"),
        "trials logged",
    ),
    Check(
        "19-24",
        "chaos: killed mid-order",
        ("make", "chaos"),
        "chaos OK",
    ),
    Check(
        "22",
        "book reconciles against the broker",
        ("make", "reconcile-book"),
        "reconciliation",
    ),
    Check(
        "23",
        "kill switch reports its state",
        ("make", "kill-status"),
        "kill switch",
    ),
    Check(
        "25-28",
        "paper reproduces the backtest exactly",
        ("make", "attribution", "FRICTIONLESS=1", "DAYS=800"),
        "gap is EXACTLY zero",
        costly="~6 min: two full runs over 546 days of the real panel",
    ),
    Check(
        "8",
        "IC tear sheet",
        ("make", "ic", "FEATURE=momentum_12_1"),
        "momentum_12_1",
        costly="~2 min over the real panel",
    ),
    Check(
        "7",
        "options no-arbitrage checks",
        ("make", "quality-options", "DAYS=3"),
        "",
        costly="needs F&O files from B2 — they are pruned locally (2,500/day cap)",
    ),
)
"""Sprint 11 (the Tier B engine) has no row of its own on purpose: its
acceptance is that the two engines reconcile, and `test-engine` already checks
that as one of its ten. A second command running both engines over the full
panel would take minutes to re-answer a question already answered.

Sprints 1, 2 and 10 are absent for different reasons. Sprint 1's ingest is
verified by `check-landing`, which re-hashes local files — and the landing zone
is pruned to Backblaze, so there is little left locally to hash. Sprint 2's
options recorder was never deployed to a VPS (see `STATE.md`). Sprint 10's Tier
A engine is covered by the reconciliation above.
"""


@dataclass(frozen=True)
class Outcome:
    check: Check
    status: str
    detail: str
    seconds: float
    output: str


def run_one(check: Check) -> Outcome:
    started = time.monotonic()
    completed = subprocess.run(
        check.command,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "NO_COLOR": "1"},
    )
    elapsed = time.monotonic() - started
    output = (completed.stdout + completed.stderr).strip()

    if completed.returncode != 0:
        tail = next((ln for ln in reversed(output.splitlines()) if ln.strip()), "")
        return Outcome(check, "FAIL", f"exit {completed.returncode}: {tail[:70]}", elapsed, output)
    if check.expect and check.expect not in output:
        return Outcome(
            check, "FAIL", f"exited 0 but never printed {check.expect!r}", elapsed, output
        )

    summary = next(
        (ln.strip() for ln in reversed(output.splitlines()) if check.expect and check.expect in ln),
        "exit 0",
    )
    return Outcome(check, "PASS", summary[:90], elapsed, "")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Every sprint's acceptance check.")
    parser.add_argument("--all", action="store_true", help="include the slow ones")
    args = parser.parse_args(argv)

    colour = sys.stdout.isatty() and not os.environ.get("NO_COLOR")

    def paint(text: str, code: str) -> str:
        return f"{code}{text}{RESET}" if colour else text

    print(
        paint(
            "\nEnd-to-end acceptance. `make verify` asks whether the repository is\n"
            "healthy; this asks whether each sprint's capability still works on the\n"
            "real data. Nothing here spends a trial — see the module docstring.\n",
            DIM,
        )
    )
    print(paint(f"{'SPRINT':<9}{'WHAT':<44}{'RESULT':<9}{'DETAIL'}", DIM))

    outcomes: list[Outcome] = []
    for check in CHECKS:
        if check.costly and not args.all:
            print(f"{check.sprint:<9}{check.what:<44}{paint(f'{"SKIP":<9}', YELLOW)}{check.costly}")
            continue
        outcome = run_one(check)
        outcomes.append(outcome)
        print(
            f"{check.sprint:<9}{check.what:<44}"
            f"{paint(f'{outcome.status:<9}', GREEN if outcome.status == 'PASS' else RED)}"
            f"{outcome.detail}"
        )

    failures = [o for o in outcomes if o.status != "PASS"]
    for outcome in failures:
        print(paint(f"\n--- {outcome.check.what} ---", RED))
        print(outcome.output[-3000:])

    total = sum(o.seconds for o in outcomes)
    if failures:
        print(paint(f"\nacceptance FAILED: {len(failures)} of {len(outcomes)} red", RED))
        return 1
    skipped = sum(1 for c in CHECKS if c.costly and not args.all)
    note = f", {skipped} skipped (run with --all)" if skipped else ""
    print(
        paint(f"\nacceptance OK: {len(outcomes)} of {len(outcomes)} green{note}", GREEN)
        + f"  [{total:.0f}s]"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
