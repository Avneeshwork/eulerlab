"""A department head: split your tasks, check finished work, pass it up, plan the day (ADR-124).

    run(head_<dept>)
      1. check   each finished task of its agents against CHECKLIST:
                 pass → done; failed run → sent back (at most twice) → then blocked;
                 refused or switched off → blocked, with the reason, for you
      2. roll up a task of yours whose subtasks are all done is passed up to you;
                 one with a blocked subtask is blocked, so it shows as needing you
      3. split   each new task you gave it, among its agents, by what each lists
                 in `can_do`. The model is asked first; if it is not available,
                 out of budget, or answers with anything that does not fit the
                 roster, fixed rules match the task's words to each skill's
                 `words`. No match → blocked, naming what its agents can do.
      4. unstick each blocked task of its agents, once (or again when you ask): the
                 model reads what the agent was asked and what its run returned,
                 and either fixes the task (a corrected value, or another agent
                 and kind on the team) and puts it back to assigned, or writes
                 you a diagnosis. Without a model the task stays blocked. This
                 is how agents that work by fixed rules (data, operations,
                 portfolio) get AI help when they are stuck.
      5. plan    every agent's day: scheduled runs, then tasks (agents/plans.py)

A head never does an agent's work, never gives an agent a kind of task the
agent does not list, and never touches the gate, the ledger or the order path:
it only writes task events. Starting the agents is the work runner's job
(`agents/work.py`), so a head's run is quick and never holds a long run open.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from eulerlab.agents import doctor, org, plans, tasks
from eulerlab.agents.runtime import BudgetSpent, Context, Item, WorkerResult, untrusted
from eulerlab.agents.spec import AgentSpec, Effective, Skill, all_effective, home

CHECKLIST = (
    "the agent's run finished ok (not failed, refused, over budget or switched off)",
    "the run says what it did (a summary is written)",
    "the doctor found no problem in that run",
    "the run delivered what the task asked for",
)
"""What a head checks before it passes a task up. Shown on the page as written."""

DELIVERS: dict[str, re.Pattern[str]] = {
    "research_topic": re.compile(r"\b0 drafted\b"),
    "test_card": re.compile(r"\b0 card\(s\) tested\b"),
}
"""A finished run whose summary matches delivered nothing for that kind of task.
On 2026-11-03 a head passed up a research task that drafted 0 ideas (ADR-132).
Sent back, research reads papers it has not judged yet; after two returns the
task is blocked and the head's AI help can reword it."""

MAX_SUBTASKS = 4
_WORD = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class Assignment:
    agent: str
    skill: Skill
    value: str
    title: str


def team(department: str, agents: dict[str, Effective]) -> dict[str, Effective]:
    """The switched-on agents this head may give work to."""
    specs = {name: a.spec for name, a in agents.items()}
    chart = org.load_org()
    return {n: agents[n] for n in org.members(chart, specs, department) if agents[n].enabled}


def roster(members: dict[str, Effective]) -> list[tuple[str, Skill]]:
    return [(name, skill) for name, a in sorted(members.items()) for skill in a.spec.can_do]


# ---------------------------------------------------------------- 1. check


def _doctor_flagged(run_id: str, root: Path) -> str:
    path = root / doctor.FOLDER / doctor.LOG
    if not run_id or not path.exists():
        return ""
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get("run") == run_id:
            return f"{row.get('kind', 'problem')}: {str(row.get('detail', ''))[:160]}"
    return ""


