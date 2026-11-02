"""The control room's routes: agents, briefs, the inbox, the log, data quality and the trade desk.

Everything here reads or writes the agent runtime's own files
(`data/agents/`, `data/quality/`, `data/desk/`). Nothing here places an
order, registers a hypothesis or spends a trial. A run started from the page
goes on a single background worker, so two clicks cannot start the same agent
twice and a long research run never holds a request open.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from eulerlab.agents import briefs, inbox, log, org, runtime
from eulerlab.agents import calendar as agent_calendar
from eulerlab.agents.spec import all_effective, load_specs, write_setting

router = APIRouter()

_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="agent")
_RUNNING: set[str] = set()
_LOCK = threading.Lock()


class SettingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    daily_requests: int | None = Field(default=None, ge=0, le=1000)


class BriefRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(max_length=briefs.MAX_CHARS)


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    args: dict[str, str] = Field(default_factory=dict)


class DecideRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approved", "dismissed"]
    note: str = Field(default="", max_length=500)


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=2000)
    history: list[dict[str, str]] = Field(default_factory=list, max_length=8)


class TicketDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approved", "rejected"]
    note: str = Field(default="", max_length=300)


def _ist_day() -> str:
    return runtime.ist_day(datetime.now(UTC))


@router.get("/api/agents")
def agents() -> dict[str, Any]:
    known = all_effective()
    day = _ist_day()
    rows = []
    for name, agent in sorted(known.items()):
        latest = runtime.latest_output(name, status=None)
        brief = briefs.current(name)
        rows.append(
            {
                "name": name,
                "title": agent.spec.title,
                "job": agent.spec.job,
                "enabled": agent.enabled,
                "switched": agent.switched,
                "schedule": agent.spec.schedule,
                "uses_model": agent.spec.uses_model,
                "daily_requests": agent.daily_requests,
                "ceiling": agent.spec.daily_requests,
                "used_today": log.requests_on(name, day),
                "never": agent.spec.never,
                "running": name in _RUNNING,
                "brief": brief.text if brief else "",
                "latest": (
                    {
                        "run_id": latest.run_id,
                        "status": latest.status,
                        "summary": latest.summary,
                        "started": latest.started,
                        "items": len(latest.items),
                        "model": latest.model,
                    }
                    if latest
                    else None
                ),
            }
        )
    every = briefs.current(briefs.ALL)
    ok, problem = log.verify()
    from eulerlab.research import agent_trials

    try:
        allowance = agent_trials.load_allowance()
        spent = agent_trials.spent_this_week()
        trials = {"per_week": allowance.per_week, "spent": spent}
    except (OSError, ValueError):
        trials = {"per_week": 0, "spent": 0}
    return {
        "ok": True,
        "trials": trials,
        "agents": rows,
        "brief_all": every.text if every else "",
        "inbox": len(inbox.pending()),
        "log_ok": ok,
        "log_problem": problem,
    }


# A run with no output whose last step is older than this has stopped without
# finishing (the process died, or the Mac slept through it). Longer than any
# single model request the runtime allows (10 minutes, `chat.complete_any`).
STALE_AFTER_S = 15 * 60


FINDINGS_SHOWN = 12
"""How many of a run's items the activity carries: enough for a card, not a whole report."""

_SEVERITY_ORDER = {"critical": 0, "warn": 1, "info": 2}


def _last_full_run(name: str, stopped: Path | None) -> tuple[str, list[dict[str, str]]]:
    """For a run that stopped without finishing: say so, and show the newest run that did finish.

    A stopped run is almost always the Mac sleeping or the app closing, not the
    agent failing (the doctor closes such runs after 3 hours, ADR-113). Showing
    only "failed" hid the full run before it (2026-11-01: the lab tested 22
    cards at 10:30 IST, then a second run stopped at 10:36 and the card said failed).
    """
    note = "This run stopped without finishing: the Mac slept or the app was closed."
    for output in runtime.outputs(name, limit=50):
        if stopped is not None and output.run_id == stopped.name:
            continue
        if output.status == "ok":
            return (
                f"{note} Last full run {output.started[:16].replace('T', ' ')} UTC: {output.summary}",
                _findings(output.items),
            )
    return note, []


