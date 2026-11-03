"""Signals the engineering agent coded for research cards, one module each (ADR-127).

A research draft may name a signal the library lacks (`liquidity_beta`). The idea
lab cannot test it, so the engineering agent writes it here: one file
`<name>.py` defining `FEATURE = Feature(...)` (`Feature` from `features/base`,
never the library, which imports this package), and one test
`tests/test_coded_<name>.py`, on its own branch for the operator to merge. Once
merged, `library.BY_NAME` holds it and the lab's next run tests the card.

**Pure, or not loaded.** A feature sees only the history it is handed, which
ends at the decision day, so it cannot look ahead unless it reads something
else. `problems()` refuses any module that imports outside `ALLOWED_IMPORTS`,
calls `open`, `eval`, `exec` and the like, touches a dunder attribute, keeps
`global` state, or does not define `FEATURE`. It runs at load time in every
process (a refused module is skipped, never imported) and in
`tests/test_coded_features.py`, which the agent's branch must pass.
"""

from __future__ import annotations

import ast
import importlib
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from eulerlab.features.base import Feature

HERE = Path(__file__).resolve().parent
NAME = re.compile(r"^[a-z][a-z0-9_]{2,40}$")
"""A coded feature's name, which is also its module's name."""

ALLOWED_IMPORTS = frozenset(
    {
        "__future__",
        "math",
        "statistics",
        "collections.abc",
        "itertools",
        "eulerlab.features.base",
        "eulerlab.features.panel",
        "eulerlab.quality.robust",
    }
)
FORBIDDEN_CALLS = frozenset(
    {
        "open",
        "eval",
        "exec",
        "compile",
        "__import__",
        "globals",
        "locals",
        "vars",
        "getattr",
        "setattr",
        "delattr",
        "input",
        "breakpoint",
    }
)

_log = logging.getLogger(__name__)


def problems(source: str) -> list[str]:
    """Why this module may not be loaded, in words. Empty when it may."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [f"does not parse: {exc.msg} (line {exc.lineno})"]
    found: list[str] = []
    try:
        # Parsing alone accepts a misplaced `from __future__` (seen 2026-11-03).
        compile(source, "<coded feature>", "exec", dont_inherit=True)
    except SyntaxError as exc:
        found.append(f"does not compile: {exc.msg} (line {exc.lineno})")
    defines = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [f"imports {a.name}" for a in node.names if a.name not in ALLOWED_IMPORTS]
        elif isinstance(node, ast.ImportFrom):
            if node.level or (node.module or "") not in ALLOWED_IMPORTS:
                found.append(f"imports from {node.module or '.'}")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in FORBIDDEN_CALLS:
                found.append(f"calls {node.func.id}()")
        elif isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            found.append(f"uses {node.attr}")
        elif isinstance(node, ast.Global | ast.Nonlocal):
            found.append("keeps state between calls (global or nonlocal)")
    for node in tree.body:
        targets = (
            node.targets
            if isinstance(node, ast.Assign)
            else [node.target]
            if isinstance(node, ast.AnnAssign)
            else []
        )
        if any(isinstance(t, ast.Name) and t.id == "FEATURE" for t in targets):
            defines = True
    if not defines:
        found.append("defines no FEATURE")
    return sorted(set(found))


def modules(directory: Path = HERE) -> list[str]:
    """The coded features' module names, sorted, so loading order never changes."""
    return sorted(
        p.stem for p in directory.glob("*.py") if p.stem != "__init__" and NAME.match(p.stem)
    )


def load(taken: dict[str, Feature] | None = None, directory: Path = HERE) -> dict[str, Feature]:
    """Every coded feature that passes `problems()` and whose name is its module's
    and not already taken. A refused one is logged and skipped, never imported."""
    from eulerlab.features.base import Feature

    taken = taken or {}
    out: dict[str, Feature] = {}
    for name in modules(directory):
        wrong = problems((directory / f"{name}.py").read_text(encoding="utf-8"))
        if wrong:
            _log.warning("coded feature %s not loaded: %s", name, "; ".join(wrong))
            continue
        try:
            module = importlib.import_module(f"{__name__}.{name}")
        except Exception as exc:  # one bad module must not stop the library loading
            _log.warning("coded feature %s not loaded: %s: %s", name, type(exc).__name__, exc)
            continue
        feature = getattr(module, "FEATURE", None)
        if not isinstance(feature, Feature) or feature.name != name or name in taken:
            _log.warning("coded feature %s not loaded: FEATURE missing, misnamed or taken", name)
            continue
        out[name] = feature
    return out
