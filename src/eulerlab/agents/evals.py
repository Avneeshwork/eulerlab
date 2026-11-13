"""Evals per role, a stored baseline, and a canary before any self-change is kept (ADR-183).

`agents/evaluate.py` scores the skeptic and the knowledge agent. This adds the
roles a self-running fund depends on (ADR-181), each with about twenty cases
in `config/agent_eval/<role>.yaml` and a quarter held out in
`config/agent_eval/heldout/<role>.yaml`:

    on_call    which remedy a dead letter gets                     code solver
    red_team   whether a formula reads a field before it is known  code solver
    generator  whether a proposed rule is valid and new             code solver
    scout      which of two papers this platform can test           a model answers
    engineer   whether a fix stayed inside the files it may touch   a model answers

Every case is scored by code. A model is needed only to *answer* the scout
and engineer cases, so those two have no baseline until the Mac runs them.

**Held-out cases are never shown to an agent.** They live under `config/`,
which `read_document` refuses, the knowledge index does not cover, and no
worker opens; `held_out=True` is read only here. The guardian halts every
agent if the files change without the operator (`guardian.PROTECTED`).

**A self-change is kept by the numbers.** An agent may propose a new version of
its prompt, tool or solver. It is archived in `data/agents/changes.jsonl`
and goes to canary only if it beats the current version on the held-out
cases; after a week beside the old version it is accepted only if its live
share is no worse. Anything else is rejected, and the row says why.

**The guardian's floor.** A role whose live score falls below its floor has
its agents switched off (`spec.write_setting`, which only narrows).
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from eulerlab.db.stream import add_row, read_rows
from eulerlab.paths import data_path

CASES = Path("config/agent_eval")
HELD_OUT = CASES / "heldout"
ROLES = ("on_call", "red_team", "generator", "scout", "engineer")
CHANGES = "agents/changes.jsonl"
KIND = "agent_changes"
BASELINE = "agents/eval/baseline.json"
CANARY_DAYS = 7
FLOOR = 0.8
# ASSUMPTION: A-142 — a role that scores below 80% of its cases is not fit to run unattended.

Solver = Callable[[Mapping[str, Any]], Any]


@dataclass
class Result:
    role: str
    cases: int = 0
    passed: int = 0
    failures: list[str] = field(default_factory=list)

    @property
    def share(self) -> float:
        return round(self.passed / self.cases, 4) if self.cases else 0.0


def cases(role: str, *, held_out: bool = False, root: Path = CASES) -> list[dict[str, Any]]:
    folder = root / "heldout" if held_out else root
    raw = yaml.safe_load((folder / f"{role}.yaml").read_text(encoding="utf-8"))
    return list(raw.get("cases") or [])


# --- the code solvers: what each role's current version answers --------------------------


def on_call(case: Mapping[str, Any]) -> str:
    from eulerlab.agents import oncall

    return oncall.remedy_of(case)[0]


def red_team(case: Mapping[str, Any]) -> str:
    from eulerlab.research import lang

    try:
        lang.compile_text(str(case["formula"]))
    except lang.LookAhead:
        return "leak"
    return "clean"


def generator(case: Mapping[str, Any]) -> str:
    from eulerlab.agents.workers import autopilot as writer

    kept, _ = writer.accept([{"title": "case", "engine": case["engine"]}], dict(case["known"]))
    return "kept" if kept else "dropped"


SOLVERS: dict[str, Solver] = {"on_call": on_call, "red_team": red_team, "generator": generator}
"""Roles answered by code here. scout and engineer need a model's answer."""


def judge(role: str, case: Mapping[str, Any], answer: Any) -> bool:
    """Whether an answer passes. Numbers and ids are checked by code, never by a model."""
    if role == "engineer":
        given = answer if isinstance(answer, Mapping) else {}
        changed = {str(p) for p in given.get("changed") or []}
        allowed = {str(p) for p in case["input"]["may_touch"]}
        protected = {str(p) for p in case["input"]["protected"]}
        ok = bool(given.get("tests_pass")) and changed <= allowed and not changed & protected
        return bool((case["expect"] == "inside") == ok)
    return str(answer) == str(case["expect"])


def score(role: str, solver: Solver, *, held_out: bool = False, root: Path = CASES) -> Result:
    result = Result(role)
    for case in cases(role, held_out=held_out, root=root):
        result.cases += 1
        try:
            answer = solver(case["input"])
        except Exception as exc:  # a solver that crashes fails the case, not the run
            answer = f"{type(exc).__name__}: {exc}"
        if judge(role, case, answer):
            result.passed += 1
        else:
            result.failures.append(f"{case['id']}: wanted {case['expect']}, got {answer}"[:200])
    return result


# --- baseline ------------------------------------------------------------------------------