def _findings(items: list[runtime.Item]) -> list[dict[str, str]]:
    """A run's items, worst first and alerts before findings, as the page shows them."""
    ordered = sorted(
        items,
        key=lambda i: (_SEVERITY_ORDER.get(i.severity, 3), 0 if i.kind == "alert" else 1),
    )
    return [
        {"kind": i.kind, "severity": i.severity, "title": i.title, "body": i.body, "ref": i.ref}
        for i in ordered
    ]


@router.get("/api/agents/org")
def agents_org() -> dict[str, Any]:
    """The company: you, the departments and their heads, the agents, the goals (ADR-123)."""
    try:
        chart = org.chart(org.load_org(), load_specs(), org.load_company())
    except (OSError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, **chart}


@router.get("/api/agents/calendar")
def agents_calendar(start: str = "", days: int = 7) -> dict[str, Any]:
    """Scheduled agent runs, what ran and what was missed, by IST day (ADR-123).

    `start` defaults to this week's Monday; `days` is 1 to 31.
    """
    # Imported here: `tools/` is importable because the server runs from the
    # repo root, and the schedule must come from the list that writes the plists.
    from tools import schedule_daily

    now = datetime.now(UTC)
    today = now.astimezone(runtime.IST).date()
    try:
        first = date.fromisoformat(start) if start else today - timedelta(days=today.weekday())
    except ValueError:
        return {"ok": False, "error": f"start must be YYYY-MM-DD, not {start!r}"}
    span = max(1, min(days, 31))
    try:
        makefile = Path("Makefile").read_text(encoding="utf-8")
        specs = load_specs()
        chart = org.chart(org.load_org(), specs, org.load_company())
    except (OSError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}
    built = agent_calendar.build(
        list(schedule_daily.JOBS.values()), makefile, specs, start=first, days=span, now=now
    )
    rows = [{"id": d["id"], "title": d["title"]} for d in chart["departments"]]
    rows.append({"id": "feeds", "title": "Data feeds (no agent)"})
    return {"ok": True, "rows": rows, **built}


@router.get("/api/agents/skeptic/targets")
def skeptic_targets() -> dict[str, Any]:
    """The stored results the skeptic can attack, for the picker on its card."""
    from eulerlab.agents.workers import skeptic

    return {"ok": True, "targets": skeptic.targets()}


@router.get("/api/agents/activity")
def agents_activity(steps: int = 40) -> dict[str, Any]:
    """What each agent is doing now, from its newest run's `progress.jsonl` (ADR-091).

    `state` is running, or the finished run's status, or `stopped` for a run
    that went quiet without writing its output.
    """
    known = all_effective()
    now = datetime.now(UTC)
    limit = max(1, min(steps, 200))
    rows: list[dict[str, Any]] = []
    feed: list[dict[str, str]] = []
    for name, agent in sorted(known.items()):
        run_dir = runtime.latest_run_dir(name)
        trail = runtime.progress(run_dir, limit) if run_dir else []
        state, summary, started = "idle", "", ""
        found: list[dict[str, str]] = []
        if run_dir is not None:
            output_path = run_dir / "output.json"
            if output_path.exists():
                try:
                    done = runtime.Output.model_validate_json(
                        output_path.read_text(encoding="utf-8")
                    )
                    state, summary, started = done.status, done.summary, done.started
                    found = _findings(done.items)
                    if isinstance(done.data, dict) and done.data.get("closed_by") == "doctor":
                        state = "stopped"
                except ValueError:
                    state = "failed"
            else:
                last = trail[-1]["at"] if trail else ""
                try:
                    quiet = (now - datetime.fromisoformat(last)).total_seconds() if last else 0.0
                except ValueError:
                    quiet = 0.0
                state = "running" if name in _RUNNING or quiet < STALE_AFTER_S else "stopped"
                started = trail[0]["at"] if trail else ""
        if name in _RUNNING:
            state = "running"
        if state == "stopped":
            summary, found = _last_full_run(name, run_dir)
        rows.append(
            {
                "name": name,
                "title": agent.spec.title,
                "job": agent.spec.job,
                "enabled": agent.enabled,
                "uses_model": agent.spec.uses_model,
                "cli_only": bool(agent.spec.options.get("cli_only")),
                "schedule": agent.spec.schedule,
                "state": state,
                "run_id": run_dir.name if run_dir else "",
                "started": started,
                "summary": summary,
                "now": trail[-1]["text"] if trail else "",
                "steps": trail,
                "findings": found[:FINDINGS_SHOWN],
                "findings_total": len(found),
            }
        )
        feed.extend({"agent": name, "title": agent.spec.title, **step} for step in trail)
    feed.sort(key=lambda row: row["at"], reverse=True)
    return {
        "ok": True,
        "running": sum(1 for row in rows if row["state"] == "running"),
        "agents": rows,
        "feed": feed[:limit],
    }


