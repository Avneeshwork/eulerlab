"""The model pass: what no rule anticipated.

Advisory, and structurally so. It cannot fail a build, its findings are always
NOTE, and the report says which model produced them. Two reasons, and neither
is squeamishness about models.

The first is that it is not reproducible. The same diff reviewed twice gives
different text, so a gate built on it would pass and fail the same commit.
Every other check here is deterministic and can be trusted to block.

The second is that it is guessing about a codebase it cannot run. The rules in
`rules.py` encode defects that actually shipped and can be checked exactly;
this reads code and forms an opinion. Those are different kinds of claim and
mixing them would make the exact ones look negotiable.

So it is pointed at the one thing rules are bad at: reviewing a *change* for
whether it does what its own comments say.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from eulerlab.audit import Finding, Severity

SYSTEM = """You are reviewing a diff from a quantitative trading research codebase.

The defects this codebase actually produces share one shape: a plausible \
default that silently applies the wrong thing, so the numbers still look \
right. Past examples: a default asset class billing Indian securities \
transaction tax on US and crypto trades; a signal reading its whole history \
on every bar, correct but quadratic, so a five-year run stopped returning; a \
paginated listing that read its first thousand results and treated the rest \
as absent.

Report only defects of that kind: something that produces a wrong number or a \
wrong decision without failing. Do not report style, naming, formatting, type \
annotations or missing docstrings — other tools already gate those and the \
author does not want them here.

For each finding output exactly one line:
FINDING|<file>|<line>|<one sentence: what is wrong and what it produces>

If the diff contains no such defect, output exactly: NONE
Never output anything else."""

MAX_DIFF = 40_000
"""Bytes of diff sent. A larger one is truncated rather than split, and the
report says so — a review of half a change presented as a review of the whole
one is worse than no review."""


def _diff(root: Path, against: str) -> str:
    result = subprocess.run(
        ["git", "diff", against, "--", "src", "web"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout if result.returncode == 0 else ""


def _parse(text: str, model: str) -> list[Finding]:
    out: list[Finding] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line.startswith("FINDING|"):
            continue
        parts = line.split("|", 3)
        if len(parts) < 4:
            continue
        _, path, where, message = parts
        try:
            number = int(where.strip())
        except ValueError:
            number = 0
        out.append(
            Finding(
                rule="model-review",
                severity=Severity.NOTE,
                message=message.strip(),
                path=path.strip(),
                line=number,
                because=f"opinion from {model}, not a checked fact",
            )
        )
    return out


def run(
    root: Path, *, against: str = "HEAD", provider_name: str | None = None
) -> tuple[list[Finding], str]:
    """Review the working diff. Returns (findings, reason it was skipped)."""
    from eulerlab.llm.client import LLMUnavailable, complete

    diff = _diff(root, against)
    if not diff.strip():
        return [], "nothing changed against " + against

    truncated = diff[:MAX_DIFF]
    note = "" if len(diff) <= MAX_DIFF else f" (truncated from {len(diff)} bytes)"
    try:
        reply = complete(
            SYSTEM, f"Review this diff{note}:\n\n{truncated}", provider_name=provider_name
        )
    except (LLMUnavailable, OSError) as exc:
        # Not reachable is a normal state, not an error. The default provider
        # is a local ollama that is usually not running, and an auditor that
        # fails when the optional pass is unavailable would stop being run.
        return [], f"no model reachable ({type(exc).__name__})"
    return _parse(reply.text, reply.model), ""
