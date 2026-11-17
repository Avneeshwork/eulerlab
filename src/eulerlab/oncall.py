"""The on-call desk: dead letters get an allowlisted fix or a ticket, and books are reconciled (ADR-182).

Problems were found (the data agent, the watchdog, the doctor, the guardian)
but fixed by a person. On-call closes that loop with three fixed remedies and
nothing else:

    rerun_feed     the feed steps a dead letter names, through `agents/jobs.py`'s
                   allowlist (idempotent steps only, under the feed lock)
    reconcile      every paper book's journal against its broker; a break puts
                   that book into reduce-only and pages the operator
    trip_kill      trip one paper book's kill switch

Anything else becomes a ticket for the engineering agent with the error
attached. Every incident is one row in `data/agents/incidents.jsonl` and one
dated line under "Incidents" in the runbook for its kind, creating the
runbook when none exists. A dead letter is settled (`jobrun.settle_dead`)
only when its remedy worked or its ticket was opened, never edited.

**Reconciliation is the broker's word.** A difference between a book's journal
and its broker means we do not know what we hold; the book stops adding risk
(`loss_limits.start_reducing`) until the operator looks. No order is placed
to make the two agree (`oms/reconcile.py`). Paper books only: live books are
not enabled, and no agent may touch the live account (ADR-179).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from eulerlab import jobrun
from eulerlab.db.stream import add_row, read_rows
from eulerlab.paths import data_path

KIND = "incidents"
INCIDENTS = "agents/incidents.jsonl"
RUNBOOKS = Path("docs/RUNBOOKS")
WHO = "on-call"
REMEDIES = ("rerun_feed", "reconcile", "trip_kill")
RUNBOOK_FOR = {
    "rerun_feed": "daily-feed-is-stale.md",
    "reconcile": "position-mismatch.md",
    "trip_kill": "kill-switch-tripped.md",
    "ticket": "ticket-for-engineering.md",
}
NEW_RUNBOOK = """# {title}

**Symptom.** {symptom}

**Diagnosis.** The on-call agent's incident row in `data/agents/incidents.jsonl` has the error.

**Fix.** {fix}

**Prevention.** Read the incidents below for a pattern before changing anything.

## Incidents
"""
TITLES = {
    "position-mismatch.md": (
        "A paper book's positions differ from its broker",
        "`make oncall` or the close found a reconciliation break; the book is reduce-only.",
        "Read the break in the incident. Correct the local record from the broker's, then "
        "`loss_limits.stop_reducing` for the book. Never trade to make them agree.",
    ),
    "ticket-for-engineering.md": (
        "A dead letter on-call could not fix",
        "A job step failed after its retries and its remedy is not on the allowlist.",
        "The engineering agent has a task with the error. Fix the cause on a branch.",
    ),
}


def incidents_path() -> Path:
    return data_path(INCIDENTS)


@dataclass(frozen=True)
class Outcome:
    letter: str
    remedy: str
    ok: bool
    detail: str


def incident(
    kind: str,
    what: str,
    outcome: str,
    *,
    ok: bool,
    ref: str = "",
    now: datetime | None = None,
    runbooks: Path = RUNBOOKS,
) -> dict[str, Any]:
    """Write one incident row and its runbook line. Returns the row."""
    at = (now or datetime.now(UTC)).isoformat(timespec="seconds")
    name = RUNBOOK_FOR.get(kind, RUNBOOK_FOR["ticket"])
    row = {"at": at, "kind": kind, "what": what[:500], "outcome": outcome[:500], "ok": ok,
           "ref": ref, "runbook": f"docs/RUNBOOKS/{name}"}  # fmt: skip
    add_row(incidents_path(), KIND, row)
    note_in_runbook(
        runbooks / name, at[:10], f"{what[:200]} {'Fixed' if ok else 'Open'}: {outcome[:200]}"
    )
    return row


def note_in_runbook(path: Path, day: str, line: str) -> None:
    """Append a dated line under the runbook's Incidents heading, making either if missing."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        title, symptom, fix = TITLES.get(path.name, (path.stem.replace("-", " "), "", ""))
        text = NEW_RUNBOOK.format(title=title, symptom=symptom, fix=fix)
    if "## Incidents" not in text:
        text = text.rstrip() + "\n\n## Incidents\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + f"\n- {day} {line.strip()}\n", encoding="utf-8")