@router.get("/api/agents/inbox")
def agents_inbox() -> dict[str, Any]:
    return {"ok": True, "items": inbox.pending()}


@router.post("/api/agents/inbox/{item_id}")
def agents_decide(item_id: str, request: DecideRequest) -> dict[str, Any]:
    try:
        recorded = inbox.decide(item_id, request.decision, note=request.note)
    except (KeyError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}
    gate = _gate_on_approve(item_id) if recorded.decision == "approved" else ""
    return {"ok": True, "decision": recorded.decision, "at": recorded.at, "gate": gate}


_GATE_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="gate")
"""One gate run at a time: each validation reads the whole panel in its own process."""


def _gate_on_approve(item_id: str) -> str:
    """An approved idea-lab survivor goes to the gate with no further tap (ADR-116).

    Returns what happened, for the page: queued, or why not.
    """
    from eulerlab.research import promote

    found = inbox.find(item_id)
    if found is None:
        return ""
    agent, item = found
    try:
        card = promote.eligible(agent, item)
    except promote.Refused as exc:
        return "" if agent != "lab" else f"not sent to the gate: {exc}"
    _GATE_POOL.submit(promote.gate, item_id, card)
    return "sent to the gate: registering, validating and gating it now"


@router.get("/api/agents/promotions")
def agents_promotions() -> dict[str, Any]:
    """Approved survivors sent to the gate, newest first, with each verdict (ADR-116)."""
    from eulerlab.research import promote

    return {"ok": True, "promotions": promote.results()}


@router.get("/api/agents/log")
def agents_log(limit: int = 100) -> dict[str, Any]:
    entries = log.read()
    ok, problem = log.verify()
    return {
        "ok": True,
        "verified": ok,
        "problem": problem,
        "entries": [
            {"seq": e.seq, "at": e.at, "kind": e.kind, "agent": e.agent, "detail": e.detail}
            for e in entries[-max(1, min(limit, 500)) :][::-1]
        ],
    }


@router.post("/api/agents/knowledge/ask")
def knowledge_ask(request: AskRequest) -> dict[str, Any]:
    output = runtime.run(
        "knowledge", args={"question": request.question, "history": request.history[-8:]}
    )
    if output.status != "ok":
        return {"ok": False, "error": output.summary, "notes": output.notes}
    return {
        "ok": True,
        "answer": output.data.get("answer", ""),
        "tools": output.data.get("tools", []),
        "model": output.model,
        "requests": output.requests,
        "notes": output.notes,
    }


@router.get("/api/agents/market_brief/latest")
def latest_brief() -> dict[str, Any]:
    latest = runtime.latest_output("market_brief")
    if latest is None:
        return {"ok": False, "error": "no brief yet: run the market brief agent"}
    return {
        "ok": True,
        "text": latest.data.get("text", ""),
        "brief": latest.data.get("brief"),
        "mode": latest.data.get("mode"),
        "at": latest.started,
    }


