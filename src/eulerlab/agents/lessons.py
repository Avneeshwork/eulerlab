"""Lessons: what the project learned, read by every agent before it asks a model (ADR-152).

    docs/HISTORY.md, gate KILLs, guardian trips, the operator's feedback
        -> lessons.add(...)                      data/agents/lessons.jsonl (append-only)
        -> runtime.Context.ask                   the relevant few go into the system prompt
        -> lessons.violations(spec)              hard lessons are code checks, not advice

**Why both.** A lesson in a prompt is advice a model may ignore. A lesson with
a `check` is enforced by code: the autopilot drops a card that breaks it before
anything runs. The prompt copy makes the model stop proposing it; the check
makes it impossible either way.

**Append-only.** A lesson is never edited. Retiring one appends a `retire`
row naming it; the fold keeps the newest state. Ids are a hash of the source
reference, so seeding from HISTORY twice adds nothing.

**Choosing which lessons a run sees** is keyword overlap between the lesson
and the prompt, plus every lesson addressed to that agent by name. The
operator's own lessons always come first. It is deliberately simple: a
retrieval step that a model performs would itself need checking.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from eulerlab.agents.spec import home

ALL = "all"
SOURCES = ("history", "gate", "screen", "doctor", "guardian", "operator", "research")
MAX_TEXT = 600
PROMPT_LESSONS = 6
"""How many lessons a model request carries. Six short lines cost about 400 tokens."""

HISTORY = Path("docs/HISTORY.md")

_STOP_WORDS = """a an and are as at be been but by for from had has have in into is it its
of on or that the their then there these this to was were which while with
not no now one two three only every each than when what who why how all any
our we you they he she them his her so if do does did done can could would
should will may might must also more most less such same other new old
after before over under up down out off very just because about"""
_STOP = frozenset(_STOP_WORDS.split())


@dataclass(frozen=True)
class Lesson:
    id: str
    text: str
    """The rule learned, in one or two sentences."""
    source: str
    ref: str
    """Where the evidence is: `HISTORY #85`, `research 177`, a ledger entry, an operator message id."""
    agents: tuple[str, ...] = (ALL,)
    check: str = ""
    """Name of a code check in `CHECKS`, for a lesson enforced by code."""
    at: str = ""
    retired: bool = False

    @property
    def words(self) -> frozenset[str]:
        return keywords(self.text)


def keywords(text: str) -> frozenset[str]:
    words = re.findall(r"[a-z][a-z0-9_-]{2,}", text.lower())
    return frozenset(w for w in words if w not in _STOP)


def lesson_id(source: str, ref: str) -> str:
    return "L-" + hashlib.sha256(f"{source}|{ref}".encode()).hexdigest()[:8]


def _path(root: Path) -> Path:
    return root / "lessons.jsonl"


def load(root: Path | None = None, *, include_retired: bool = False) -> list[Lesson]:
    """Every lesson, newest state of each, in the order first added."""
    path = _path(home(root))
    if not path.exists():
        return []
    order: list[str] = []
    state: dict[str, Lesson] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("event") == "retire":
            old = state.get(str(row.get("id")))
            if old is not None:
                state[old.id] = Lesson(**{**asdict(old), "retired": True})
            continue
        lesson = Lesson(
            id=str(row["id"]),
            text=str(row["text"]),
            source=str(row["source"]),
            ref=str(row["ref"]),
            agents=tuple(row.get("agents") or (ALL,)),
            check=str(row.get("check") or ""),
            at=str(row.get("at") or ""),
        )
        if lesson.id not in state:
            order.append(lesson.id)
        state[lesson.id] = lesson
    out = [state[i] for i in order]
    return out if include_retired else [x for x in out if not x.retired]


def add(
    text: str,
    *,
    source: str,
    ref: str,
    agents: Iterable[str] = (ALL,),
    check: str = "",
    root: Path | None = None,
    now: datetime | None = None,
) -> Lesson:
    """Record a lesson. The same source and ref again returns the one already held."""
    if source not in SOURCES:
        msg = f"source must be one of {', '.join(SOURCES)}, not {source!r}"
        raise ValueError(msg)
    clean = " ".join(text.split())[:MAX_TEXT]
    if not clean:
        msg = "a lesson needs text"
        raise ValueError(msg)
    if check and check not in CHECKS:
        msg = f"no code check named {check!r}. Checks: {', '.join(sorted(CHECKS))}"
        raise ValueError(msg)
    root = home(root)
    lid = lesson_id(source, ref)
    for held in load(root, include_retired=True):
        if held.id == lid:
            return held
    lesson = Lesson(
        id=lid,
        text=clean,
        source=source,
        ref=ref,
        agents=tuple(sorted(set(agents))) or (ALL,),
        check=check,
        at=(now or datetime.now(UTC)).isoformat(timespec="seconds"),
    )
    path = _path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {k: v for k, v in asdict(lesson).items() if k != "retired"}
    row["agents"] = list(lesson.agents)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row) + "\n")
    return lesson


def retire(lesson_id_: str, *, why: str, root: Path | None = None) -> None:
    root = home(root)
    if lesson_id_ not in {x.id for x in load(root)}:
        msg = f"no active lesson {lesson_id_!r}"
        raise KeyError(msg)
    with _path(root).open("a", encoding="utf-8") as handle:
        row = {"event": "retire", "id": lesson_id_, "why": why[:300]}
        row["at"] = datetime.now(UTC).isoformat(timespec="seconds")
        handle.write(json.dumps(row) + "\n")


def relevant(
    agent: str, prompt: str, *, root: Path | None = None, limit: int = PROMPT_LESSONS
) -> list[Lesson]:
    """The lessons this request should carry, best first.

    Operator lessons for the agent (or for all) always come first; then any
    lesson addressed to the agent by name; then the rest by shared keywords.
    A lesson sharing fewer than two keywords with the prompt is left out.
    """
    words = keywords(prompt)
    scored: list[tuple[int, int, str, Lesson]] = []
    for lesson in load(root):
        mine = agent in lesson.agents
        if not mine and ALL not in lesson.agents:
            continue
        overlap = len(words & lesson.words)
        operator = lesson.source == "operator"
        if not operator and not mine and overlap < 2:
            continue
        tier = 0 if operator else (1 if mine else 2)
        scored.append((tier, -overlap, lesson.id, lesson))
    scored.sort(key=lambda x: (x[0], x[1], x[2]))
    return [x[3] for x in scored[:limit]]


def prompt_block(found: list[Lesson]) -> str:
    if not found:
        return ""
    lines = [f"- {x.text} ({x.ref})" for x in found]
    return (
        "Lessons this project has learned. Do not repeat these mistakes; if your answer "
        "would, say so instead:\n" + "\n".join(lines)
    )


# --- seeding from docs/HISTORY.md ----------------------------------------------------

_ENTRY = re.compile(r"^\*\*(\d+[a-z]?)\. (.+?)\*\*\s*(.*)$")


def history_entries(text: str) -> list[tuple[str, str, str]]:
    """[(number, title, first sentence after the date)] for each numbered HISTORY entry."""
    out: list[tuple[str, str, str]] = []
    for line in text.splitlines():
        m = _ENTRY.match(line.strip())
        if not m:
            continue
        number, title, rest = m.group(1), m.group(2).strip(), m.group(3)
        rest = re.sub(r"^\([^)]*\)\s*", "", rest)
        first = re.split(r"(?<=[.!?])\s+", rest, maxsplit=1)[0] if rest else ""
        out.append((number, title.rstrip("."), first))
    return out


def seed_from_history(path: Path = HISTORY, *, root: Path | None = None) -> int:
    """Add one lesson per HISTORY entry not already held. Returns how many were added."""
    if not path.exists():
        return 0
    before = len(load(root, include_retired=True))
    for number, title, first in history_entries(path.read_text(encoding="utf-8")):
        text = f"{title}. {first}" if first else f"{title}."
        add(text, source="history", ref=f"HISTORY #{number}", root=root)
    return len(load(root, include_retired=True)) - before


# --- lessons enforced by code ----------------------------------------------------------

PRICE_ONLY = frozenset({"gap", "ret", "day_return", "at_high", "at_low"})
"""Engine signals computed from a stock's own prices alone."""


