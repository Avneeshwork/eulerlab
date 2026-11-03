"""Tasks: who owes what to whom, kept as an append-only list of events (ADR-124).

    you (CEO) ── create, owner = a head ─▶ open
    head splits it ─▶ subtasks, owner = an agent ─▶ assigned
    work runner starts the agent ─▶ doing ─▶ finished ─▶ review
    head checks it against the checklist ─▶ done │ sent back (at most twice) │ blocked
    blocked ─▶ the head asks the model for help, once ─▶ assisted (fixed, back to assigned)
                                                      └▶ a diagnosis for you (stays blocked)
    every subtask done ─▶ the parent is passed up to you ─▶ done ─▶ you close it

Everything lives in `data/agents/tasks.jsonl`, one event per line. Nothing is
edited or deleted; a task's state is the fold of its events, so the page can
show the whole history of every task, and so can a diff. Each event is also
written to the hash-chained agent log (`agents/log.py`).

An event that does not fit the task's state is refused (`ALLOWED`), so a task
cannot be closed twice, finished before it started, or sent back a third time.

A task never acts by itself. An agent acts only when the work runner or the
page runs it, with the arguments its definition's `can_do` allows.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, get_args

from eulerlab.agents import log
from eulerlab.agents.runtime import ist_day
from eulerlab.agents.spec import home

FILE = "tasks.jsonl"
LOCK = "tasks.lock"
MAX_RETURNS = 2
"""A head sends a task back at most this many times; the next failure blocks it for you."""
MAX_ASSISTS = 1
"""A head asks the model to unstick a blocked task this many times on its own; asking
for help on the page allows one more each time."""

Status = Literal["open", "assigned", "doing", "review", "done", "blocked", "closed", "cancelled"]
Event = Literal[
    "created",
    "assigned",
    "started",
    "finished",
    "accepted",
    "sent_back",
    "blocked",
    "passed_up",
    "closed",
    "reopened",
    "cancelled",
    "assisted",
    "help_asked",
    "note",
]
ACTIVE: frozenset[str] = frozenset({"open", "assigned", "doing", "review", "blocked"})
"""States that still need someone. `done` waits only for you to close it."""

ALLOWED: dict[str, frozenset[str]] = {
    "assigned": frozenset({"open", "assigned", "blocked", "review"}),
    "started": frozenset({"assigned"}),
    "finished": frozenset({"doing"}),
    "accepted": frozenset({"review"}),
    "sent_back": frozenset({"review"}),
    "blocked": frozenset({"open", "assigned", "doing", "review"}),
    "passed_up": frozenset({"open", "assigned", "blocked"}),
    "closed": frozenset({"done"}),
    "reopened": frozenset({"done", "blocked", "cancelled", "closed"}),
    "cancelled": frozenset({"open", "assigned", "review", "blocked", "done"}),
    "assisted": frozenset({"blocked"}),
    "help_asked": frozenset({"blocked"}),
    "note": frozenset(get_args(Status)),
}
"""Which states each event may follow. `created` has no state before it."""

NEXT: dict[str, Status] = {
    "assigned": "assigned",
    "started": "doing",
    "finished": "review",
    "accepted": "done",
    "sent_back": "assigned",
    "blocked": "blocked",
    "passed_up": "done",
    "closed": "closed",
    "cancelled": "cancelled",
    "assisted": "assigned",
}


class Refused(ValueError):
    """The event does not fit the task's state, or the task does not exist."""


@dataclass
class Task:
    id: str
    title: str
    detail: str
    owner: str
    """A head's or an agent's name."""
    department: str
    created_by: str
    """`ceo`, a head, an agent, or `doctor`."""
    created: str
    due: str
    """IST day, YYYY-MM-DD."""
    kind: str = ""
    """A `can_do` kind once a head has matched it; empty while it is the head's."""
    parent: str = ""
    args: dict[str, str] = field(default_factory=dict)
    status: Status = "open"
    returns: int = 0
    run_id: str = ""
    run_status: str = ""
    summary: str = ""
    planned_by: str = ""
    """`model` or `rules`: how the head split it (set on the parent)."""
    assists: int = 0
    """Times the head asked the model to unstick it (a fix or a diagnosis)."""
    help_wanted: bool = False
    """You asked for AI help on the page and the head has not tried yet."""
    updated: str = ""
    history: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _path(root: Path) -> Path:
    return root / FILE