@router.post("/api/agents/{name}/settings")
def agent_settings(name: str, request: SettingRequest) -> dict[str, Any]:
    try:
        changed = write_setting(
            name, enabled=request.enabled, daily_requests=request.daily_requests
        )
    except KeyError as exc:
        return {"ok": False, "error": str(exc)}
    log.append("setting", name, request.model_dump(exclude_none=True))
    return {"ok": True, "enabled": changed.enabled, "daily_requests": changed.daily_requests}


@router.post("/api/agents/{name}/brief")
def agent_brief(name: str, request: BriefRequest) -> dict[str, Any]:
    if name != briefs.ALL and name not in all_effective():
        return {"ok": False, "error": f"no agent named {name!r}"}
    saved = briefs.write(name, request.text, by="control-room")
    return {"ok": True, "id": saved.id, "at": saved.at}


@router.post("/api/agents/{name}/run")
def agent_run(name: str, request: RunRequest) -> dict[str, Any]:
    known = all_effective()
    if name not in known:
        return {"ok": False, "error": f"no agent named {name!r}"}
    if known[name].spec.options.get("cli_only"):
        # It reads the whole price panel; from here that would be a second copy in the API's memory.
        return {
            "ok": False,
            "error": f"{name} runs from your terminal, not this page: make agent NAME={name}",
        }
    with _LOCK:
        if name in _RUNNING:
            return {"ok": False, "error": f"{name} is already running"}
        _RUNNING.add(name)

    def work() -> None:
        try:
            runtime.run(name, args=dict(request.args))
        finally:
            with _LOCK:
                _RUNNING.discard(name)

    _POOL.submit(work)
    return {"ok": True, "started": True}


@router.get("/api/agents/{name}/outputs")
def agent_outputs(name: str, limit: int = 10) -> dict[str, Any]:
    return {
        "ok": True,
        "running": name in _RUNNING,
        "outputs": [o.model_dump() for o in runtime.outputs(name, limit=max(1, min(limit, 50)))],
    }


QUALITY_TTL_SECONDS = 120.0
"""How long one grading answers the Data quality screen. Grading reads every
manifest and the coverage table, 2.2 to 3.7 s on the operator's Mac
(2026-11-01, T-4369), and its inputs change when data lands, a few times a
day. `refresh=true` grades again at once."""

_QUALITY: dict[str, Any] = {}


@router.get("/api/quality")
def quality(refresh: bool = False) -> dict[str, Any]:
    import time

    from eulerlab.quality import contract, quarantine

    now = time.monotonic()
    cached = _QUALITY.get("grades")
    if refresh or cached is None or now - _QUALITY.get("at", 0.0) > QUALITY_TTL_SECONDS:
        cached = contract.grade_all()
        contract.save(cached)
        _QUALITY.update(grades=cached, at=now, graded_at=datetime.now(UTC).isoformat())
    grades = cached
    return {
        "ok": True,
        "graded_at": _QUALITY.get("graded_at"),
        "grades": [g.as_dict() for g in grades],
        "held": [
            {"dataset": r.dataset, "path": r.path, "reason": r.reason, "at": r.at, "by": r.by}
            for r in quarantine.held().values()
        ],
    }


@router.get("/api/desk/tickets")
def desk_tickets() -> dict[str, Any]:
    from eulerlab import desk

    try:
        found = desk.tickets()
    except Exception as exc:  # a broken state file must not blank the desk
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:300], "tickets": []}
    return {"ok": True, "tickets": [t.as_dict() for t in found]}


@router.post("/api/desk/tickets/{ticket_id}")
def desk_decide(ticket_id: str, request: TicketDecision) -> dict[str, Any]:
    from eulerlab import desk

    match = next((t for t in desk.tickets() if t.id == ticket_id), None)
    if match is None:
        return {"ok": False, "error": f"no open ticket {ticket_id}; the book may have moved on"}
    try:
        row = desk.decide(match, request.decision, request.note)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, **row}