def check(task: tasks.Task, head: str, root: Path, now: datetime) -> tasks.Task:
    """Run CHECKLIST on one finished task and record the verdict."""
    status = task.run_status
    if status == "over_budget":
        return tasks.record(
            task.id,
            "assigned",
            head,
            {"note": "the agent's budget for today was spent; it runs again on the next pass"},
            root=root,
            now=now,
        )
    # A failed run whose error is a refusal (no API key, a blocked host, a
    # spent quota) fails again the same way: it needs you, not a retry.
    refusal = status == "failed" and task.summary.startswith(("Refused", "BudgetSpent"))
    if status in ("refused", "skipped") or refusal:
        why = "switched off" if status == "skipped" else "refused"
        return tasks.record(
            task.id,
            "blocked",
            head,
            {
                "note": f"the agent {why}: {task.summary[:200].rstrip('.')}. Running it again would not change that."
            },
            root=root,
            now=now,
        )
    failed: list[str] = []
    if status != "ok":
        failed.append(CHECKLIST[0])
    if not task.summary.strip():
        failed.append(CHECKLIST[1])
    flagged = _doctor_flagged(task.run_id, root)
    if flagged:
        failed.append(f"{CHECKLIST[2]} ({flagged})")
    empty = DELIVERS.get(task.kind)
    if status == "ok" and empty is not None and empty.search(task.summary):
        failed.append(f"{CHECKLIST[3]} ({task.summary[:120].rstrip('.')})")
    if not failed:
        return tasks.record(
            task.id, "accepted", head, {"note": "passed the checklist"}, root=root, now=now
        )
    note = "failed: " + "; ".join(failed)
    if task.returns < tasks.MAX_RETURNS:
        return tasks.record(task.id, "sent_back", head, {"note": note}, root=root, now=now)
    return tasks.record(
        task.id,
        "blocked",
        head,
        {"note": f"{note}. Sent back {tasks.MAX_RETURNS} times already; it needs you."},
        root=root,
        now=now,
    )


def check_all(head: str, department: str, root: Path, now: datetime) -> list[tasks.Task]:
    done: list[tasks.Task] = []
    for task in tasks.load(root).values():
        if task.department == department and task.status == "review":
            done.append(check(task, head, root, now))
    return done


# ---------------------------------------------------------------- 2. roll up


def roll_up(head: str, root: Path, now: datetime) -> list[tasks.Task]:
    """Pass up a task whose subtasks are all finished; block one with a blocked subtask."""
    changed: list[tasks.Task] = []
    known = tasks.load(root)
    for parent in tasks.owned_by(known, head):
        subs = tasks.children(known, parent.id)
        if not subs:
            continue
        blocked = [s for s in subs if s.status == "blocked"]
        if blocked and parent.status != "blocked":
            note = "; ".join(f"{s.owner}: {s.history[-1].get('note', '')}"[:200] for s in blocked)
            changed.append(
                tasks.record(parent.id, "blocked", head, {"note": note}, root=root, now=now)
            )
            continue
        if not blocked and parent.status == "blocked":
            changed.append(
                tasks.record(
                    parent.id, "assigned", head, {"note": "nothing blocked now"}, root=root, now=now
                )
            )
            parent = tasks.load(root)[parent.id]
        settled = all(s.status in ("done", "closed", "cancelled") for s in subs)
        if settled and any(s.status in ("done", "closed") for s in subs):
            summary = " | ".join(
                f"{s.owner}: {s.summary[:160]}" for s in subs if s.status in ("done", "closed")
            )
            changed.append(
                tasks.record(
                    parent.id,
                    "passed_up",
                    head,
                    {"summary": summary[:1000], "note": "every subtask passed the checklist"},
                    root=root,
                    now=now,
                )
            )
    return changed


# ---------------------------------------------------------------- 3. split


def _unwrap(skill: Skill, wanted: str) -> str:
    """A model sometimes sends the value as JSON (`{"question": "..."}`, seen on Groq
    2026-11-03); take the argument out of it."""
    text = wanted.strip()
    if not text.startswith("{"):
        return wanted
    try:
        raw = json.loads(text)
    except ValueError:
        return wanted
    if isinstance(raw, dict):
        inner = raw.get(skill.arg) or raw.get("value")
        if isinstance(inner, str):
            return inner
    return wanted


def _value(skill: Skill, wanted: str, task: tasks.Task) -> str:
    wanted = _unwrap(skill, wanted)
    text = " ".join(wanted.split())[:300]
    if skill.choices:
        # The model's value first, then the task's words: a choice fits when all
        # its words are there ("after the close" fits after-close).
        for text_in in (wanted, f"{task.title} {task.detail}"):
            words = set(_WORD.findall(text_in.lower()))
            for c in skill.choices:
                if set(_WORD.findall(c.lower())) <= words:
                    return c
        return skill.choices[0]
    return text or task.title


