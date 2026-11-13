"""Durable jobs: each step's result is kept, so a job that dies resumes where it stopped (ADR-174).

A nightly job used to be one function. Killed halfway, it started again from
the top: new cards written, the same rules screened again, and a gate run that
had finished but not been noted could be paid for twice. Here a job is a
sequence of named steps and every step leaves a row:

    job = jobrun.open("autopilot", "2026-11-13")
    cards = job.do("write", write_cards)             # runs, result kept
    result = job.do("gate:H-0231", gate, cost=jobrun.Cost(ledger_entries=2),
                    once=True, settle=look_in_the_ledger)
    job.finish("3 screened, 1 gated")

Run again with the same name and key and `do` returns each finished step's
kept result without running it. A finished job is not resumed: the next
`open` with that key starts run 2.

**Budgets are checked here, before a step starts**, against the operator's
constitution: a step that says it needs ledger entries is refused when the
week's cap would be passed, and one that says it costs rupees is refused when
the month's AI budget would be. A refused step raises `Refused`; the job is
not dead, it waits.

**A step that must not happen twice** (`once=True`) and was started but never
finished is not run again blind. `settle` looks at the world (the ledger, the
broker) and returns what happened, or None when nothing did. This is the order
journal's rule for an UNKNOWN order, applied to jobs.

A step that still fails after its retries leaves a row in the dead-letter
list, which the on-call agent reads (`oncall.py`, ADR-182).

Rows are in `data/jobs/<name>.jsonl`, or Postgres when the database is on.
A step's result must be JSON. Seconds taken are recorded for every step;
nothing here stops a step that runs long.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from eulerlab import constitution
from eulerlab.db.stream import add_row, read_rows
from eulerlab.llm import spend
from eulerlab.paths import data_path

KIND = "jobs"
DEAD = "dead"
BACKOFF = (2.0, 10.0, 60.0)
"""Seconds waited before the second, third and fourth try of a step."""


def root_dir() -> Path:
    return data_path("jobs")


class Refused(RuntimeError):
    """The constitution's budget does not cover this step. The job waits."""


class Unknown(RuntimeError):
    """A once-only step started, never finished, and cannot say what happened."""


@dataclass(frozen=True)
class Cost:
    """What a step will use, said before it starts so it can be refused."""

    ai_inr: float = 0.0
    ledger_entries: int = 0


def _now() -> datetime:
    return datetime.now(UTC)


def _file(name: str, root: Path | None) -> Path:
    return (root or root_dir()) / f"{name}.jsonl"


def dead_letter(
    name: str,
    step: str,
    error: str,
    *,
    job: str = "",
    remedy: Mapping[str, Any] | None = None,
    root: Path | None = None,
    now: datetime | None = None,
) -> None:
    """Leave a failed piece of work where the on-call agent will find it."""
    add_row(
        _file(DEAD, root),
        KIND,
        {
            "at": (now or _now()).isoformat(timespec="seconds"),
            "name": name,
            "job": job,
            "step": step,
            "error": error[:2000],
            "remedy": dict(remedy or {}),
            "event": "dead",
        },
    )


def settle_dead(
    key: str, how: str, *, root: Path | None = None, now: datetime | None = None
) -> None:
    """Note that a dead letter was dealt with, and how. The letter itself is never edited."""
    add_row(
        _file(DEAD, root),
        KIND,
        {
            "at": (now or _now()).isoformat(timespec="seconds"),
            "event": "settled",
            "key": key,
            "how": how,
        },
    )


def letter_key(row: Mapping[str, Any]) -> str:
    return f"{row['at']}|{row['name']}|{row['step']}"


def dead_letters(root: Path | None = None) -> list[dict[str, Any]]:
    """Dead letters nobody has dealt with yet, oldest first."""
    rows = read_rows(_file(DEAD, root), KIND)
    settled = {r["key"] for r in rows if r.get("event") == "settled"}
    return [r for r in rows if r.get("event") == "dead" and letter_key(r) not in settled]


