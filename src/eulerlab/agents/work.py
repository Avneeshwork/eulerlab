"""The work runner: turn hand-offs into tasks, run the tasks that may run, check them (ADR-124).

    make agents-work  (also inside agents-preopen and agents-ideas, after the heads)
      1. hand-offs   the doctor's code queue → a fix_code task for engineering;
                     the doctor's data refusals and the research agent's data
                     requests → a check_dataset task for data; a research card
                     the lab could not build for a named signal → a code_feature
                     task for engineering, at most `max_features` a day (ADR-127).
                     Same hand-off, same task id, so a re-run adds nothing.
      2. run         every assigned task due today or earlier whose skill is `auto`,
                     whose agent is on and not terminal-only: the agent runs once
                     with the skill's `fixed` arguments and the task's value
      3. check       its head runs the checklist on the result (workers/manager.check)
                     and passes finished parents up

A task whose skill is not `auto` (the lab's card tests spend trials; the
engineering agent writes branches with a paid model) is never started here.
It waits on the page for you; `run_one` is what your click calls.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from eulerlab.agents import doctor, org, runtime, tasks
from eulerlab.agents.spec import Effective, Skill, all_effective, home
from eulerlab.agents.workers import manager

RUNNER = "work"


def skill_for(task: tasks.Task, agents: dict[str, Effective]) -> Skill | None:
    agent = agents.get(task.owner)
    if agent is None:
        return None
    return next((s for s in agent.spec.can_do if s.kind == task.kind), None)


def run_args(task: tasks.Task, skill: Skill) -> dict[str, str]:
    """What the agent is started with: the skill's fixed arguments, the task's value
    and any `also` values it carries, and the task id."""
    args = dict(skill.fixed)
    for name in [skill.arg, *skill.also]:
        if name and task.args.get(name):
            args[name] = task.args[name]
    args["task"] = task.id
    return args


def _head(department: str) -> str:
    try:
        return org.head_of(org.load_org(), department)
    except (KeyError, OSError, ValueError):
        return RUNNER


def doctor_rows(root: Path, kind: str) -> list[dict[str, Any]]:
    """The doctor's log rows of one problem kind. Before ADR-124 nothing read the
    `data_refused` rows, although the doctor called them hand-offs (HISTORY #64)."""
    path = root / doctor.FOLDER / doctor.LOG
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("kind") == kind and row.get("run"):
            out.append(row)
    return out


def handoffs(root: Path | None = None, now: datetime | None = None) -> list[tasks.Task]:
    """Today's file hand-offs as tasks. Idempotent: each has a fixed key."""
    root = home(root)
    now = now or datetime.now(UTC)
    made: list[tasks.Task] = []
    queued = {p.file for p in doctor.queued(root)}
    for p in doctor.queued(root):
        made.append(
            tasks.create(
                title=f"Fix {p.file}",
                detail=f"The doctor queued a code error from {p.agent}'s run {p.run}: {p.error[:300]}",
                owner="engineering",
                department="platform",
                created_by="doctor",
                kind="fix_code",
                args={"file": p.file},
                key=f"doctor|{p.file}|{p.run}",
                root=root,
                now=now,
            )
        )
    # A queued file the engineering agent's own run has since handled leaves the
    # queue; its task is then finished, not left waiting for you.
    for t in tasks.load(root).values():
        if t.created_by == "doctor" and t.status == "assigned" and t.args.get("file") not in queued:
            tasks.record(
                t.id,
                "passed_up",
                "engineering",
                {
                    "summary": "handled by the engineering agent's scheduled run (left the doctor's queue)"
                },
                root=root,
                now=now,
            )
    for row in doctor_rows(root, "data_refused"):
        made.append(
            tasks.create(
                title=f"Data refused in {row.get('agent', '?')}'s run",
                detail=str(row.get("detail", ""))[:500],
                owner="data",
                department="platform",
                created_by="doctor",
                kind="check_dataset",
                args={"dataset": str(row.get("detail", ""))[:200]},
                key=f"doctor-data|{row.get('run', '')}",
                root=root,
                now=now,
            )
        )
    made += coding_handoffs(root, now)
    latest = runtime.latest_output("research", root)
    if latest is not None:
        for item in latest.items:
            if item.kind != "data_request":
                continue
            wanted = str(item.data.get("dataset") or item.title).strip()[:200]
            if not wanted:
                continue
            made.append(
                tasks.create(
                    title=f"Data for research: {wanted}",
                    detail=item.body[:500],
                    owner="data",
                    department="platform",
                    created_by="research",
                    kind="check_dataset",
                    args={"dataset": wanted},
                    key=f"data_request|{wanted.lower()}|{latest.run_id}",
                    root=root,
                    now=now,
                )
            )
    return made


MAX_FEATURES = 2
"""Signals the engineering agent may be asked to code in one IST day, when its
definition does not say (`options.max_features`)."""


def card_passed(card: Path) -> bool:
    """A research draft whose card was complete when drafted (`draft.json`), so the
    research agent's checks passed and only the missing signal stops the lab."""
    meta = card.parent / "draft.json"
    try:
        return bool(json.loads(meta.read_text(encoding="utf-8")).get("card") == "valid")
    except (OSError, ValueError):
        return False


def coding_handoffs(root: Path, now: datetime) -> list[tasks.Task]:
    """The lab's latest unbuildable research cards as code_feature tasks for engineering.

    Only a complete card with a named signal (an unnamed one would mean changing
    a pre-registered card). One task per signal, ever, by key. At most
    `max_features` new ones a day: each may spend paid requests (ADR-127).
    """
    from eulerlab.features import coded

    lab = runtime.latest_output("lab", root)
    if lab is None:
        return []
    try:
        engineering = all_effective(root).get("engineering")
    except (OSError, ValueError):
        engineering = None
    cap = int((engineering.spec.options if engineering else {}).get("max_features", MAX_FEATURES))
    today = runtime.ist_day(now)
    existing = tasks.load(root).values()
    started = sum(
        1
        for t in existing
        if t.kind == "code_feature" and runtime.ist_day(datetime.fromisoformat(t.created)) == today
    )
    keys = {t.args.get("feature") for t in existing if t.kind == "code_feature"}
    made: list[tasks.Task] = []
    for row in lab.data.get("unbuildable") or []:
        card = Path(str(row.get("card") or ""))
        for name in row.get("features") or []:
            name = str(name)
            if name in keys or not coded.NAME.match(name) or not card_passed(card):
                continue
            if started >= cap:
                return made
            made.append(
                tasks.create(
                    title=f"Code the signal {name} for a research card",
                    detail=f"The idea lab could not test {card.parent.name}: the library has no "
                    f"{name}. Code it in features/coded/ with its test; once you merge it, the "
                    "lab's next run tests the card.",
                    owner="engineering",
                    department="platform",
                    created_by="lab",
                    kind="code_feature",
                    args={"feature": name, "card": str(card)},
                    key=f"code_feature|{name}",
                    root=root,
                    now=now,
                )
            )
            keys.add(name)
            started += 1
    return made


def run_one(
    tid: str,
    *,
    by: str = RUNNER,
    root: Path | None = None,
    agents: dict[str, Effective] | None = None,
    now: datetime | None = None,
    worker: Any = None,
) -> tasks.Task:
    """Run one assigned task's agent, record the result, and have its head check it."""
    root = home(root)
    agents = agents if agents is not None else all_effective(root)
    task = tasks.load(root).get(tid)
    if task is None:
        msg = f"no task {tid!r}"
        raise tasks.Refused(msg)
    skill = skill_for(task, agents)
    if skill is None:
        msg = f"{task.owner} does not list {task.kind or 'this kind of task'} in can_do"
        raise tasks.Refused(msg)
    if agents[task.owner].spec.options.get("cli_only"):
        msg = f"{task.owner} runs from your terminal: make agent NAME={task.owner} ARGS='{' '.join(f'{k}={v}' for k, v in run_args(task, skill).items())}'"
        raise tasks.Refused(msg)
    head = _head(task.department)
    tasks.record(tid, "started", by, {"note": f"{task.owner} started"}, root=root, now=now)
    out = runtime.run(
        task.owner, args=run_args(task, skill), root=root, agents=agents, now=now, worker=worker
    )
    tasks.record(
        tid,
        "finished",
        task.owner,
        {"run_id": out.run_id, "run_status": out.status, "summary": out.summary[:600]},
        root=root,
        now=now,
    )
    finished = tasks.load(root)[tid]
    return manager.check(finished, head, root, now or datetime.now(UTC))


def runnable(
    known: dict[str, tasks.Task], agents: dict[str, Effective], day: str
) -> list[tasks.Task]:
    """Assigned tasks the runner may start by itself, due first."""
    out: list[tasks.Task] = []
    for t in sorted(known.values(), key=lambda t: (t.due, t.created)):
        if t.status != "assigned" or t.due > day or t.owner.startswith("head_"):
            continue
        skill = skill_for(t, agents)
        agent = agents.get(t.owner)
        if skill is None or agent is None or not skill.auto or not agent.enabled:
            continue
        if agent.spec.options.get("cli_only"):
            continue
        out.append(t)
    return out


def run_due(
    *,
    root: Path | None = None,
    departments: set[str] | None = None,
    now: datetime | None = None,
    worker: Any = None,
) -> list[tasks.Task]:
    """Every runnable task, then a roll-up by each head. Returns the tasks it ran."""
    root = home(root)
    when = now or datetime.now(UTC)
    agents = all_effective(root)
    ran: list[tasks.Task] = []
    for t in runnable(tasks.load(root), agents, runtime.ist_day(when)):
        if departments is not None and t.department not in departments:
            continue
        try:
            ran.append(run_one(t.id, root=root, agents=agents, now=now, worker=worker))
        except tasks.Refused:
            continue
    chart = org.load_org()
    for d in chart.departments:
        if departments is None or d.id in departments:
            manager.roll_up(d.head.name, root, when)
    return ran


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Turn hand-offs into tasks and run the due ones.")
    parser.add_argument("--department", action="append", default=None)
    parsed = parser.parse_args(argv)
    made = handoffs()
    ran = run_due(departments=set(parsed.department) if parsed.department else None)
    print(f"hand-offs: {len(made)} task(s) (new or existing); ran {len(ran)} task(s)")
    for t in ran:
        print(f"  {t.status:<9} {t.owner:<14} {t.title[:70]}  ({t.run_status})")
    waiting = [t for t in tasks.load().values() if t.status in ("assigned", "blocked")]
    for t in waiting:
        print(f"  waiting   {t.owner:<14} {t.status:<8} {t.title[:70]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
