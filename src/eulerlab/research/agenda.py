"""The research agenda: open questions, the evidence on each, and the next step (#164, ADR-191).

The research agent took one topic a day in turn, and the autopilot got twelve
papers shuffled by date. Nothing held what was being asked, what had been
learned about it, or what to try next, so each night started cold and the
prompt grew with every card ever tried. A research group keeps a notebook:
this is it, as data.

`data/derived/agenda.jsonl`, appended only. Each line is an event:

    ask      a new question: id, text, why, author
    finding  what a run learned about a question: text, refs (screens, cards, traces)
    status   open -> answered | dead, with why
    next     the next experiment to run on it

`questions()` folds the events into the current state of each question. The
operator may add or close questions too (`make agenda ASK="..."`); an agent's
event and the operator's are the same kind of line, with the author named.

The research loop reads the open questions (`summary`), picks one, and writes
back what it found, so the next night starts from there. Questions with the
fewest findings and the oldest last touch come first: unexplored ground before
re-treading.
"""

from __future__ import annotations

import argparse
import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from eulerlab.db.stream import add_row, read_rows
from eulerlab.paths import data_path

PATH = "derived/agenda.jsonl"
KIND = "agenda"
Status = Literal["open", "answered", "dead"]
STATUSES: tuple[Status, ...] = ("open", "answered", "dead")


def _path(path: Path | None) -> Path:
    return path if path is not None else data_path(PATH)


@dataclass
class Question:
    id: str
    text: str
    why: str
    author: str
    at: str
    status: Status = "open"
    findings: list[dict[str, Any]] = field(default_factory=list)
    next: str = ""
    touched: str = ""

    def line(self) -> str:
        last = self.findings[-1]["text"][:160] if self.findings else "nothing yet"
        out = f"[{self.id}] {self.text} ({self.status}, {len(self.findings)} finding(s)); last: {last}"
        return out + (f"; next: {self.next}" if self.next else "")


def _append(row: dict[str, Any], path: Path | None, now: datetime | None) -> dict[str, Any]:
    row = {"at": (now or datetime.now(UTC)).isoformat(timespec="seconds"), **row}
    add_row(_path(path), KIND, row)
    return row


def events(path: Path | None = None) -> list[dict[str, Any]]:
    """Every agenda event, oldest first (a file, or Postgres when it is on)."""
    return [r for r in read_rows(_path(path), KIND) if isinstance(r, dict)]


def questions(path: Path | None = None) -> dict[str, Question]:
    """Every question in its current state, by id, in the order asked."""
    out: dict[str, Question] = {}
    for row in events(path):
        kind, qid = row.get("kind"), str(row.get("id") or "")
        if kind == "ask" and qid not in out:
            out[qid] = Question(
                qid,
                str(row.get("text") or ""),
                str(row.get("why") or ""),
                str(row.get("author") or ""),
                str(row.get("at") or ""),
                touched=str(row.get("at") or ""),
            )
            continue
        q = out.get(qid)
        if q is None:
            continue
        q.touched = str(row.get("at") or q.touched)
        if kind == "finding":
            q.findings.append(
                {
                    "at": row.get("at"),
                    "text": row.get("text"),
                    "refs": row.get("refs") or [],
                    "by": row.get("author"),
                }
            )
        elif kind == "status" and row.get("status") in STATUSES:
            q.status = row["status"]
        elif kind == "next":
            q.next = str(row.get("text") or "")
    return out


def ask(
    text: str, why: str, *, author: str, path: Path | None = None, now: datetime | None = None
) -> str:
    """Add a question, or return the id of the same question already asked."""
    clean = " ".join(text.split())
    if len(clean) < 10:
        msg = "a question needs at least ten characters"
        raise ValueError(msg)
    qid = "Q-" + hashlib.sha256(clean.lower().encode()).hexdigest()[:6]
    if qid in questions(path):
        return qid
    _append(
        {"kind": "ask", "id": qid, "text": clean[:300], "why": why.strip()[:300], "author": author},
        path,
        now,
    )
    return qid


def note(
    qid: str,
    finding: str,
    *,
    author: str,
    refs: Sequence[str] = (),
    status: Status | None = None,
    next_step: str = "",
    path: Path | None = None,
    now: datetime | None = None,
) -> Question:
    """Record what was learned about a question, and optionally its new status and next step."""
    held = questions(path)
    if qid not in held:
        msg = f"no question {qid}"
        raise KeyError(msg)
    if finding.strip():
        _append(
            {
                "kind": "finding",
                "id": qid,
                "text": finding.strip()[:600],
                "refs": list(refs)[:20],
                "author": author,
            },
            path,
            now,
        )
    if status is not None:
        if status not in STATUSES:
            msg = f"status must be one of {', '.join(STATUSES)}"
            raise ValueError(msg)
        _append({"kind": "status", "id": qid, "status": status, "author": author}, path, now)
    if next_step.strip():
        _append(
            {"kind": "next", "id": qid, "text": next_step.strip()[:300], "author": author},
            path,
            now,
        )
    return questions(path)[qid]


def ranked(path: Path | None = None) -> list[Question]:
    """Open questions, least explored and least recently touched first."""
    open_ = [q for q in questions(path).values() if q.status == "open"]
    return sorted(open_, key=lambda q: (len(q.findings), q.touched, q.id))


def summary(limit: int = 12, path: Path | None = None) -> str:
    """The agenda for a prompt: a fixed size whatever the history."""
    found = ranked(path)
    if not found:
        return "The agenda is empty. Ask a question with `ask_question` before you research."
    held = questions(path)
    done = sum(q.status != "open" for q in held.values())
    lines = [q.line() for q in found[:limit]]
    more = len(found) - limit
    tail = f"\n... and {more} more open." if more > 0 else ""
    return (
        f"{len(found)} open question(s), {done} closed. Least explored first:\n"
        + "\n".join(lines)
        + tail
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="make agenda", description=__doc__)
    parser.add_argument("--ask", default="", help="add a question")
    parser.add_argument("--why", default="", help="why it matters")
    parser.add_argument("--close", default="", help="a question id to mark answered or dead")
    parser.add_argument("--status", default="answered", choices=["answered", "dead", "open"])
    parser.add_argument("--note", default="", help="a finding or reason for the close")
    args = parser.parse_args(argv)
    if args.ask:
        print(ask(args.ask, args.why, author="operator"))
    elif args.close:
        print(note(args.close, args.note, author="operator", status=args.status).line())
    else:
        for q in questions().values():
            print(q.line())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
