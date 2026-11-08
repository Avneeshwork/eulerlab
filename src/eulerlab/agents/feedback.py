"""The feedback desk: the operator writes once; code routes it (ADR-152).

    make feedback TEXT="never short stocks under ₹50"      -> a lesson every agent reads
    make feedback TEXT="goal: a second intraday book by Dec" -> a task for the right head
    Telegram: `feedback <text>`                               -> the same

Routing is fixed rules, not a model, so the same words always land in the same
place and the operator can predict it:

- **lesson**: the text starts with `lesson:`, or reads as a rule (`never`,
  `always`, `don't`, `do not`, `stop`, `avoid`, `must`). It becomes an operator
  lesson, which `lessons.relevant` puts first in every model request. A text
  that starts with an agent's name and a colon (`autopilot: ...`) is a lesson
  for that agent only.
- **task**: anything else, including `goal:`. It goes to a department head as
  a task (`agents/tasks.py`), chosen by keywords: data, code, UI and speed to
  Data and Platform; paper books, risk, sizing and live to Portfolio and Risk;
  the rest to Research. The head splits it on its next run (ADR-124).

Every message is kept in `data/agents/feedback.jsonl` with where it went, so
"what did I tell them, and what happened to it" always has an answer.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from eulerlab.agents.spec import home

RULE_WORDS = re.compile(r"\b(never|always|don't|dont|do not|stop|avoid|must)\b", re.IGNORECASE)

HEADS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "head_platform",
        "platform",
        (
            "data",
            "ingest",
            "download",
            "upload",
            "bug",
            "code",
            "ui",
            "screen",
            "page",
            "latency",
            "fast",
            "slow",
            "speed",
            "infra",
            "server",
            "test",
            "kite",
            "token",
        ),
    ),
    (
        "head_portfolio",
        "portfolio",
        (
            "paper",
            "book",
            "risk",
            "sizing",
            "size",
            "capital",
            "live",
            "deploy",
            "drawdown",
            "loss",
            "position",
            "pilot",
            "brief",
        ),
    ),
)
DEFAULT_HEAD = ("head_research", "research")


@dataclass(frozen=True)
class Routed:
    id: str
    text: str
    kind: str
    """`lesson` or `task`."""
    target: str
    """The lesson id or the task id it became."""
    owner: str
    at: str
    by: str


def _path(root: Path) -> Path:
    return root / "feedback.jsonl"


def classify(text: str, agents: set[str]) -> tuple[str, str, str]:
    """(kind, owner, cleaned text). Owner is an agent name, `all`, or a head."""
    clean = " ".join(text.split())
    head, sep, rest = clean.partition(":")
    label = head.strip().lower()
    if sep and label == "lesson":
        return "lesson", "all", rest.strip()
    if sep and label in agents and rest.strip():
        return "lesson", label, rest.strip()
    if sep and label == "goal":
        clean = rest.strip()
    elif RULE_WORDS.search(clean):
        return "lesson", "all", clean
    words = set(re.findall(r"[a-z]+", clean.lower()))
    for owner, _, keys in HEADS:
        if words & set(keys):
            return "task", owner, clean
    return "task", DEFAULT_HEAD[0], clean


def route(
    text: str,
    *,
    by: str = "cli",
    root: Path | None = None,
    agents: set[str] | None = None,
    now: datetime | None = None,
) -> Routed:
    from eulerlab.agents import lessons, tasks
    from eulerlab.agents.spec import load_specs

    root = home(root)
    if not text.strip():
        msg = "feedback needs text"
        raise ValueError(msg)
    now = now or datetime.now(UTC)
    known = agents if agents is not None else set(load_specs())
    kind, owner, clean = classify(text, known)
    fid = "F-" + hashlib.sha256(f"{clean}|{now.isoformat()}".encode()).hexdigest()[:8]
    if kind == "lesson":
        lesson = lessons.add(clean, source="operator", ref=fid, agents=(owner,), root=root)
        target = lesson.id
    else:
        department = next((d for o, d, _ in HEADS if o == owner), DEFAULT_HEAD[1])
        task = tasks.create(
            title=clean[:200],
            owner=owner,
            department=department,
            created_by="ceo",
            detail=f"Operator feedback {fid}: {clean}",
            key=fid,
            root=root,
            now=now,
        )
        target = task.id
    routed = Routed(fid, clean, kind, target, owner, now.isoformat(timespec="seconds"), by)
    path = _path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(asdict(routed)) + "\n")
    return routed


def history(root: Path | None = None, limit: int = 30) -> list[Routed]:
    path = _path(home(root))
    if not path.exists():
        return []
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    return [Routed(**r) for r in rows][-limit:]


def say(routed: Routed) -> str:
    if routed.kind == "lesson":
        who = "every agent" if routed.owner == "all" else routed.owner
        return f"Saved as a lesson for {who} ({routed.target}); it rides on their model requests."
    return f"Sent to {routed.owner} as task {routed.target}; the head splits it on its next run."


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="The operator's feedback desk (ADR-152).")
    parser.add_argument("text", nargs="*")
    args = parser.parse_args(argv)
    text = " ".join(args.text).strip()
    if not text:
        for r in history():
            print(f"{r.at}  {r.kind:6} -> {r.owner:15} {r.target}  {r.text[:100]}")
        return 0
    print(say(route(text)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