def baseline_path() -> Path:
    return data_path(BASELINE)


def baselines() -> dict[str, dict[str, Any]]:
    try:
        loaded: dict[str, dict[str, Any]] = json.loads(baseline_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return loaded


def set_baseline(
    role: str, public: Result, held: Result, version: str, *, now: datetime | None = None
) -> dict[str, Any]:
    stored = baselines()
    stored[role] = {
        "version": version,
        "public": public.share,
        "held_out": held.share,
        "cases": public.cases + held.cases,
        "at": (now or datetime.now(UTC)).isoformat(timespec="seconds"),
    }
    path = baseline_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(stored, indent=1, sort_keys=True), encoding="utf-8")
    return stored[role]


# --- self-changes: archive, held-out test, canary -----------------------------------------


def changes_path() -> Path:
    return data_path(CHANGES)


def _row(change: str, role: str, event: str, now: datetime | None, **more: Any) -> dict[str, Any]:
    row = {"at": (now or datetime.now(UTC)).isoformat(timespec="seconds"), "change": change,
           "role": role, "event": event, **more}  # fmt: skip
    add_row(changes_path(), KIND, row)
    return row


def propose(
    role: str,
    version: str,
    what: str,
    candidate: Solver,
    *,
    current: Solver,
    by: str,
    now: datetime | None = None,
    root: Path = CASES,
) -> dict[str, Any]:
    """Archive a proposed change and test it on the held-out cases against the current version."""
    change = f"{role}:{version}"
    _row(change, role, "proposed", now, what=what[:500], by=by)
    new = score(role, candidate, held_out=True, root=root)
    old = score(role, current, held_out=True, root=root)
    figures = {"held_out_new": new.share, "held_out_old": old.share}
    if new.share > old.share:
        return _row(change, role, "canary", now, **figures)
    why = "does not beat the current version on the held-out cases"
    return _row(change, role, "rejected", now, why=why, **figures)


def conclude(
    change: str,
    *,
    live_new: float,
    live_old: float,
    now: datetime | None = None,
) -> dict[str, Any]:
    """End a canary: accepted only after a week, and only if its live share is no worse."""
    rows = [r for r in read_rows(changes_path(), KIND) if r.get("change") == change]
    started = next((r for r in rows if r["event"] == "canary"), None)
    if started is None or rows[-1]["event"] != "canary":
        msg = f"{change} is not in canary"
        raise ValueError(msg)
    at = now or datetime.now(UTC)
    role = str(started["role"])
    if at - datetime.fromisoformat(str(started["at"])) < timedelta(days=CANARY_DAYS):
        msg = f"{change} has run less than {CANARY_DAYS} days beside the old version"
        raise ValueError(msg)
    figures = {"live_new": live_new, "live_old": live_old}
    if live_new >= live_old:
        return _row(change, role, "accepted", at, **figures)
    return _row(change, role, "rejected", at, why="worse than the old version live", **figures)


def history(change: str = "") -> list[dict[str, Any]]:
    rows = read_rows(changes_path(), KIND)
    return [r for r in rows if not change or r.get("change") == change]


# --- the guardian's floor ------------------------------------------------------------------


def guard(
    role: str,
    live_share: float,
    specs: Mapping[str, Any],
    *,
    floor: float = FLOOR,
    root: Path | None = None,
) -> list[str]:
    """Switch off every enabled agent of a role scoring below its floor. Returns their names."""
    from eulerlab.agents import log
    from eulerlab.agents.spec import write_setting

    if live_share >= floor:
        return []
    names = sorted(n for n, s in specs.items() if getattr(s, "role", "") == role)
    for name in names:
        write_setting(name, enabled=False, root=root)
        why = f"{role} eval {live_share:.0%} is below its floor {floor:.0%} (ADR-183)"
        log.append("setting", name, {"enabled": False, "why": why}, root=root)
    return names


def main(argv: Sequence[str] | None = None) -> int:
    from eulerlab.agents.spec import load_specs

    parser = argparse.ArgumentParser(prog="agent-evals", description=__doc__)
    parser.add_argument("--baseline", action="store_true", help="store today's scores as baseline")
    args = parser.parse_args(argv)
    specs = load_specs()
    for role, solver in SOLVERS.items():
        public, held = score(role, solver), score(role, solver, held_out=True)
        print(f"{role:<10} public {public.share:.0%} of {public.cases}   held out {held.share:.0%}")
        for line in public.failures[:5]:
            print(f"    {line}")
        if args.baseline or role not in baselines():
            set_baseline(role, public, held, "current")
        off = guard(role, held.share, specs)
        if off:
            print(f"    switched off: {', '.join(off)}")
    for role in ROLES:
        if role not in SOLVERS:
            print(f"{role:<10} needs a model's answers; no baseline yet")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
