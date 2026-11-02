"""Today's plan for one agent: its scheduled runs, then its tasks (ADR-124).

    duties       what it does every day, from its definition
    scheduled    today's launchd slots that run it (agents/calendar.py), each
                 marked ran, upcoming, due, missed or not run
    tasks        its open tasks, due first, then oldest first
    to check     for a head: its agents' finished tasks waiting for its checklist
    done today   tasks it finished or passed up today

A plan is computed from the files each time it is read, so it cannot go stale
or show a run that did not happen. The head's run writes a copy into its run
folder (`plans.json`) as the record of what it planned.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from eulerlab.agents.runtime import IST
from eulerlab.agents.spec import CEO, AgentSpec
from eulerlab.agents.tasks import Task, owned_by

ScheduleSlots = list[dict[str, Any]]


def today_slots(
    specs: dict[str, AgentSpec], now: datetime, root: Path | None = None
) -> tuple[ScheduleSlots, str]:
    """Today's calendar slots and a note. The note says why the list is empty, if it is."""
    from eulerlab.agents import calendar

    try:
        # `tools/` is importable from the repo root, where the API and `make` run.
        from tools import schedule_daily

        makefile = Path("Makefile").read_text(encoding="utf-8")
    except (ImportError, OSError) as exc:
        return [], f"schedule not read: {type(exc).__name__}"
    day = now.astimezone(IST).date()
    built = calendar.build(
        list(schedule_daily.JOBS.values()), makefile, specs, start=day, days=1, now=now, root=root
    )
    return list(built["slots"]), ""


def _scheduled(name: str, slots: ScheduleSlots) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for slot in slots:
        for row in slot.get("agents", []):
            if row.get("name") != name:
                continue
            if row.get("run_id"):
                state = "ran"
            elif slot["state"] in ("ran", "partial"):
                state = "not run"
            else:
                state = str(slot["state"])
            out.append(
                {
                    "time": str(slot["time"]),
                    "job": str(slot["job"]),
                    "what": str(slot["what"]),
                    "state": state,
                    "run_id": str(row.get("run_id", "")),
                    "status": str(row.get("status", "")),
                }
            )
    return out


def _brief(task: Task, auto: bool = True) -> dict[str, Any]:
    return {
        "id": task.id,
        "title": task.title,
        "kind": task.kind,
        "status": task.status,
        "due": task.due,
        "parent": task.parent,
        "created_by": task.created_by,
        "returns": task.returns,
        "summary": task.summary,
        "run_id": task.run_id,
        "auto": auto,
        "args": dict(task.args),
    }


def for_agent(
    spec: AgentSpec,
    tasks: dict[str, Task],
    slots: ScheduleSlots,
    now: datetime,
    *,
    enabled: bool = True,
) -> dict[str, Any]:
    """One agent's day, as the org chart's side panel shows it."""
    day = now.astimezone(IST).date().isoformat()
    mine = owned_by(tasks, spec.name)
    finished = [
        t
        for t in tasks.values()
        if t.owner == spec.name and t.status in ("done", "closed") and t.updated[:10] == day
    ]
    check: list[Task] = []
    if spec.reports_to == CEO:
        dept = str(spec.options.get("department") or "")
        check = sorted(
            (t for t in tasks.values() if t.department == dept and t.status == "review"),
            key=lambda t: (t.due, t.created),
        )
    overdue = [t for t in mine if t.due < day]
    auto = {s.kind: s.auto for s in spec.can_do}
    return {
        "agent": spec.name,
        "title": spec.title,
        "day": day,
        "enabled": enabled,
        "duties": list(spec.duties),
        "scheduled": _scheduled(spec.name, slots),
        "tasks": [_brief(t, auto.get(t.kind, True)) for t in mine],
        "to_check": [_brief(t) for t in check],
        "done_today": [_brief(t) for t in finished],
        "overdue": len(overdue),
    }