class Job:
    """One run of a named job. Make it with `open`."""

    def __init__(
        self,
        name: str,
        key: str,
        run: int,
        done: dict[str, Any],
        started: set[str],
        *,
        root: Path | None,
        ledger_used: Callable[[], int] | None,
        sleep: Callable[[float], None],
        clock: Callable[[], datetime],
    ) -> None:
        self.name = name
        self.id = f"{name}:{key}:{run}"
        self.done = done
        self.started = started
        self.replayed: list[str] = []
        self._root = root
        self._ledger_used = ledger_used
        self._sleep = sleep
        self._clock = clock

    def _row(self, step: str, event: str, **more: Any) -> None:
        row = {"at": self._clock().isoformat(timespec="seconds"), "job": self.id}
        add_row(_file(self.name, self._root), KIND, {**row, "step": step, "event": event, **more})

    def allow(self, cost: Cost) -> None:
        """Raise `Refused` when the constitution's budget does not cover `cost`."""
        rules = constitution.load()
        if cost.ledger_entries:
            if rules.actions["use_ledger_entry"] != "act":
                msg = "the constitution does not let an agent use a ledger entry"
                raise Refused(msg)
            used = self._ledger_used() if self._ledger_used else 0
            cap = rules.caps.gate_entries_per_week
            if used + cost.ledger_entries > cap:
                msg = f"the week's ledger entries are used ({used} of {cap})"
                raise Refused(msg)
        if cost.ai_inr:
            spent = spend.month_spend_inr(self._clock())
            if spent + cost.ai_inr > rules.budget.monthly_ai_inr:
                msg = (
                    f"the month's AI budget would be passed (Rs {spent:,.0f} spent, "
                    f"Rs {cost.ai_inr:,.0f} wanted, Rs {rules.budget.monthly_ai_inr:,.0f} allowed)"
                )
                raise Refused(msg)

    def do(
        self,
        step: str,
        fn: Callable[[], Any],
        *,
        cost: Cost = Cost(),  # noqa: B008  (frozen, never changed)
        retries: int = 0,
        once: bool = False,
        settle: Callable[[], Any] | None = None,
    ) -> Any:
        """Run one step, or return its kept result when an earlier run finished it."""
        if step in self.done:
            self.replayed.append(step)
            return self.done[step]
        if once and step in self.started:
            found = settle() if settle is not None else None
            if found is not None:
                self._row(step, "done", output=found, settled=True)
                self.done[step] = found
                return found
            if settle is None:
                msg = f"{self.id} {step}: started before, never finished, and has no way to check"
                dead_letter(self.name, step, msg, job=self.id, root=self._root, now=self._clock())
                raise Unknown(msg)
        try:
            self.allow(cost)
        except Refused as exc:
            self._row(step, "refused", error=str(exc))
            raise
        for attempt in range(retries + 1):
            self._row(step, "started", attempt=attempt + 1)
            self.started.add(step)
            began = time.monotonic()
            try:
                output = fn()
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                self._row(step, "failed", attempt=attempt + 1, error=error[:2000])
                if attempt >= retries or once:
                    dead_letter(
                        self.name, step, error, job=self.id, root=self._root, now=self._clock()
                    )
                    raise
                self._sleep(BACKOFF[min(attempt, len(BACKOFF) - 1)])
                continue
            seconds = round(time.monotonic() - began, 3)
            # Through JSON now, so a first run and a resumed one hand back the same thing.
            output = json.loads(json.dumps(output, default=str))
            self._row(step, "done", output=output, seconds=seconds)
            self.done[step] = output
            return output
        raise AssertionError("unreachable")  # pragma: no cover

    def finish(self, summary: str = "") -> None:
        self._row("", "finished", summary=summary[:500])


def open(
    name: str,
    key: str,
    *,
    root: Path | None = None,
    ledger_used: Callable[[], int] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], datetime] = _now,
) -> Job:
    """The unfinished run of this job and key, with its kept results, or a new run."""
    prefix = f"{name}:{key}:"
    runs: dict[int, list[dict[str, Any]]] = {}
    for row in read_rows(_file(name, root), KIND):
        job = str(row.get("job", ""))
        if job.startswith(prefix):
            runs.setdefault(int(job[len(prefix) :]), []).append(row)
    last = max(runs) if runs else 0
    rows = runs.get(last, [])
    if not rows or any(r["event"] == "finished" for r in rows):
        return Job(
            name, key, last + 1, {}, set(), root=root,
            ledger_used=ledger_used, sleep=sleep, clock=clock,
        )  # fmt: skip
    done = {str(r["step"]): r.get("output") for r in rows if r["event"] == "done"}
    started = {str(r["step"]) for r in rows if r["event"] == "started"}
    return Job(
        name, key, last, done, started, root=root,
        ledger_used=ledger_used, sleep=sleep, clock=clock,
    )  # fmt: skip


def status(name: str, root: Path | None = None) -> dict[str, Any]:
    """The latest run of a job: its id, steps done, and whether it finished."""
    rows = read_rows(_file(name, root), KIND)
    if not rows:
        return {"job": "", "done": [], "finished": False}
    job = rows[-1]["job"]
    mine = [r for r in rows if r["job"] == job]
    return {
        "job": job,
        "done": [r["step"] for r in mine if r["event"] == "done"],
        "finished": any(r["event"] == "finished" for r in mine),
        "refused": [r["step"] for r in mine if r["event"] == "refused"],
    }
