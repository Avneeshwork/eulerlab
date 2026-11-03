"""The watchdog: is every agent running, doing what it is for, and within its budget? (ADR-132)

The doctor (`agents/doctor.py`) looks at one run as it ends. Nothing looked
across runs, so an agent that never ran, failed the same way three days in a
row, spent ten times its usual tokens, or kept being handed back its tasks
went unnoticed (2026-11-04: the operator asked for exactly this). One pass:

1. **Runs** in the window, per agent: failed, over budget or refused runs, and
   the same failure three runs in a row ("stuck").
2. **Missed runs**: a scheduled agent with no run within its `expect` hours
   (weekday-only agents get the weekend off).
3. **Model use**: requests against each agent's `daily_requests`, any request
   from an agent defined without a model, and tokens from the token log
   (`llm/usage.py`): an agent over `tokens_per_agent` a day, all agents over
   `tokens_total` (Groq's free tier allows 200,000 a day, research 143), or an
   average request over `tokens_per_request`.
4. **Tasks**: blocked, sent back twice (wrong work), or open past their due day.
5. **Remedies**, from a fixed list only: re-run once a day an agent in
   `rerun_ok` whose last run failed or that missed its run; then one Groq
   request over what is left, whose answer becomes a task for the agent's head
   ("fix it, or give it to the agent that can") or a note for the operator.

It never edits code or data, never trades, never touches the gate, and never
re-runs an agent that spends trials or sends messages (lab, research,
market_brief): those wait for their head or for you.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from eulerlab.agents import tasks
from eulerlab.agents.runtime import (
    BudgetSpent,
    Context,
    Item,
    Output,
    WorkerResult,
    outputs,
    untrusted,
)
from eulerlab.agents.spec import Effective, all_effective
from eulerlab.llm import usage

IST = ZoneInfo("Asia/Kolkata")
BAD = ("failed", "over_budget", "refused")
STUCK_AFTER = 3
HELP = """You are the watchdog of a small company of software agents that run a quant
research platform. You get the problems found in the last day: failed or missed runs,
agents over their model budget, tasks that went wrong. For each problem, say its most
likely cause and who should act. Answer only with JSON:
{"problems": [{"agent": "<agent name>", "cause": "...", "fix": "...",
  "who": "head" | "operator" | "wait"}]}
- head: the agent's head should fix it or give it to the agent that can (a code bug
  goes to engineering, data to the data agent).
- operator: only the operator can (a login, a key, money, a decision about a book).
- wait: it is passing and the next scheduled run will clear it.
Never suggest editing the validation gate, the trial ledger, the holdout or orders."""


@dataclass(frozen=True)
class Problem:
    agent: str
    kind: str
    """failed, stuck, missed, over_requests, model_without_budget, tokens, task."""
    title: str
    body: str
    severity: str = "warn"


def _started(output: Output) -> datetime:
    return datetime.fromisoformat(output.started)


def runs_since(name: str, since: datetime, root: Any) -> list[Output]:
    """The agent's runs from `since`, oldest first."""
    return sorted((o for o in outputs(name, root, limit=80) if _started(o) >= since), key=_started)


def weekend_gap(now: datetime) -> bool:
    """True from Saturday to Monday 17:00 IST, when weekday-only agents have not run."""
    local = now.astimezone(IST)
    return local.weekday() >= 5 or (local.weekday() == 0 and local.hour < 17)


def check_runs(
    agents: dict[str, Effective], *, now: datetime, root: Any, options: dict[str, Any]
) -> tuple[list[Problem], dict[str, list[Output]]]:
    hours = int(options.get("window_hours") or 26)
    since = now - timedelta(hours=hours)
    expect: dict[str, Any] = dict(options.get("expect") or {})
    weekday_only = set(options.get("weekdays_only") or [])
    problems: list[Problem] = []
    seen: dict[str, list[Output]] = {}
    for name, agent in sorted(agents.items()):
        if not agent.enabled or name == "watchdog":
            continue
        recent = runs_since(name, since, root)
        seen[name] = recent
        for out in recent:
            if out.status in BAD:
                problems.append(
                    Problem(
                        name,
                        "failed",
                        f"{name} run {out.status}",
                        f"{out.run_id}: {out.summary[:300]}",
                    )
                )
        last = outputs(name, root, limit=STUCK_AFTER)
        if len(last) == STUCK_AFTER and all(o.status in BAD for o in last):
            same = len({re.sub(r"\d+", "#", o.summary)[:80] for o in last}) == 1
            problems.append(
                Problem(
                    name,
                    "stuck",
                    f"{name} failed its last {STUCK_AFTER} runs"
                    + (" the same way" if same else ""),
                    last[0].summary[:300],
                    "critical",
                )
            )
        if name in expect:
            allowed = float(expect[name]) + (48 if name in weekday_only and weekend_gap(now) else 0)
            newest = outputs(name, root, limit=1)
            if not newest or _started(newest[0]) < now - timedelta(hours=allowed):
                when = newest[0].started if newest else "never"
                problems.append(
                    Problem(
                        name,
                        "missed",
                        f"{name} has not run for over {allowed:.0f} hours",
                        f"last run: {when}. Check its schedule (make schedule JOB=...) and the job's log.",
                    )
                )
    return problems, seen


