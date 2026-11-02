"""The company calendar: when each agent is scheduled, what it did, and what it missed (ADR-122).

    tools/schedule_daily.JOBS ── job: hour, minute, weekdays, `make <target>`
            │
    Makefile recipe of <target> ── `eulerlab.agents.runtime <agent>` lines ──► agents in the job
            │
    data/agents/<agent>/<run>/output.json ──► runs in the window
            │
            ▼
    one slot per job per day: ran · partial · due · missed · upcoming · feed
    and every run that matched no slot (Run button, a brief rewritten by `make daily`)

The schedule is read from the same job list that writes the launchd plists, and
which agents a job runs is read from the Makefile recipe it calls, so the
calendar cannot show a schedule that does not run. It only reads: nothing here
moves a job, starts an agent or edits a plist.

Times are IST. launchd fires on the Mac's local clock, which is IST for this
operator (A-092).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from eulerlab.agents.runtime import IST, outputs
from eulerlab.agents.spec import AgentSpec, home

EARLY = timedelta(minutes=10)
"""A run this much before its slot still counts for it (a clock a little fast)."""
GRACE = timedelta(hours=3)
"""After this, a slot with no run is missed rather than due. launchd runs a job
on wake if the Mac slept through it, so a late run is normal."""
RUNS_PER_AGENT = 400
"""Newest run folders read per agent; about a month of the busiest agent."""


class JobLike(Protocol):
    """The fields of `tools.schedule_daily.Job` the calendar reads."""

    @property
    def name(self) -> str: ...
    @property
    def command(self) -> str: ...
    @property
    def hour(self) -> int: ...
    @property
    def minute(self) -> int: ...
    @property
    def weekdays(self) -> tuple[int, ...]: ...
    @property
    def what(self) -> str: ...


@dataclass(frozen=True)
class Run:
    agent: str
    run_id: str
    started: datetime
    """IST."""
    status: str
    summary: str


def _recipe(makefile: str, target: str) -> list[str]:
    """The tab-indented lines under `target:` in the Makefile."""
    lines = makefile.splitlines()
    head = re.compile(rf"^{re.escape(target)}\s*:(?!=)")
    for i, line in enumerate(lines):
        if head.match(line):
            out: list[str] = []
            for nxt in lines[i + 1 :]:
                if not nxt.startswith("\t"):
                    break
                out.append(nxt)
            return out
    return []


def agents_in_job(command: str, makefile: str) -> list[str]:
    """Which agents a scheduled command runs, read from the Makefile, in order."""
    match = re.search(r"\bmake\s+([A-Za-z0-9_.-]+)(.*)", command)
    if match is None:
        return []
    target, rest = match.group(1), match.group(2)
    if target == "agent":
        named = re.search(r"\bNAME=([a-z0-9_]+)", rest)
        return [named.group(1)] if named else []
    found: list[str] = []
    for line in _recipe(makefile, target):
        for name in re.findall(r"eulerlab\.agents\.runtime\s+([a-z][a-z0-9_]*)", line):
            if name not in found:
                found.append(name)
    return found


def _started(run_started: str) -> datetime | None:
    try:
        moment = datetime.fromisoformat(run_started)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(IST)


def runs_between(names: list[str], first: date, last: date, root: Path | None = None) -> list[Run]:
    """Every finished run of these agents that started on an IST day in [first, last]."""
    found: list[Run] = []
    for name in names:
        for out in outputs(name, root=home(root), limit=RUNS_PER_AGENT):
            moment = _started(out.started)
            if moment is None or not first <= moment.date() <= last:
                continue
            found.append(Run(name, out.run_id, moment, out.status, out.summary[:200]))
    found.sort(key=lambda r: (r.started, r.agent))
    return found


def _fires_on(job: JobLike, day: date) -> bool:
    # launchd and isoweekday agree: 1 is Monday, 7 is Sunday.
    return not job.weekdays or day.isoweekday() in job.weekdays


def build(
    jobs: Sequence[JobLike],
    makefile: str,
    specs: dict[str, AgentSpec],
    *,
    start: date,
    days: int,
    now: datetime,
    root: Path | None = None,
) -> dict[str, Any]:
    """The calendar for `days` IST days from `start`, as the AI tab draws it."""
    # ASSUMPTION: A-092 - launchd fires on the Mac's clock, which is IST, so a
    # job's hour and minute are placed in IST.
    last = start + timedelta(days=days - 1)
    now_ist = now.astimezone(IST)
    dept = {name: spec.reports_to for name, spec in specs.items()}
    job_agents = {job.name: agents_in_job(job.command, makefile) for job in jobs}

    # Every (agent, day) slot time, so a run is matched to the slot it follows
    # and not to a later one the same day (data runs at 08:45 and at 16:15).
    slots: list[tuple[datetime, JobLike]] = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        for job in jobs:
            if _fires_on(job, day):
                at = datetime(day.year, day.month, day.day, job.hour, job.minute, tzinfo=IST)
                slots.append((at, job))
    slots.sort(key=lambda s: (s[0], s[1].name))

    names = sorted({a for agents in job_agents.values() for a in agents} | set(specs))
    runs = runs_between(names, start, last, root)
    used: set[str] = set()

    def window_end(agent: str, at: datetime) -> datetime:
        later = [
            s_at
            for s_at, s_job in slots
            if s_at > at and s_at.date() == at.date() and agent in job_agents[s_job.name]
        ]
        if later:
            return min(later) - EARLY
        return datetime(at.year, at.month, at.day, tzinfo=IST) + timedelta(days=1)

    out_slots: list[dict[str, Any]] = []
    for at, job in slots:
        agents = job_agents[job.name]
        rows: list[dict[str, str]] = []
        for agent in agents:
            end = window_end(agent, at)
            match = next(
                (
                    r
                    for r in runs
                    if r.agent == agent and r.run_id not in used and at - EARLY <= r.started < end
                ),
                None,
            )
            if match is not None:
                used.add(match.run_id)
            rows.append(
                {
                    "name": agent,
                    "department": dept.get(agent, ""),
                    "run_id": match.run_id if match else "",
                    "status": match.status if match else "",
                }
            )
        ran = sum(1 for r in rows if r["run_id"])
        if not agents:
            state = "feed"
        elif at > now_ist:
            state = "upcoming"
        elif ran == len(agents):
            state = "ran"
        elif ran:
            state = "partial"
        elif now_ist < at + GRACE:
            state = "due"
        else:
            state = "missed"
        out_slots.append(
            {
                "day": at.date().isoformat(),
                "time": at.strftime("%H:%M"),
                "job": job.name,
                "what": job.what,
                "agents": rows,
                "departments": sorted({r["department"] for r in rows if r["department"]}),
                "state": state,
            }
        )

    return {
        "start": start.isoformat(),
        "days": [(start + timedelta(days=i)).isoformat() for i in range(days)],
        "today": now_ist.date().isoformat(),
        "now": now_ist.strftime("%H:%M"),
        "slots": out_slots,
        "runs": [
            {
                "agent": r.agent,
                "department": dept.get(r.agent, ""),
                "run_id": r.run_id,
                "day": r.started.date().isoformat(),
                "time": r.started.strftime("%H:%M"),
                "status": r.status,
                "summary": r.summary,
                "scheduled": r.run_id in used,
            }
            for r in runs
        ],
    }
