"""Each workspace's gate: the platform's mandate, made stricter and never looser (ADR-169).

Operator, 2026-11-12 (decision card): "Platform gate, stricter only".

`mandate.yaml` is the floor for every workspace and stays operator-owned; this
module never writes it and `gates.py` is unchanged. A workspace owner may
store a few thresholds of their own, and `effective()` returns the mandate
with those applied, which the gate run passes to `gates.decide(mandate=...)`.

**Refused, not clamped.** A value looser than the platform's, or a key not in
`TIGHTENABLE`, raises `Looser`. Quietly clamping would let an owner believe
they are held to a bar they are not.

Only thresholds with one obvious direction can be tightened. The switches
(`require_*`, `mode`, the process rules, the holdout date) are the platform's
alone: `simple` and `strict` test different things, so neither is "stricter".

The default workspace, and any install with accounts off, gets the mandate
exactly as written.
"""

from __future__ import annotations

import copy
import json
from typing import Any

from eulerlab import accounts, db, gates
from eulerlab.workspace import DEFAULT_ID

HIGHER, LOWER = "higher", "lower"
TIGHTENABLE: dict[str, str] = {
    "simple.min_probabilistic_sharpe": HIGHER,
    "simple.min_positive_year_fraction": HIGHER,
    "paper.min_full_sample_sharpe": HIGHER,
    "paper.min_probabilistic_sharpe": HIGHER,
    "statistical.min_deflated_sharpe_probability": HIGHER,
    "statistical.min_t_statistic": HIGHER,
    "statistical.min_backtest_length_ratio": HIGHER,
    "statistical.max_pbo": LOWER,
    "robustness.min_sharpe_retained_at_2x_costs": HIGHER,
    "robustness.min_sharpe_retained_dropping_best_names": HIGHER,
    "robustness.min_sharpe_retained_worst_regime": HIGHER,
    "forward_test.min_days": HIGHER,
    "forward_test.min_sharpe_ratio_of_backtest": HIGHER,
    "forward_test.max_drawdown": LOWER,
}
"""Dotted path into the mandate, and which direction is stricter."""


class Looser(ValueError):
    """The rules asked for would loosen the platform gate, or name something not theirs to set."""


def _at(mandate: dict[str, Any], dotted: str) -> tuple[dict[str, Any], str]:
    *parents, leaf = dotted.split(".")
    node = mandate
    for part in parents:
        node = node[part]
    return node, leaf


def tighten(base: dict[str, Any], rules: dict[str, float]) -> dict[str, Any]:
    """`base` with `rules` applied. Raises `Looser` on anything that is not stricter-or-equal."""
    out = copy.deepcopy(base)
    for key, value in rules.items():
        direction = TIGHTENABLE.get(key)
        if direction is None:
            msg = f"{key} is set by the platform and cannot be changed per workspace"
            raise Looser(msg)
        if isinstance(value, bool) or not isinstance(value, int | float):
            msg = f"{key} must be a number"
            raise Looser(msg)
        node, leaf = _at(out, key)
        floor = node[leaf]
        looser = value < floor if direction == HIGHER else value > floor
        if looser:
            word = "at least" if direction == HIGHER else "at most"
            msg = f"{key} must be {word} the platform's {floor}; {value} would loosen the gate"
            raise Looser(msg)
        node[leaf] = value
    return out


def own_rules(workspace_id: str | None = None) -> dict[str, float]:
    """The workspace's stored tightening, newest version; {} when it has none."""
    workspace_id = workspace_id or accounts.current().workspace_id
    if workspace_id == DEFAULT_ID or not db.configured():
        return {}
    with db.connect() as conn:
        row = conn.execute(
            "SELECT rules FROM workspace_gate WHERE workspace_id = %s"
            " ORDER BY version DESC LIMIT 1",
            (workspace_id,),
        ).fetchone()
    return dict(json.loads(row[0])) if row else {}


def set_rules(rules: dict[str, float]) -> int:
    """Store the current workspace's tightening. Returns the new version."""
    principal = accounts.current()
    if principal.workspace_id == DEFAULT_ID:
        msg = "the default workspace is held to mandate.yaml itself; the operator edits that"
        raise Looser(msg)
    tighten(gates.load_mandate(), rules)  # refuse before storing
    with db.connect() as conn:
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s))", (f"gate:{principal.workspace_id}",)
        )
        row = conn.execute(
            "SELECT coalesce(max(version), 0) + 1 FROM workspace_gate WHERE workspace_id = %s",
            (principal.workspace_id,),
        ).fetchone()
        version = int(row[0]) if row else 1
        conn.execute(
            "INSERT INTO workspace_gate (workspace_id, version, rules, set_by)"
            " VALUES (%s, %s, %s, %s)",
            (principal.workspace_id, version, json.dumps(rules, sort_keys=True), principal.user_id),
        )
    return version


def effective() -> dict[str, Any]:
    """The mandate the current workspace is held to.

    If the platform's mandate has since been raised above a stored value, the
    platform's wins for that threshold: the stored value is no longer stricter,
    and a gate run must not fail to start because of it.
    """
    base = gates.load_mandate()
    rules = own_rules()
    kept = {}
    for key, value in rules.items():
        try:
            tighten(base, {key: value})
        except Looser:
            continue
        kept[key] = value
    return tighten(base, kept)