def check_model_use(
    agents: dict[str, Effective],
    seen: dict[str, list[Output]],
    *,
    now: datetime,
    options: dict[str, Any],
) -> tuple[list[Problem], dict[str, Any]]:
    problems: list[Problem] = []
    day = now.astimezone(IST).date()
    requests_today: dict[str, int] = defaultdict(int)
    for name, runs in seen.items():
        for out in runs:
            if _started(out).astimezone(IST).date() == day:
                requests_today[name] += out.requests
    for name, used in sorted(requests_today.items()):
        agent = agents[name]
        if used and not agent.spec.uses_model:
            problems.append(
                Problem(
                    name,
                    "model_without_budget",
                    f"{name} asked a model but is defined without one",
                    f"{used} request(s) today",
                    "critical",
                )
            )
        elif agent.daily_requests and used >= agent.daily_requests:
            problems.append(
                Problem(
                    name,
                    "over_requests",
                    f"{name} used all {agent.daily_requests} model requests today",
                    "its later runs today get no AI help",
                )
            )
    rows = usage.rows(since=now - timedelta(hours=24))
    by_agent: dict[str, list[int]] = defaultdict(list)
    for row in rows:
        by_agent[str(row.get("agent") or "?")].append(int(row.get("total") or 0))
    per_agent = int(options.get("tokens_per_agent") or 60_000)
    total_cap = int(options.get("tokens_total") or 160_000)
    per_request = int(options.get("tokens_per_request") or 12_000)
    for name, totals in sorted(by_agent.items()):
        spent = sum(totals)
        if spent > per_agent:
            problems.append(
                Problem(
                    name,
                    "tokens",
                    f"{name} used {spent:,} tokens in a day",
                    f"over the {per_agent:,} allowed an agent; {len(totals)} request(s)",
                )
            )
        average = spent / len(totals) if totals else 0
        if average > per_request:
            problems.append(
                Problem(
                    name,
                    "tokens",
                    f"{name} sends {average:,.0f} tokens a request",
                    f"over {per_request:,}: its prompts carry more than they need",
                )
            )
    grand = sum(sum(t) for t in by_agent.values())
    if grand > total_cap:
        problems.append(
            Problem(
                "all",
                "tokens",
                f"agents used {grand:,} tokens in a day",
                f"over {total_cap:,}; Groq's free tier stops at 200,000",
                "critical",
            )
        )
    spend = {
        "tokens_24h": grand,
        "tokens_by_agent": {k: sum(v) for k, v in sorted(by_agent.items())},
        "requests_today": dict(sorted(requests_today.items())),
    }
    return problems, spend


def check_tasks(root: Any, *, now: datetime) -> list[Problem]:
    problems: list[Problem] = []
    today = now.astimezone(IST).date().isoformat()
    for task in tasks.load(root).values():
        if task.status not in tasks.ACTIVE:
            continue
        if task.status == "blocked":
            why = str(task.history[-1].get("data", {}).get("note", "")) if task.history else ""
            problems.append(
                Problem(
                    task.owner,
                    "task",
                    f"task blocked: {task.title[:120]}",
                    f"{task.id}: {why[:200]}",
                )
            )
        elif task.returns >= tasks.MAX_RETURNS:
            problems.append(
                Problem(
                    task.owner,
                    "task",
                    f"task sent back {task.returns} times: {task.title[:120]}",
                    f"{task.id}: the work did not meet its checklist",
                )
            )
        elif task.due and task.due < today:
            problems.append(
                Problem(
                    task.owner,
                    "task",
                    f"task overdue since {task.due}: {task.title[:120]}",
                    f"{task.id}, {task.status}",
                )
            )
    return problems


def _reran_today(ctx: Context) -> set[str]:
    day = ctx.now.astimezone(IST).date()
    done: set[str] = set()
    for out in outputs("watchdog", ctx.root, limit=20):
        if _started(out).astimezone(IST).date() == day:
            done |= set(out.data.get("reran") or [])
    return done


def remedy(ctx: Context, problems: list[Problem]) -> tuple[list[str], list[Item]]:
    """Re-run, once a day, a cheap agent whose run failed or was missed."""
    allowed = set(ctx.options.get("rerun_ok") or [])
    already = _reran_today(ctx)
    reran: list[str] = []
    items: list[Item] = []
    for name in sorted({p.agent for p in problems if p.kind in ("failed", "missed", "stuck")}):
        if name not in allowed or name in already or name in reran:
            continue
        from eulerlab.agents import runtime

        ctx.step(f"Re-running {name} once")
        out = runtime.run(name, root=ctx.root)
        reran.append(name)
        items.append(
            Item(
                kind="finding",
                title=f"re-ran {name}: {out.status}",
                body=out.summary[:300],
                severity="info" if out.status == "ok" else "warn",
            )
        )
    return reran, items


