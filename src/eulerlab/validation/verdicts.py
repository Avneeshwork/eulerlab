"""The gate's verdicts, read-only: which hypotheses the gate promoted, and when.

Agents may not import the trial ledger module (`agents/boundaries.py`),
because it is also the ledger's writer. This reads the same file through
`ledger.read` and hands back plain values, so the portfolio agent can ask
"what has passed?" without being able to append a trial.
"""

from __future__ import annotations

from dataclasses import dataclass

from eulerlab.validation import ledger


@dataclass(frozen=True)
class Verdict:
    subject: str
    verdict: str
    at: str


def gate_verdicts() -> list[Verdict]:
    """Every gate verdict in the ledger, oldest first; a later one supersedes."""
    return [
        Verdict(e.subject, str(e.outcome.get("verdict", "?")), e.logged_at)
        for e in ledger.read()
        if e.kind == "gate"
    ]


def promoted() -> list[str]:
    """Hypotheses whose latest gate verdict is PROMOTE."""
    latest: dict[str, str] = {}
    for v in gate_verdicts():
        latest[v.subject] = v.verdict
    return sorted(s for s, v in latest.items() if v == "PROMOTE")


def trial_count() -> int:
    return len(ledger.read())
