"""Re-run one experiment-store row and say what moved (#154, ADR-213).

    make reproduce ID=<experiment id>

The row's rule is rebuilt from its own `spec` (or its card), screened again on
the research data cut at the row's own end, and compared with what was
stored: the count, the net Sharpe, and the daily returns day by day. The
answer says whether the data and the code are still the ones that made the
row (`data_version`, `code`), so a mismatch comes with its likely cause
instead of a guess (research 192's ten rules, HISTORY #89).

It records nothing: re-running a result is not a new test of an idea. It
cannot bring back old data; when the data version differs it says so, and to
re-run old code, check out the row's commit in a worktree and run it there.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Mapping, Sequence
from datetime import date
from typing import Any

from eulerlab.intraday import rule_engine
from eulerlab.research import data_manifest, experiments

TOLERANCE = 1e-9
"""Two daily returns closer than this are the same."""

Engine = Callable[[date], rule_engine.Engine]


def _engine(end: date) -> rule_engine.Engine:
    from eulerlab.research import agent_tools

    return agent_tools.discovery_engine(end)


def rule_of(row: Mapping[str, Any]) -> rule_engine.Rule | None:
    """The row's rule: its recorded spec, else its card's."""
    from eulerlab.research import forward_shadow

    body = row.get("spec")
    if isinstance(body, dict):
        spec = forward_shadow.spec_from(body)
        if spec is not None:
            return spec
    hypothesis = str(row.get("hypothesis") or "")
    return rule_engine.card_spec(hypothesis) if hypothesis else None


def compare(stored: Mapping[date, float], again: Mapping[date, float]) -> dict[str, Any]:
    """Where two daily series differ: the first day that moved and how many did."""
    days = sorted(set(stored) | set(again))
    moved = [
        d
        for d in days
        if d not in stored or d not in again or abs(stored[d] - again[d]) > TOLERANCE
    ]
    return {
        "days": len(days),
        "moved": len(moved),
        "first_moved": moved[0].isoformat() if moved else None,
        "only_stored": sum(1 for d in days if d not in again),
        "only_now": sum(1 for d in days if d not in stored),
    }


def reproduce(row: Mapping[str, Any], engine: Engine = _engine) -> dict[str, Any]:
    """The re-run beside the stored row."""
    from eulerlab.reports import code_version

    rule = rule_of(row)
    out: dict[str, Any] = {"id": row.get("id"), "purpose": row.get("purpose")}
    now_data, now_code = data_manifest.version(), code_version()["commit"]
    out["data"] = {"then": row.get("data_version"), "now": now_data}
    out["code"] = {"then": (row.get("code") or {}).get("commit"), "now": now_code}
    if rule is None or rule.fingerprint() != row.get("fingerprint"):
        out["result"] = "cannot rebuild the rule: no spec on the row and no card with that rule"
        return out
    eng = engine(date.fromisoformat(str(row["end"])))
    found = eng.screen(rule)
    daily = eng.returns.pop(rule.fingerprint(), {})
    then = row.get("metrics") or {}
    now = {"count": found.get("count"), "net_sharpe": (found.get("net") or {}).get("sharpe")}
    out["metrics"] = {k: {"then": then.get(k), "now": v} for k, v in now.items()}
    if row.get("returns"):
        out["returns"] = compare(experiments.returns_of(row), daily)
    same = all(then.get(k) == v for k, v in now.items() if k in then) and not (
        out.get("returns") or {}
    ).get("moved")
    causes = [k for k in ("data", "code") if out[k]["then"] not in (None, out[k]["now"])]
    if same:
        out["result"] = "reproduced"
    elif causes:
        out["result"] = f"moved; changed since the row: {', '.join(causes)}"
    elif out["data"]["then"] is None:
        out["result"] = "moved; the row predates data and code stamps (2026-11-16), cause unknown"
    else:
        out["result"] = (
            "moved with the same data and code: the row was made another way "
            "(another engine or window), or the engine is not deterministic"
        )
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="make reproduce", description=__doc__)
    parser.add_argument("id", help="the experiment row's id")
    args = parser.parse_args(argv)
    found = [r for r in experiments.rows() if r.get("id") == args.id]
    if not found:
        print(f"no experiment row {args.id}")
        return 1
    result = reproduce(found[0])
    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("result") == "reproduced" else 1


if __name__ == "__main__":
    raise SystemExit(main())
