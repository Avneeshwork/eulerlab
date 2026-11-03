"""Can every agent do the work it may be given? Checked by reading, not by running (ADR-124).

    make agents-capabilities

For each agent it checks:
    duties      it says what it does every day
    takes work  it lists at least one `can_do` skill
    reads it    the worker's source reads each skill's argument and fixed
                arguments (`ctx.args.get("<name>")`), so a task's value reaches it
    can start   an `auto` skill's agent is not terminal-only
    fallback    each skill has `words`, so its head can route to it without a model
    AI help     its head has a model budget, so a stuck task gets AI help (ADR-124),
                including for agents that work by fixed rules
For each head: it has a model budget and every agent under it is reachable by rules.
For each department: at least one skill the runner may start by itself.
For each doctor problem kind: who resolves it, and whether that agent lists the skill.

Each failing check is a gap, in words. A test holds the committed agents to
having none that are not listed in `KNOWN_GAPS`, each with the reason it stays.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from eulerlab.agents import org
from eulerlab.agents.spec import CEO, AgentSpec, load_specs

DOCTOR_OWNERS: dict[str, tuple[str, str, str]] = {
    "stalled": ("doctor", "", "the doctor closes the run itself; nothing to hand on"),
    "suspicious": (CEO, "", "flagged for you; no agent may judge its own result"),
    "model_down": (CEO, "", "noted and retried next run; a missing key or quota is yours to fix"),
    "data_refused": ("data", "check_dataset", "becomes a check_dataset task (agents/work.py)"),
    "code_error": ("engineering", "fix_code", "queued, then a fix_code task (agents/work.py)"),
}
"""Who resolves each kind of problem the doctor finds (`doctor.REMEDIES`)."""

KNOWN_GAPS: dict[str, str] = {}
"""Gaps accepted on purpose, by their exact text, with why. Empty: none are accepted."""


@dataclass(frozen=True)
class Check:
    who: str
    check: str
    ok: bool
    detail: str


def _source(worker: str) -> str:
    spec = importlib.util.find_spec(worker)
    if spec is None or spec.origin is None:
        return ""
    return Path(spec.origin).read_text(encoding="utf-8")


def reads_arg(source: str, name: str) -> bool:
    return re.search(rf"""args(?:\.get\(\s*|\[\s*)["']{re.escape(name)}["']""", source) is not None


def audit(specs: dict[str, AgentSpec] | None = None, chart: org.Org | None = None) -> list[Check]:
    specs = specs if specs is not None else load_specs()
    chart = chart if chart is not None else org.load_org()
    heads = {d.head.name: d.id for d in chart.departments}
    out: list[Check] = []
    for name, spec in sorted(specs.items()):
        out.append(Check(name, "duties", bool(spec.duties), f"{len(spec.duties)} listed"))
        if name in heads:
            out.append(
                Check(
                    name,
                    "model budget",
                    spec.uses_model and spec.daily_requests > 0,
                    f"{spec.daily_requests} requests a day; fixed rules when they run out",
                )
            )
            continue
        out.append(
            Check(
                name,
                "takes work",
                bool(spec.can_do),
                ", ".join(s.kind for s in spec.can_do) or "none",
            )
        )
        head = next((d.head.name for d in chart.departments if d.id == spec.reports_to), "")
        helper = specs.get(head)
        out.append(
            Check(
                name,
                "AI help when stuck",
                helper is not None and helper.uses_model and helper.daily_requests > 0,
                f"{head} asks its model to unstick a blocked task"
                + ("" if spec.uses_model else "; this agent itself works by fixed rules"),
            )
        )
        source = _source(spec.worker)
        for skill in spec.can_do:
            for arg in [*([skill.arg] if skill.arg else []), *skill.fixed]:
                out.append(
                    Check(
                        name,
                        f"reads {arg}",
                        reads_arg(source, arg),
                        f"{skill.kind}: {spec.worker} must read ctx.args[{arg!r}]",
                    )
                )
            if skill.auto:
                out.append(
                    Check(
                        name,
                        f"can start {skill.kind}",
                        not spec.options.get("cli_only"),
                        "auto, so the runner starts it"
                        if not spec.options.get("cli_only")
                        else "auto but terminal-only",
                    )
                )
            out.append(
                Check(
                    name,
                    f"fallback words for {skill.kind}",
                    bool(skill.words),
                    f"{len(skill.words)} words",
                )
            )
    for d in chart.departments:
        team = org.members(chart, specs, d.id)
        auto = [f"{n}.{s.kind}" for n, a in team.items() for s in a.can_do if s.auto and a.enabled]
        out.append(
            Check(
                d.head.name,
                "team can start work",
                bool(auto),
                ", ".join(auto) or "every skill waits for you",
            )
        )
    for kind, (owner, skill_kind, how) in sorted(DOCTOR_OWNERS.items()):
        if owner in (CEO, "doctor"):
            out.append(Check(f"doctor:{kind}", "has an owner", True, f"{owner}: {how}"))
            continue
        has = owner in specs and any(s.kind == skill_kind for s in specs[owner].can_do)
        out.append(Check(f"doctor:{kind}", "has an owner", has, f"{owner}.{skill_kind}: {how}"))
    return out


def gaps(checks: list[Check]) -> list[str]:
    return [f"{c.who}: {c.check} ({c.detail})" for c in checks if not c.ok]


def report(checks: list[Check] | None = None) -> dict[str, Any]:
    checks = checks if checks is not None else audit()
    found = gaps(checks)
    return {
        "checks": [asdict(c) for c in checks],
        "gaps": [g for g in found if g not in KNOWN_GAPS],
        "accepted": [{"gap": g, "why": KNOWN_GAPS[g]} for g in found if g in KNOWN_GAPS],
        "doctor": [
            {"kind": k, "owner": o, "skill": s, "how": h}
            for k, (o, s, h) in sorted(DOCTOR_OWNERS.items())
        ],
    }


def main() -> int:
    result = report()
    checks = result["checks"]
    passed = sum(1 for c in checks if c["ok"])
    print(f"{passed} of {len(checks)} capability checks pass")
    for c in checks:
        if not c["ok"]:
            print(f"  GAP  {c['who']:<18} {c['check']}: {c['detail']}")
    for row in result["doctor"]:
        print(
            f"  doctor {row['kind']:<13} -> {row['owner']}{'.' + row['skill'] if row['skill'] else ''}: {row['how']}"
        )
    return 0 if not result["gaps"] else 1


if __name__ == "__main__":
    sys.exit(main())
