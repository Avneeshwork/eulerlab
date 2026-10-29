"""What no agent may import, checked by reading the source, not by trusting it.

The paper agent proved the pattern (ADR-084): a test parses the module and
fails on a forbidden import. Here it covers every worker in `agents/workers/`
and the runtime itself, so a new agent inherits the check without anyone
remembering to add it.

Forbidden for every agent: the order path (`oms`, `broker`), the operator's
gate (`gates`, `gate_run`), the trial ledger's writer and the validation
battery, the secret loader, and the kill switch's reset. A worker that needs
something from these asks for a read-only helper elsewhere, which then gets
its own review.
"""

from __future__ import annotations

import ast
from pathlib import Path

FORBIDDEN = (
    "eulerlab.oms",
    "eulerlab.broker",
    "eulerlab.gates",
    "eulerlab.gate_run",
    "eulerlab.validation.ledger",
    "eulerlab.validation.run",
    "eulerlab.validation.holdout",
    "eulerlab.features.trials",
    "eulerlab.env",
    "eulerlab.deploy.runner",
    "eulerlab.deploy.overnight",
    "eulerlab.deploy.intraday_book",
    "subprocess",
)
"""Module prefixes no agent module may import.

`subprocess` is included because a shell is a way round every other line here.
The data agent's reruns go through `agents/jobs.py`, which calls the feed's
own idempotent steps in-process, from an allowlist."""

ALLOWED_EXCEPTIONS: dict[str, tuple[str, ...]] = {}
"""Per-module exceptions, by file name. Empty, and should stay so."""


def imports_of(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
            names.extend(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def violations(path: Path) -> list[str]:
    allowed = ALLOWED_EXCEPTIONS.get(path.name, ())
    found: list[str] = []
    for name in imports_of(path):
        for prefix in FORBIDDEN:
            if (name == prefix or name.startswith(prefix + ".")) and prefix not in allowed:
                found.append(f"{path.name} imports {name}")
    return sorted(set(found))


def agent_modules(package: Path | None = None) -> list[Path]:
    base = package or Path(__file__).resolve().parent
    return sorted([*base.glob("*.py"), *(base / "workers").glob("*.py")])
