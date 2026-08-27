"""Deterministic checks. Every one of these caught a real defect.

Written against the AST rather than the text, because the interesting cases
differ by where a bracket sits — `_closes(window)[-n:]` and
`_closes(window[-n:])` are the same characters in a different order and one of
them is quadratic.
"""

from __future__ import annotations

import ast
from pathlib import Path

from eulerlab.audit import Finding, Severity

REPO = Path(__file__).resolve().parents[3]

EXTRACTORS = frozenset({"_closes", "_highs", "_lows", "_volumes", "_opens"})
"""Helpers that walk a candle window and return a list of one field.

Bounded input or not, they are O(len(window)). `detect` is called once per bar
with every bar so far, so handing one the whole window is O(n) per call and
O(n**2) per run. That is what made a 1,244-session request pass the 900s job
cap and return nothing, and it is invisible in a short backtest.
"""

COST_MODULES = ("costs/", "intraday/", "backtest/")
"""Where a wrong asset class silently bills the wrong exchange's taxes."""


def _python_files(root: Path) -> list[Path]:
    return sorted(p for p in (root / "src").rglob("*.py") if "__pycache__" not in p.parts)


def _relative(path: Path) -> str:
    try:
        return path.relative_to(REPO).as_posix()
    except ValueError:
        return path.as_posix()


def unbounded_window_reads(tree: ast.AST, path: Path) -> list[Finding]:
    """An extractor handed a whole window rather than a slice of one."""
    out: list[Finding] = []
    for function in ast.walk(tree):
        if not isinstance(function, ast.FunctionDef):
            continue
        params = {arg.arg for arg in function.args.args}
        if not params & {"window", "candles", "bars"}:
            continue
        for node in ast.walk(function):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            if node.func.id not in EXTRACTORS or not node.args:
                continue
            first = node.args[0]
            # A bare name is the whole window. A Subscript is a slice of it,
            # which is the shape that is safe.
            if isinstance(first, ast.Name) and first.id in params:
                out.append(
                    Finding(
                        rule="unbounded-window-read",
                        severity=Severity.FAIL,
                        message=(
                            f"{function.name}() calls {node.func.id}({first.id}) on the whole "
                            f"window; slice before extracting, not after"
                        ),
                        path=_relative(path),
                        line=node.lineno,
                        because="O(n) per bar is O(n^2) per run; a 5-year request times out",
                    )
                )
    return out


def defaulted_asset_class(tree: ast.AST, path: Path) -> list[Finding]:
    """A cost-bearing function that will guess a venue when not told one."""
    if not any(part in _relative(path) for part in COST_MODULES):
        return []
    out: list[Finding] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        args = node.args
        # Defaults align to the tail of the positional list; keyword-only
        # defaults sit in their own parallel list.
        positional = args.args[len(args.args) - len(args.defaults) :] if args.defaults else []
        keyword = [a for a, d in zip(args.kwonlyargs, args.kw_defaults, strict=True) if d]
        for arg in [*positional, *keyword]:
            if arg.arg not in {"asset_class", "venue", "segment", "market"}:
                continue
            out.append(
                Finding(
                    rule="defaulted-venue",
                    severity=Severity.FAIL,
                    message=f"{node.name}() defaults {arg.arg}; the caller must say",
                    path=_relative(path),
                    line=node.lineno,
                    because="a default venue billed Indian STT on crypto, US and every exit",
                )
            )
    return out


def unpaginated_listing(tree: ast.AST, path: Path) -> list[Finding]:
    """An S3 LIST whose continuation token is never followed."""
    out: list[Finding] = []
    loops = [n for n in ast.walk(tree) if isinstance(n, ast.While | ast.For)]
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        attribute = node.func
        if not isinstance(attribute, ast.Attribute) or attribute.attr != "list_objects_v2":
            continue
        # One request is correct when it is only asking whether anything is
        # there, which `MaxKeys=1` says explicitly.
        capped = any(
            k.arg == "MaxKeys" and isinstance(k.value, ast.Constant) and k.value.value == 1
            for k in node.keywords
        )
        if capped:
            continue
        inside = any(
            loop.lineno <= node.lineno <= (loop.end_lineno or loop.lineno) for loop in loops
        )
        if inside:
            continue
        out.append(
            Finding(
                rule="unpaginated-listing",
                severity=Severity.FAIL,
                message="list_objects_v2 outside a loop reads 1,000 keys and stops",
                path=_relative(path),
                line=node.lineno,
                because="the overflow reads as absent: re-uploads, and an undercounted census",
            )
        )
    return out


CHECKS = (unbounded_window_reads, defaulted_asset_class, unpaginated_listing)


def run(root: Path = REPO) -> tuple[list[Finding], int]:
    """Every deterministic check over every source file."""
    findings: list[Finding] = []
    files = _python_files(root)
    for path in files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        for check in CHECKS:
            findings.extend(check(tree, path))
    return findings, len(files)