def by_rules(task: tasks.Task, options: list[tuple[str, Skill]]) -> list[Assignment]:
    """The fallback: the skill whose `words` the task uses most. Ties go to the first listed."""
    words = set(_WORD.findall(f"{task.title} {task.detail}".lower()))
    best: tuple[int, str, Skill] | None = None
    for name, skill in options:
        score = len(words & {w.lower() for w in skill.words})
        if score and (best is None or score > best[0]):
            best = (score, name, skill)
    if best is None:
        return []
    _, name, skill = best
    value = task.detail.strip() or task.title
    return [Assignment(name, skill, _value(skill, value, task), task.title)]


SYSTEM = """You are a department head in Euler Lab, a one-person quant research firm. The CEO gave you a task.
Split it into at most {n} subtasks for the agents on your team. Use only the agents and task kinds in the roster.
For a kind with an argument, put the argument in "value": a research topic, a question, a strategy name or "all",
a dataset name, or one of the listed choices. Write a short title for each subtask.
If no agent on your team can do any part of it, return an empty list and say why.
Answer with JSON only, nothing else:
{{"subtasks": [{{"agent": "...", "kind": "...", "value": "...", "title": "..."}}], "why": "..."}}"""


def _parse(text: str) -> dict[str, Any]:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        msg = "no JSON object in the answer"
        raise ValueError(msg)
    raw = json.loads(text[start : end + 1])
    if not isinstance(raw, dict) or not isinstance(raw.get("subtasks"), list):
        msg = "the answer has no subtasks list"
        raise ValueError(msg)
    return raw


def fit(
    raw: dict[str, Any], task: tasks.Task, options: list[tuple[str, Skill]], limit: int
) -> list[Assignment]:
    """Keep only the model's subtasks that name a real agent and one of its own kinds."""
    allowed = {(name, skill.kind): skill for name, skill in options}
    out: list[Assignment] = []
    seen: set[tuple[str, str, str]] = set()
    for row in raw.get("subtasks", []):
        if not isinstance(row, dict):
            continue
        name, kind = str(row.get("agent", "")), str(row.get("kind", ""))
        skill = allowed.get((name, kind))
        if skill is None:
            continue
        value = _value(skill, str(row.get("value", "")), task) if skill.arg else ""
        title = " ".join(str(row.get("title") or task.title).split())[:200]
        key = (name, kind, value)
        if key in seen:
            continue
        seen.add(key)
        out.append(Assignment(name, skill, value, title))
        if len(out) >= limit:
            break
    return out


def by_model(
    ctx: Context, task: tasks.Task, options: list[tuple[str, Skill]], limit: int
) -> tuple[list[Assignment], str, bool]:
    """The model's split, a note, and whether the model judged that nothing fits.

    An empty list without that judgement means the model could not be used: no
    budget, no answer, malformed JSON, or only agents and kinds not on the
    roster. Then the fixed rules split it. A model that read the roster and
    said nothing fits is believed: the task is blocked for you rather than
    pushed onto whichever skill shares a word with it.
    """
    if not ctx.can_ask():
        return [], "no model request left today", False
    lines = [
        f"- agent {name}, kind {s.kind}: {s.what}"
        + (
            f" (value: {s.arg}" + (f", one of {', '.join(s.choices)}" if s.choices else "") + ")"
            if s.arg
            else ""
        )
        for name, s in options
    ]
    user = (
        "Your team's roster:\n"
        + "\n".join(lines)
        + "\n\nThe CEO's task:\n"
        + untrusted("ceo-task", f"{task.title}\n\n{task.detail}", limit=3000)
    )
    try:
        answer = ctx.ask(SYSTEM.format(n=limit), user, accept=_parse)
        raw = _parse(answer)
    except BudgetSpent:
        return [], "no model request left today", False
    except Exception as exc:  # any model failure falls back to the fixed rules
        return [], f"the model did not answer usably ({type(exc).__name__})", False
    chosen = fit(raw, task, options, limit)
    if chosen:
        return chosen, "", False
    if raw["subtasks"]:
        return [], "the model named only agents or kinds not on the roster", False
    why = str(raw.get("why") or "")[:200]
    return [], "the model found no agent here who can do it" + (f": {why}" if why else ""), True