def _head_of(agent: str, agents: dict[str, Effective]) -> str:
    if agent.startswith("head_") and agent in agents:
        return agent
    dept = agents[agent].spec.reports_to if agent in agents else "platform"
    head = f"head_{dept}"
    return head if head in agents else "head_platform"


def ask_for_help(ctx: Context, problems: list[Problem], agents: dict[str, Effective]) -> list[Item]:
    if not problems or not ctx.can_ask() or not ctx.options.get("ai_help"):
        return []
    listed = "\n".join(f"- [{p.agent}] {p.kind}: {p.title}. {p.body[:240]}" for p in problems[:15])
    try:
        raw = ctx.ask(HELP, untrusted("watchdog-problems", listed, limit=5000), accept=_parse)
        answers = _parse(raw)["problems"]
    except BudgetSpent:
        return []
    except Exception as exc:
        ctx.notes.append(f"AI help failed ({type(exc).__name__})")
        return []
    items: list[Item] = []
    known = {p.agent for p in problems}
    day = ctx.now.astimezone(IST).date().isoformat()
    for advice in answers[:10]:
        agent = str(advice.get("agent") or "")
        if agent not in known:
            continue
        cause = " ".join(str(advice.get("cause") or "").split())[:300]
        fix = " ".join(str(advice.get("fix") or "").split())[:300]
        who = str(advice.get("who") or "operator")
        if who == "head" and agent in agents:
            head = _head_of(agent, agents)
            first = next(p for p in problems if p.agent == agent)
            task = tasks.create(
                title=f"Watchdog: {first.title}"[:200],
                owner=head,
                department=agents[head].spec.reports_to if head in agents else "platform",
                created_by=ctx.name,
                detail=f"{first.body[:800]}\n\nLikely cause: {cause}\nFix: {fix}",
                key=f"watchdog|{agent}|{first.kind}|{day}",
                root=ctx.root,
                now=ctx.now,
            )
            items.append(
                Item(
                    kind="finding",
                    title=f"{agent}: given to {head} ({task.id})",
                    body=f"Cause: {cause}. Fix: {fix}",
                    severity="info",
                )
            )
        elif who == "operator":
            items.append(
                Item(
                    kind="alert",
                    title=f"Needs you — {agent}: {cause[:120]}",
                    body=fix,
                    severity="warn",
                    needs_approval=True,
                )
            )
        else:
            items.append(
                Item(
                    kind="finding",
                    title=f"{agent}: will clear on its own",
                    body=f"Cause: {cause}. {fix}",
                    severity="info",
                )
            )
    return items


def _parse(text: str) -> dict[str, Any]:
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        raise ValueError("no JSON object in the answer")
    body = json.loads(match.group(0))
    if not isinstance(body, dict) or not isinstance(body.get("problems"), list):
        raise ValueError("the answer has no problems list")
    body["problems"] = [p for p in body["problems"] if isinstance(p, dict)]
    return body


def run(ctx: Context) -> WorkerResult:
    agents = all_effective(ctx.root)
    ctx.step(f"Checking {len(agents)} agents' runs, model use and tasks")
    run_problems, seen = check_runs(agents, now=ctx.now, root=ctx.root, options=ctx.options)
    use_problems, spend = check_model_use(agents, seen, now=ctx.now, options=ctx.options)
    task_problems = check_tasks(ctx.root, now=ctx.now)
    problems = run_problems + use_problems + task_problems
    reran, items = remedy(ctx, problems)
    # What a re-run fixed is not asked about.
    fixed = {
        i.title.split(":")[0].removeprefix("re-ran ").strip()
        for i in items
        if i.title.endswith(": ok")
    }
    left = [
        p for p in problems if not (p.agent in fixed and p.kind in ("failed", "missed", "stuck"))
    ]
    items = [
        Item(
            kind="alert",
            title=p.title,
            body=p.body,
            severity=p.severity,
            data={"agent": p.agent, "kind": p.kind},
        )
        for p in left
    ] + items
    items += ask_for_help(ctx, left, agents)
    ran = sum(len(v) for v in seen.values())
    bad = sum(1 for v in seen.values() for o in v if o.status in BAD)
    summary = (
        f"{len(seen)} agents, {ran} runs in the last day ({bad} failed); "
        f"{len(left)} problem(s) open"
        + (f", re-ran {', '.join(reran)}" if reran else "")
        + f"; {spend['tokens_24h']:,} tokens in 24 hours."
    )
    return WorkerResult(
        summary,
        items,
        data={
            "problems": [p.__dict__ for p in left],
            "reran": reran,
            **spend,
            "runs": {k: [f"{o.started} {o.status}" for o in v] for k, v in seen.items()},
        },
    )