def _price_only_intraday(spec: Any) -> str:
    """Research 153-176: 124 day-trading rules; no price-only rule cleared 12.24 bps."""
    if getattr(spec, "kind", "") != "intraday":
        return ""
    names = {s.signal for s in spec.signals}
    if names and names <= PRICE_ONLY:
        return (
            "an intraday rule on prices alone: 124 such tests (research 153-176) never "
            "cleared the 12.24 bps round trip; add a non-price condition"
        )
    return ""


def _results_short_after_drop(spec: Any) -> str:
    """H-0177 (research 177): shorting a results-morning gap-down lost in both halves."""
    if getattr(spec, "side", "") != "short":
        return ""
    names = {c.signal: c for c in spec.when}
    gap = names.get("gap")
    if (
        "results_morning" in names
        and gap is not None
        and gap.op in ("<=", "<")
        and gap.value is not None
        and gap.value < 0
    ):
        return "shorting a results-morning gap-down: H-0177 lost (research 177)"
    return ""


CHECKS: dict[str, Callable[[Any], str]] = {
    "price_only_intraday": _price_only_intraday,
    "results_short_after_drop": _results_short_after_drop,
}
"""Name -> a function of a `rule_engine.RuleSpec` that returns why it breaks the lesson, or ''."""

BUILT_IN: tuple[tuple[str, str, str], ...] = (
    (
        "price_only_intraday",
        "research 153-176",
        "Intraday stock rules built only from the stock's own prices do not clear retail "
        "costs: 124 tested, none cleared 12.24 bps a round trip. Use other data "
        "(delivery, results, deals, F&O) as a condition.",
    ),
    (
        "results_short_after_drop",
        "research 177",
        "Shorting a stock that gapped down on a results morning lost money (H-0177).",
    ),
)


def seed_checks(root: Path | None = None) -> None:
    for check, ref, text in BUILT_IN:
        add(text, source="research", ref=ref, check=check, agents=("autopilot",), root=root)


def violations(spec: Any, *, root: Path | None = None) -> list[str]:
    """Why `spec` breaks an active lesson that has a code check (empty when it breaks none)."""
    active = {x.check for x in load(root) if x.check}
    return [why for name in sorted(active) if (why := CHECKS[name](spec))]


@dataclass
class Seeded:
    history: int = 0
    total: int = 0
    checks: list[str] = field(default_factory=list)


def seed(root: Path | None = None, history: Path = HISTORY) -> Seeded:
    added = seed_from_history(history, root=root)
    seed_checks(root)
    held = load(root)
    return Seeded(history=added, total=len(held), checks=sorted({x.check for x in held if x.check}))


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="The agents' lessons (ADR-152).")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("seed", help="add HISTORY entries and the coded lessons")
    show = sub.add_parser("show", help="list active lessons")
    show.add_argument("--agent", default="")
    args = parser.parse_args(argv)
    if args.cmd == "seed":
        s = seed()
        print(f"lessons: {s.history} added from HISTORY, {s.total} active, checks: {s.checks}")
        return 0
    for lesson in load():
        if args.agent and args.agent not in lesson.agents and ALL not in lesson.agents:
            continue
        print(f"{lesson.id}  [{lesson.source} · {lesson.ref}]  {lesson.text[:140]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