def incidents(since: datetime | None = None) -> list[dict[str, Any]]:
    rows = read_rows(incidents_path(), KIND)
    if since is None:
        return rows
    cut = since.isoformat(timespec="seconds")
    return [r for r in rows if str(r.get("at", "")) >= cut]


# --- the remedies -------------------------------------------------------------------------


def _rerun_feed(remedy: Mapping[str, Any]) -> tuple[bool, str]:
    from eulerlab.agents import jobs

    steps = [str(s) for s in remedy.get("rerun") or remedy.get("steps") or []]
    result = jobs.rerun(steps)
    return result.ok, result.detail


def _trip_kill(remedy: Mapping[str, Any]) -> tuple[bool, str]:
    from eulerlab.deploy import deployments
    from eulerlab.oms.killswitch import KillSwitch

    book = deployments.load(str(remedy["book"]))
    if book.mode != "paper":
        return False, "on-call trips paper books only"
    folder = book.folder
    folder.mkdir(parents=True, exist_ok=True)
    KillSwitch(folder / "KILL_SWITCH", folder / "killswitch_log.jsonl").trip(
        str(remedy.get("why") or "on-call"), by=WHO
    )
    return True, f"kill switch tripped for {book.id}"


def _reconcile(remedy: Mapping[str, Any]) -> tuple[bool, str]:
    found = reconcile_books()
    broken = [b for b in found if b["breaks"]]
    return not broken, f"{len(found)} book(s) reconciled, {len(broken)} with breaks"


ACTIONS: dict[str, Callable[[Mapping[str, Any]], tuple[bool, str]]] = {
    "rerun_feed": _rerun_feed,
    "reconcile": _reconcile,
    "trip_kill": _trip_kill,
}


