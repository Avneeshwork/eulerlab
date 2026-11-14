"""Signals an agent invents: a named formula, kept only if code finds it honest (#163, ADR-191).

The rule engine has eleven signals and language v2 a few more fields. When a
paper needed anything else, the lab wrote the draft off as "unbuildable" and an
engineer had to add the field. Here an agent defines a feature itself, as a
formula over the fields and operators of `research/lang.py`, and code decides
whether it may be used:

    name      lowercase, 3-40 characters, not an existing field or operator
    formula   a language-v2 expression, e.g. div(delay(close_price, 1), delay(ts_mean(close_price, 20), 1))
    why       the economic reason, in a sentence

**The checks, all code, no model:**

| Check | Refused when |
|---|---|
| compiles | the formula does not parse or reads a field before it is known (`lang.check_lookahead`) |
| look-ahead, measured | the values on early sessions change when later sessions are removed from the data |
| coverage | fewer than 5% of tradable stock-sessions have a value |
| deterministic | two evaluations differ by a bit |
| new | its cross-sectional ranks correlate 0.95 or more with a field or a feature already kept |

A feature that passes is appended to `data/derived/features.jsonl` with its
checks, its author and the formula's fingerprint; one that fails is appended
too, refused, with why, so a refusal is not tried again blind. Nothing is ever
edited.

**How a kept feature is used.** `expand(text)` replaces each feature name in an
expression with its formula, so a card stores the formula itself and reads the
same whether or not the registry is there. Nothing is passed to `exec` or
`eval`: a feature is a tree of the language's own operators. Free Python waits
for a sandbox (T-4618).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from eulerlab.db.stream import add_row, read_rows
from eulerlab.features.formula import FormulaError, Node, Op, parse, text_of
from eulerlab.paths import data_path
from eulerlab.research import lang

PATH = "derived/features.jsonl"
KIND = "features"
NAME = re.compile(r"^[a-z][a-z0-9_]{2,39}$")
MIN_COVERAGE = 0.05
MAX_LIKENESS = 0.95
CUTS = (0.5, 0.75)
"""Where the measured look-ahead test cuts the sessions, as shares of the window."""

# ASSUMPTION: A-147 — the coverage and likeness bars were chosen by hand, not tuned on results.


def _path(path: Path | None) -> Path:
    return path if path is not None else data_path(PATH)


@dataclass(frozen=True)
class Feature:
    name: str
    formula: str
    """The expanded formula: only base fields and operators."""
    why: str
    author: str
    at: str


def rows(path: Path | None = None) -> list[dict[str, Any]]:
    """Every definition, kept or refused, oldest first (a file, or Postgres when it is on)."""
    return [r for r in read_rows(_path(path), KIND) if isinstance(r, dict)]


def kept(path: Path | None = None) -> dict[str, Feature]:
    """Every feature that passed, by name; the first definition of a name wins."""
    out: dict[str, Feature] = {}
    for row in rows(path):
        if row.get("status") == "kept" and row.get("name") not in out:
            out[str(row["name"])] = Feature(
                str(row["name"]),
                str(row["formula"]),
                str(row.get("why") or ""),
                str(row.get("author") or ""),
                str(row.get("at") or ""),
            )
    return out


def _parse_with(text: str, features: Mapping[str, Feature]) -> Node:
    ops = {**lang.OPS, **{n: Op(0, 0, f.why) for n, f in features.items()}}
    return parse(text, ops, max_depth=lang.MAX_DEPTH * 2, max_nodes=lang.MAX_NODES * 4)


def _replace(node: Node, trees: Mapping[str, Node]) -> Node:
    if node.op in trees and not node.args:
        return trees[node.op]
    if not node.args:
        return node
    return Node(
        op=node.op,
        args=tuple(_replace(a, trees) for a in node.args),
        params=node.params,
        value=node.value,
    )


def expand(text: str, features: Mapping[str, Feature] | None = None) -> str:
    """`text` with every kept feature's name replaced by its formula, compiled and checked."""
    found = kept() if features is None else features
    if not found or not any(n in text for n in found):
        return text_of(lang.compile_text(text))
    trees = {n: lang.compile_text(f.formula) for n, f in found.items()}
    expanded = text_of(_replace(_parse_with(text, found), trees))
    return text_of(lang.compile_text(expanded))


def describe(features: Mapping[str, Feature] | None = None) -> str:
    found = kept() if features is None else features
    if not found:
        return "No features defined yet."
    return "Features defined by agents (use by name):\n" + "\n".join(
        f"  {f.name}  = {f.formula}   ({f.why}; by {f.author})" for f in found.values()
    )


# --- the checks --------------------------------------------------------------------------