def split(ctx: Context, task: tasks.Task, members: dict[str, Effective], limit: int) -> tasks.Task:
    head, root, now = ctx.name, ctx.root, ctx.now
    options = roster(members)
    if not options:
        return tasks.record(
            task.id,
            "blocked",
            head,
            {"note": "no switched-on agent on this team takes tasks"},
            root=root,
            now=now,
        )
    chosen, note, judged = by_model(ctx, task, options, limit)
    planned_by = "model"
    if not chosen and not judged:
        planned_by = "rules"
        chosen = by_rules(task, options)
        ctx.notes.append(f"{task.id}: fixed rules used ({note})")
    if not chosen:
        can = "; ".join(f"{n} can {s.what.lower()}" for n, s in options)
        return tasks.record(
            task.id,
            "blocked",
            head,
            {"note": f"no agent here can do this ({note or 'no words matched'}). {can}"[:600]},
            root=root,
            now=now,
        )
    for i, a in enumerate(chosen):
        tasks.create(
            title=a.title,
            detail=f"From {task.created_by}'s task {task.id}: {task.title}",
            owner=a.agent,
            department=task.department,
            created_by=head,
            due=task.due,
            kind=a.skill.kind,
            args={a.skill.arg: a.value} if a.skill.arg else {},
            parent=task.id,
            key=f"{task.id}|{task.returns}|{len(task.history)}|{i}|{a.agent}|{a.skill.kind}",
            root=root,
            now=now,
        )
    who = ", ".join(f"{a.agent} ({a.skill.kind})" for a in chosen)
    return tasks.record(
        task.id,
        "assigned",
        head,
        {"planned_by": planned_by, "note": f"split by {planned_by} into: {who}"},
        root=root,
        now=now,
    )


# ---------------------------------------------------------------- 4. unstick

HELP = """You are a department head in Euler Lab, a one-person quant research firm. One of your agents is stuck.
Read what it was asked, why it is blocked and what its last run returned. Choose one:
- "retry": the same agent and kind, with a corrected value (for example the exact strategy or dataset name its output lists);
- "reassign": another agent and kind from the roster, with a value;
- "needs_ceo": only the CEO can unblock it (an API key, data to buy, a decision, or a request no agent here can do).
Use only agents and kinds from the roster. Never suggest anything that runs the gate, trades, or spends trials outside the idea lab.
Answer with JSON only: {"action": "retry|reassign|needs_ceo", "agent": "...", "kind": "...", "value": "...", "why": "one or two sentences for the CEO"}"""


def _parse_help(text: str) -> dict[str, Any]:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        msg = "no JSON object in the answer"
        raise ValueError(msg)
    raw = json.loads(text[start : end + 1])
    if not isinstance(raw, dict) or raw.get("action") not in ("retry", "reassign", "needs_ceo"):
        msg = "the answer names no action"
        raise ValueError(msg)
    return raw


def _run_text(task: tasks.Task, root: Path) -> str:
    """What the stuck agent's last run said: summary, the last notes, the items' titles."""
    if not task.run_id:
        return "it has not run"
    path = root / task.owner / task.run_id / "output.json"
    try:
        out = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return f"summary: {task.summary}"
    notes = [str(n).strip().splitlines()[-1] for n in out.get("notes", []) if str(n).strip()][-5:]
    titles = [str(i.get("title", "")) for i in out.get("items", [])][:30]
    return "\n".join(
        [f"status: {out.get('status')}", f"summary: {out.get('summary', '')}"]
        + [f"note: {n}" for n in notes]
        + [f"item: {t}" for t in titles]
    )


MAX_KNOWN = 300
"""Valid values shown to the model per argument; more are cut, and then not enforced."""