def remedy_of(letter: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    """Which allowlisted remedy a dead letter asks for, or ('ticket', {})."""
    remedy = dict(letter.get("remedy") or {})
    if remedy.get("rerun"):
        return "rerun_feed", remedy
    kind = str(remedy.get("kind") or "")
    return (kind, remedy) if kind in ACTIONS else ("ticket", remedy)


def ticket(letter: Mapping[str, Any], *, now: datetime | None = None) -> str:
    """A task for the engineering agent, once per dead letter, with the error attached."""
    from eulerlab.agents import tasks

    key = jobrun.letter_key(letter)
    task = tasks.create(
        title=f"Fix {letter.get('name')} step {letter.get('step')}: failed after retries",
        owner="engineering",
        department="platform",
        created_by=WHO,
        detail=f"Dead letter {key}\njob {letter.get('job')}\n\n{letter.get('error', '')}",
        key=f"oncall|{key}",
        now=now,
    )
    return task.id


def handle(
    letters: Sequence[Mapping[str, Any]] | None = None,
    *,
    now: datetime | None = None,
    runbooks: Path = RUNBOOKS,
) -> list[Outcome]:
    """Work every unsettled dead letter once: an allowlisted remedy, else a ticket."""
    at = now or datetime.now(UTC)
    out = []
    for letter in jobrun.dead_letters() if letters is None else letters:
        key = jobrun.letter_key(letter)
        what = f"{letter.get('name')} {letter.get('step')}: {str(letter.get('error', ''))[:160]}"
        kind, remedy = remedy_of(letter)
        if kind == "ticket":
            try:
                tid = ticket(letter, now=at)
            except Exception as exc:  # a ticket that cannot be opened stays a dead letter
                out.append(Outcome(key, kind, False, f"{type(exc).__name__}: {exc}"))
                continue
            detail = f"ticket {tid} for engineering"
            incident(kind, what, detail, ok=False, ref=tid, now=at, runbooks=runbooks)
            jobrun.settle_dead(key, detail, now=at)
            out.append(Outcome(key, kind, False, detail))
            continue
        try:
            ok, detail = ACTIONS[kind](remedy)
        except Exception as exc:  # a remedy that raises is an open incident, not a crash
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        incident(kind, what, detail, ok=ok, ref=key, now=at, runbooks=runbooks)
        if ok:
            jobrun.settle_dead(key, f"{kind}: {detail}"[:300], now=at)
        out.append(Outcome(key, kind, ok, detail))
    return out


# --- reconciliation -----------------------------------------------------------------------


def reconcile_books(
    *,
    books: Sequence[Any] | None = None,
    oms_for: Callable[[Any], Any] | None = None,
    today: date | None = None,
    page: Callable[[str], Any] | None = None,
    now: datetime | None = None,
    runbooks: Path = RUNBOOKS,
) -> list[dict[str, Any]]:
    """Each active paper book's journal against its broker. A break means reduce-only and a page."""
    from eulerlab.deploy import deployments, runner
    from eulerlab.oms import reconcile
    from eulerlab.risk.limits import loss_limits

    at = now or datetime.now(UTC)
    day = today or at.date()
    found = []
    for book in deployments.all_deployments() if books is None else books:
        if book.mode != "paper" or book.status != "active":
            continue
        oms = (oms_for or runner.make_oms)(book)
        result = reconcile.reconcile(oms)
        breaks = [f"{b.kind} {b.symbol}: local {b.local}, broker {b.broker}" for b in result.breaks]
        row: dict[str, Any] = {"book": book.id, "strategy": book.strategy_id, "breaks": breaks}
        if breaks:
            why = f"reconciliation break: {'; '.join(breaks)[:300]}"
            loss_limits.start_reducing(book, day, why, by=WHO)
            text = f"{book.id} ({book.strategy_id}) is reduce-only: {why}"
            incident("reconcile", text, "reduce-only until you look", ok=False, ref=book.id,
                     now=at, runbooks=runbooks)  # fmt: skip
            (page or _page)(f"Euler Lab on-call: {text}")
            row["reducing"] = True
        found.append(row)
    return found


def _page(text: str) -> None:
    from eulerlab import notify

    notify.send(text[:900])


def worker(ctx: Any) -> Any:
    """On-call as an agent's run (the watchdog's, role on_call): letters first, then books."""
    from eulerlab.agents.runtime import Item, WorkerResult

    done = handle(now=ctx.now)
    books = reconcile_books(now=ctx.now)
    broken = [b for b in books if b["breaks"]]
    items = [
        Item(
            kind="alert" if not o.ok else "finding",
            title=f"on-call {o.remedy}: {'fixed' if o.ok else 'open'}"[:200],
            body=f"{o.letter}\n{o.detail}",
            severity="info" if o.ok else "warn",
        )
        for o in done
    ] + [
        Item(
            kind="alert",
            title=f"{b['book']} reduce-only: positions differ from the broker"[:200],
            body="\n".join(b["breaks"]),
            severity="critical",
            needs_approval=True,
        )
        for b in broken
    ]
    fixed = sum(o.ok for o in done)
    summary = (
        f"{len(done)} dead letter(s): {fixed} fixed, {len(done) - fixed} ticketed or open; "
        f"{len(books)} book(s) reconciled, {len(broken)} with breaks"
    )
    return WorkerResult(summary, items=items, data={"letters": [o.__dict__ for o in done],
                                                    "books": books})  # fmt: skip


def main(argv: Sequence[str] | None = None) -> int:
    from eulerlab.agents import runtime

    output = runtime.run("watchdog", worker=worker)
    print(f"{output.status}: {output.summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