class _Cut:
    """The first `rows` sessions of a panel, as if nothing later existed."""

    def __init__(self, panel: lang.Panel, rows: int) -> None:
        self._panel = panel
        self._rows = rows

    @property
    def days(self) -> Sequence[Any]:
        return self._panel.days[: self._rows]

    @property
    def symbols(self) -> Sequence[str]:
        return self._panel.symbols

    def field(self, name: str, n: int) -> lang.Matrix:
        return self._panel.field(name, n)[: self._rows]

    def groups(self) -> Any:
        return self._panel.groups()


def _ranks(x: lang.Matrix) -> lang.Matrix:
    return lang._rank(x)


def _likeness(a: lang.Matrix, b: lang.Matrix) -> float | None:
    """Pooled correlation of two tables' cross-sectional ranks, over cells both have."""
    ra, rb = _ranks(a), _ranks(b)
    both = ~np.isnan(ra) & ~np.isnan(rb)
    if both.sum() < 50:
        return None
    x, y = ra[both], rb[both]
    if x.std() == 0 or y.std() == 0:
        return None
    return float(np.corrcoef(x, y)[0, 1])


def check(
    name: str,
    formula: str,
    panel: lang.Panel,
    tradable: np.ndarray[Any, np.dtype[np.bool_]],
    *,
    features: Mapping[str, Feature] | None = None,
) -> dict[str, Any]:
    """Every check on a proposed feature. {"ok": bool, "why": str, "checks": {...}, "formula": str}."""
    found = kept() if features is None else features
    checks: dict[str, Any] = {}

    def refuse(why: str) -> dict[str, Any]:
        return {"ok": False, "why": why, "checks": checks, "formula": formula}

    if not NAME.match(name):
        return refuse("a name is 3-40 lowercase letters, digits or _, starting with a letter")
    if name in lang.OPS or name in found:
        return refuse(f"{name} is already a field, an operator or a feature")
    try:
        text = expand(formula, found)
    except FormulaError as exc:
        checks["compiles"] = False
        return refuse(f"does not compile: {exc}")
    checks["compiles"] = True
    tree = lang.compile_text(text)
    full = lang.Evaluator(panel).value(tree)
    again = lang.Evaluator(panel).value(tree)
    checks["deterministic"] = bool(np.array_equal(full, again, equal_nan=True))
    if not checks["deterministic"]:
        return refuse("two evaluations gave different values")
    rows_ = len(panel.days)
    for share in CUTS:
        cut = max(1, int(rows_ * share))
        early = lang.Evaluator(_Cut(panel, cut)).value(tree)
        if not np.array_equal(early, full[:cut], equal_nan=True):
            checks["lookahead"] = f"values before session {cut} change when later ones are removed"
            return refuse(checks["lookahead"])
    checks["lookahead"] = "none found"
    cells = int(tradable.sum())
    covered = int((~np.isnan(full) & tradable).sum())
    checks["coverage"] = round(covered / cells, 4) if cells else 0.0
    if checks["coverage"] < MIN_COVERAGE:
        return refuse(f"only {checks['coverage']:.1%} of tradable stock-sessions have a value")
    others: dict[str, lang.Matrix] = {}
    for field, info in lang.FIELDS.items():
        if not info.market_wide:
            leaf = f"{field}(20)" if info.window else field
            others[field] = lang.Evaluator(panel).value(lang.compile_text(f"delay({leaf}, 1)"))
    for other in found.values():
        others[other.name] = lang.Evaluator(panel).value(lang.compile_text(other.formula))
    worst = ("", 0.0)
    for other_name, table in others.items():
        like = _likeness(full, table)
        if like is not None and abs(like) > abs(worst[1]):
            worst = (other_name, like)
    checks["closest"] = {"to": worst[0], "rank_correlation": round(worst[1], 3)}
    if abs(worst[1]) >= MAX_LIKENESS:
        return refuse(f"the same signal as {worst[0]} (rank correlation {worst[1]:+.2f})")
    return {"ok": True, "why": "", "checks": checks, "formula": text}


def define(
    name: str,
    formula: str,
    why: str,
    *,
    author: str,
    panel: lang.Panel,
    tradable: np.ndarray[Any, np.dtype[np.bool_]],
    now: datetime | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    """Check a feature and append the outcome, kept or refused. Returns the check's result."""
    found = check(name, formula, panel, tradable, features=kept(path))
    row = {
        "at": (now or datetime.now(UTC)).isoformat(timespec="seconds"),
        "name": name,
        "formula": found["formula"],
        "asked": formula,
        "why": why.strip()[:300],
        "author": author,
        "status": "kept" if found["ok"] else "refused",
        "refused_because": found["why"],
        "checks": found["checks"],
        "fingerprint": hashlib.sha256(str(found["formula"]).encode()).hexdigest()[:16],
    }
    add_row(_path(path), KIND, row)
    return found