def known_values(arg: str) -> list[str]:
    """The values an argument can take, where the project lists them; empty if unknown.

    strategy: the stored results the skeptic can attack. dataset: the datasets
    the data agent last graded. Only these two are listed; any other argument
    (a topic, a question) is free text.
    """
    try:
        if arg == "strategy":
            from eulerlab.agents.workers import skeptic

            return [str(t["strategy"]) for t in skeptic.targets()]
        if arg == "dataset":
            from eulerlab.quality import contract

            return [str(g.get("name")) for g in contract.saved() if g.get("name")]
    except (OSError, ValueError, KeyError):
        return []
    return []


def wants_help(task: tasks.Task) -> bool:
    return task.status == "blocked" and (task.help_wanted or task.assists < tasks.MAX_ASSISTS)


def unstick(ctx: Context, task: tasks.Task, members: dict[str, Effective]) -> tasks.Task | None:
    """Ask the model to fix one blocked task. None: no model now, nothing recorded."""
    head, root, now = ctx.name, ctx.root, ctx.now
    options = roster(members)
    if not ctx.can_ask():
        if task.help_wanted:
            return tasks.record(
                task.id,
                "note",
                head,
                {
                    "assist": "unavailable",
                    "note": "AI help is not available now: no model request left today",
                },
                root=root,
                now=now,
            )
        return None
    lines = [
        f"- agent {n}, kind {s.kind}: {s.what}" + (f" (value: {s.arg})" if s.arg else "")
        for n, s in options
    ]
    known = {arg: known_values(arg) for arg in sorted({s.arg for _, s in options if s.arg})}
    known = {arg: values for arg, values in known.items() if values}
    listed = "".join(
        f"\nValid values for {arg}: {', '.join(values[:MAX_KNOWN])}"
        for arg, values in known.items()
    )
    why = str(task.history[-1].get("note", "")) if task.history else ""
    user = (
        "Your team's roster:\n"
        + "\n".join(lines)
        + f"\n\nThe stuck task: {task.title}\nagent {task.owner}, kind {task.kind}, value {json.dumps(task.args)}"
        + f"\nWhy it is blocked: {why[:600]}{listed}\n\nIts last run:\n"
        + untrusted("agent-output", _run_text(task, root), limit=4000)
    )
    try:
        raw = _parse_help(ctx.ask(HELP, user, accept=_parse_help))
    except BudgetSpent:
        return None
    except Exception as exc:  # the model failed: say so if you asked, else try next run
        ctx.notes.append(f"{task.id}: AI help failed ({type(exc).__name__})")
        if task.help_wanted:
            return tasks.record(
                task.id,
                "note",
                head,
                {
                    "assist": "unavailable",
                    "note": f"AI help failed this time ({type(exc).__name__}); ask again later",
                },
                root=root,
                now=now,
            )
        return None
    advice = " ".join(str(raw.get("why") or "").split())[:400]
    action = raw["action"]
    if action in ("retry", "reassign"):
        agent = task.owner if action == "retry" else str(raw.get("agent", ""))
        kind = task.kind if action == "retry" else str(raw.get("kind", ""))
        skill = {(n, s.kind): s for n, s in options}.get((agent, kind))
        if skill is not None:
            value = _value(skill, str(raw.get("value", "")), task) if skill.arg else ""
            args = {skill.arg: value} if skill.arg else {}
            valid = known.get(skill.arg, [])
            if valid and len(valid) <= MAX_KNOWN and value not in valid:
                return tasks.record(
                    task.id,
                    "note",
                    head,
                    {
                        "assist": "diagnosis",
                        "note": f"AI help: it suggested {value!r}, which is not a valid {skill.arg}. {advice}"[
                            :600
                        ],
                    },
                    root=root,
                    now=now,
                )
            if (agent, kind, args) != (
                task.owner,
                task.kind,
                {k: v for k, v in task.args.items() if k == skill.arg},
            ):
                return tasks.record(
                    task.id,
                    "assisted",
                    head,
                    {
                        "owner": agent,
                        "kind": kind,
                        "args": args,
                        "note": f"AI help ({action}): {advice}",
                    },
                    root=root,
                    now=now,
                )
        advice = f"the model suggested a change that does not fit the roster or changes nothing. {advice}"
    return tasks.record(
        task.id,
        "note",
        head,
        {"assist": "diagnosis", "note": f"AI help: {advice}"[:600]},
        root=root,
        now=now,
    )