@contextmanager
def _locked(root: Path) -> Iterator[None]:
    """One writer at a time across the API's thread and a terminal run."""
    root.mkdir(parents=True, exist_ok=True)
    with (root / LOCK).open("a", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _events(root: Path) -> list[dict[str, Any]]:
    path = _path(root)
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("task") and row.get("event"):
            out.append(row)
    return out


def _fold(events: list[dict[str, Any]]) -> dict[str, Task]:
    tasks: dict[str, Task] = {}
    for row in events:
        tid, event, data = str(row["task"]), str(row["event"]), dict(row.get("data") or {})
        mark = {"at": row.get("at", ""), "event": event, "by": row.get("by", ""), **data}
        if event == "created":
            fields = {k: v for k, v in data.items() if k in Task.__dataclass_fields__}
            task = Task(**fields)
            task.updated = str(row.get("at", ""))
            task.history.append(mark)
            tasks[tid] = task
            continue
        task_or_none = tasks.get(tid)
        if task_or_none is None:
            continue
        task = task_or_none
        if event in NEXT:
            task.status = NEXT[event]
        if event == "reopened":
            task.status = "open" if task.owner.startswith("head_") else "assigned"
            task.returns = 0
        if event == "sent_back":
            task.returns += 1
        if event == "help_asked":
            task.help_wanted = True
        if event == "assisted" or (event == "note" and data.get("assist") == "diagnosis"):
            task.assists += 1
            task.help_wanted = False
        if event == "note" and data.get("assist") == "unavailable":
            task.help_wanted = False
        if event == "assisted":
            task.returns = 0
        for key in ("owner", "kind", "run_id", "run_status", "summary", "planned_by"):
            if key in data:
                setattr(task, key, str(data[key]))
        if "args" in data and isinstance(data["args"], dict):
            task.args = {str(k): str(v) for k, v in data["args"].items()}
        task.updated = str(row.get("at", ""))
        task.history.append(mark)
    return tasks


def load(root: Path | None = None) -> dict[str, Task]:
    """Every task, by id, in the order it was created."""
    return _fold(_events(home(root)))


def _append(root: Path, row: dict[str, Any]) -> None:
    with _path(root).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True, default=str) + "\n")


def task_id(key: str) -> str:
    return "T-" + hashlib.sha256(key.encode()).hexdigest()[:10]


def create(
    *,
    title: str,
    owner: str,
    department: str,
    created_by: str,
    detail: str = "",
    due: str = "",
    kind: str = "",
    args: dict[str, str] | None = None,
    parent: str = "",
    key: str = "",
    root: Path | None = None,
    now: datetime | None = None,
) -> Task:
    """Add a task. `key` makes it idempotent: the same key returns the same task.

    A task owned by a head starts `open` (to be split); one owned by an agent
    starts `assigned`.
    """
    root = home(root)
    now = now or datetime.now(UTC)
    title = " ".join(title.split())[:200]
    if not title:
        msg = "a task needs a title"
        raise Refused(msg)
    tid = task_id(key or f"{created_by}|{parent}|{owner}|{title}|{now.isoformat()}")
    with _locked(root):
        existing = load(root)
        if tid in existing:
            return existing[tid]
        if parent and parent not in existing:
            msg = f"no parent task {parent!r}"
            raise Refused(msg)
        task = Task(
            id=tid,
            title=title,
            detail=detail.strip()[:2000],
            owner=owner,
            department=department,
            created_by=created_by,
            created=now.isoformat(timespec="seconds"),
            due=due or ist_day(now),
            kind=kind,
            parent=parent,
            args=dict(args or {}),
            status="open" if owner.startswith("head_") else "assigned",
        )
        data = task.as_dict()
        data.pop("history")
        data.pop("updated")
        at = now.isoformat(timespec="seconds")
        _append(root, {"at": at, "task": tid, "event": "created", "by": created_by, "data": data})
    log.append(
        "task",
        created_by,
        {"task": tid, "event": "created", "owner": owner, "title": title},
        root=root,
        at=now,
    )
    return load(root)[tid]


def record(
    tid: str,
    event: Event,
    by: str,
    data: dict[str, Any] | None = None,
    *,
    root: Path | None = None,
    now: datetime | None = None,
) -> Task:
    """Add one event to a task. Raises `Refused` if it does not fit the task's state."""
    root = home(root)
    now = now or datetime.now(UTC)
    payload = dict(data or {})
    with _locked(root):
        known = load(root)
        task = known.get(tid)
        if task is None:
            msg = f"no task {tid!r}"
            raise Refused(msg)
        if task.status not in ALLOWED[event]:
            msg = f"{tid} is {task.status}; it cannot be {event.replace('_', ' ')}"
            raise Refused(msg)
        if event == "sent_back" and task.returns >= MAX_RETURNS:
            msg = f"{tid} was already sent back {MAX_RETURNS} times; block it instead"
            raise Refused(msg)
        at = now.isoformat(timespec="seconds")
        _append(root, {"at": at, "task": tid, "event": event, "by": by, "data": payload})
    note = str(payload.get("note") or payload.get("summary") or "")[:200]
    log.append("task", by, {"task": tid, "event": event, "note": note}, root=root, at=now)
    return load(root)[tid]


def children(tasks: dict[str, Task], parent: str) -> list[Task]:
    """The subtasks of the parent's current round: those made since it was last reopened."""
    owner = tasks.get(parent)
    since = ""
    if owner is not None:
        since = max(
            (str(e.get("at", "")) for e in owner.history if e.get("event") == "reopened"),
            default="",
        )
    return [t for t in tasks.values() if t.parent == parent and t.created >= since]


def reopen(
    tid: str, by: str, note: str = "", *, root: Path | None = None, now: datetime | None = None
) -> Task:
    """Give a task back to its owner. A parent's unfinished subtasks are cancelled first,
    so its head splits it afresh instead of waiting on the old round."""
    root = home(root)
    known = load(root)
    for sub in children(known, tid):
        if sub.status in ("open", "assigned", "review", "blocked"):
            record(sub.id, "cancelled", by, {"note": f"parent {tid} reopened"}, root=root, now=now)
    return record(tid, "reopened", by, {"note": note[:300]}, root=root, now=now)


def owned_by(tasks: dict[str, Task], owner: str, *, active: bool = True) -> list[Task]:
    """An owner's tasks, due first, then oldest first."""
    found = [t for t in tasks.values() if t.owner == owner and (not active or t.status in ACTIVE)]
    return sorted(found, key=lambda t: (t.due, t.created))