def unstick_all(ctx: Context, department: str, members: dict[str, Effective]) -> list[tasks.Task]:
    found: list[tasks.Task] = []
    for task in tasks.load(ctx.root).values():
        if (
            task.department == department
            and not task.owner.startswith("head_")
            and wants_help(task)
        ):
            done = unstick(ctx, task, members)
            if done is not None:
                found.append(done)
    return found


# ---------------------------------------------------------------- the run


def run(ctx: Context) -> WorkerResult:
    department = str(ctx.options.get("department") or "")
    if not department:
        return WorkerResult("no department in this head's options", status="refused")
    root = home(ctx.root)
    limit = max(1, min(int(ctx.options.get("max_subtasks") or MAX_SUBTASKS), MAX_SUBTASKS))
    agents = all_effective(root)
    members = team(department, agents)

    ctx.step("Checking finished tasks against the checklist")
    checked = check_all(ctx.name, department, root, ctx.now)
    helped = unstick_all(ctx, department, members)
    if helped:
        ctx.step(f"Asked the model for help on {len(helped)} stuck task(s)")
    rolled = roll_up(ctx.name, root, ctx.now)

    fresh = [t for t in tasks.owned_by(tasks.load(root), ctx.name) if t.status == "open"]
    ctx.step(f"Splitting {len(fresh)} new task(s) among {len(members)} agent(s)")
    split_done = [split(ctx, t, members, limit) for t in fresh]
    rolled += roll_up(ctx.name, root, ctx.now)

    known = tasks.load(root)
    specs: dict[str, AgentSpec] = {n: a.spec for n, a in agents.items()}
    slots, slot_note = plans.today_slots(specs, ctx.now, root)
    if slot_note:
        ctx.notes.append(slot_note)
    day = {
        name: plans.for_agent(
            agents[name].spec, known, slots, ctx.now, enabled=agents[name].enabled
        )
        for name in [ctx.name, *sorted(org.members(org.load_org(), specs, department))]
    }
    ctx.write("plans.json", day)

    items: list[Item] = []
    for t in tasks.owned_by(known, ctx.name):
        if t.status == "blocked":
            items.append(
                Item(
                    kind="alert",
                    severity="warn",
                    title=f"Needs you: {t.title}"[:200],
                    body=str(t.history[-1].get("note", ""))[:600],
                    ref=t.id,
                )
            )
    for t in rolled:
        if t.status == "done":
            items.append(
                Item(kind="finding", title=f"Done: {t.title}"[:200], body=t.summary[:600], ref=t.id)
            )
    by_model_count = sum(
        1 for t in split_done if t.planned_by == "model" and t.status == "assigned"
    )
    by_rules_count = sum(
        1 for t in split_done if t.planned_by == "rules" and t.status == "assigned"
    )
    planned_tasks = sum(len(p["tasks"]) for p in day.values())
    summary = (
        f"checked {len(checked)}, unstuck {sum(1 for t in helped if t.status == 'assigned')} "
        f"and diagnosed {sum(1 for t in helped if t.status == 'blocked')} with AI help, "
        f"passed up or blocked {len(rolled)}, "
        f"split {by_model_count} by model and {by_rules_count} by rules"
        f"{f', {len(split_done) - by_model_count - by_rules_count} could not be split' if len(split_done) > by_model_count + by_rules_count else ''}; "
        f"{planned_tasks} open task(s) across {len(day)} plan(s)"
    )
    return WorkerResult(
        summary,
        items,
        data={
            "department": department,
            "checklist": list(CHECKLIST),
            "plans": day,
            "helped": [t.id for t in helped],
        },
    )
