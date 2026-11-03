"""The agent company at work (ADR-124): tasks, heads, the work runner, plans and capabilities."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from eulerlab.agents import capabilities, log, plans, runtime, tasks, work
from eulerlab.agents.runtime import Context, WorkerResult
from eulerlab.agents.spec import AgentSpec, Skill, all_effective, load_specs
from eulerlab.agents.workers import manager

NOW = datetime(2026, 11, 3, 4, 0, tzinfo=UTC)  # 09:30 IST, a Tuesday


def _at(minutes: int) -> datetime:
    return NOW + timedelta(minutes=minutes)


def _ceo_task(
    root: Path, title: str, detail: str = "", dept: str = "research", minute: int = 0
) -> tasks.Task:
    return tasks.create(
        title=title,
        detail=detail,
        owner=f"head_{dept}",
        department=dept,
        created_by="ceo",
        root=root,
        now=_at(minute),
    )


def _asker(answer: str | Exception) -> runtime.Asker:
    def ask(system: str, user: str, accept: Callable[[str], object] | None) -> str:
        if isinstance(answer, Exception):
            raise answer
        return answer

    return ask


def _head(root: Path, dept: str, answer: str | Exception, minute: int = 1) -> runtime.Output:
    return runtime.run(f"head_{dept}", root=root, asker=_asker(answer), now=_at(minute))


def _ok(summary: str = "did it") -> Callable[[Context], WorkerResult]:
    return lambda ctx: WorkerResult(summary)


# --- the task log ------------------------------------------------------------


def test_a_task_is_the_fold_of_its_events_and_each_event_is_logged(tmp_path: Path) -> None:
    t = _ceo_task(tmp_path, "Find papers on low volatility")
    assert t.status == "open" and t.owner == "head_research" and t.due == "2026-11-03"
    tasks.record(t.id, "blocked", "head_research", {"note": "why"}, root=tmp_path, now=_at(1))
    again = tasks.reopen(t.id, "ceo", "try again", root=tmp_path, now=_at(2))
    assert again.status == "open"
    assert [h["event"] for h in again.history] == ["created", "blocked", "reopened"]
    entries = [e for e in log.read(tmp_path) if e.kind == "task"]
    assert [e.detail["event"] for e in entries] == ["created", "blocked", "reopened"]
    assert log.verify(tmp_path)[0]


def test_the_same_key_gives_the_same_task(tmp_path: Path) -> None:
    kw = {
        "title": "Fix x.py",
        "owner": "engineering",
        "department": "platform",
        "created_by": "doctor",
    }
    first = tasks.create(**kw, key="doctor|x.py", root=tmp_path, now=_at(0))  # type: ignore[arg-type]
    second = tasks.create(**kw, key="doctor|x.py", root=tmp_path, now=_at(5))  # type: ignore[arg-type]
    assert first.id == second.id and len(tasks.load(tmp_path)) == 1


@pytest.mark.parametrize(
    ("events", "refused"),
    [
        ([], "finished"),  # finished before it started
        (["started", "finished", "accepted"], "accepted"),  # accepted twice
        ([], "closed"),  # closed before it was done
    ],
)
def test_an_event_that_does_not_fit_is_refused(
    tmp_path: Path, events: list[str], refused: str
) -> None:
    t = tasks.create(
        title="Look",
        owner="research",
        department="research",
        created_by="head_research",
        root=tmp_path,
    )
    for e in events:
        tasks.record(t.id, e, "x", root=tmp_path)  # type: ignore[arg-type]
    with pytest.raises(tasks.Refused):
        tasks.record(t.id, refused, "x", root=tmp_path)  # type: ignore[arg-type]


def test_a_task_is_sent_back_at_most_twice(tmp_path: Path) -> None:
    t = tasks.create(
        title="Look",
        owner="research",
        department="research",
        created_by="head_research",
        root=tmp_path,
    )
    for _ in range(tasks.MAX_RETURNS):
        tasks.record(t.id, "started", "x", root=tmp_path)
        tasks.record(t.id, "finished", "x", root=tmp_path)
        tasks.record(t.id, "sent_back", "x", root=tmp_path)
    tasks.record(t.id, "started", "x", root=tmp_path)
    tasks.record(t.id, "finished", "x", root=tmp_path)
    with pytest.raises(tasks.Refused, match="already sent back"):
        tasks.record(t.id, "sent_back", "x", root=tmp_path)


# --- a head splits your task ---------------------------------------------------


def test_the_model_splits_and_anything_off_the_roster_is_dropped(tmp_path: Path) -> None:
    t = _ceo_task(tmp_path, "Low volatility in Indian stocks", "papers, and attack our best result")
    answer = json.dumps(
        {
            "subtasks": [
                {
                    "agent": "research",
                    "kind": "research_topic",
                    "value": "low volatility India",
                    "title": "Papers",
                },
                {
                    "agent": "skeptic",
                    "kind": "attack_result",
                    "value": "low_vol_30",
                    "title": "Attack it",
                },
                {
                    "agent": "trader",
                    "kind": "buy",
                    "value": "RELIANCE",
                    "title": "Buy",
                },  # not on the team
                {
                    "agent": "data",
                    "kind": "check_dataset",
                    "value": "x",
                    "title": "Other team's agent",
                },
                {
                    "agent": "research",
                    "kind": "attack_result",
                    "value": "x",
                    "title": "Not its skill",
                },
            ]
        }
    )
    _head(tmp_path, "research", answer)
    known = tasks.load(tmp_path)
    parent = known[t.id]
    subs = tasks.children(known, t.id)
    assert parent.status == "assigned" and parent.planned_by == "model"
    assert sorted((s.owner, s.kind, s.args) for s in subs) == [
        ("research", "research_topic", {"topic": "low volatility India"}),
        ("skeptic", "attack_result", {"strategy": "low_vol_30"}),
    ]
    assert all(s.status == "assigned" and s.created_by == "head_research" for s in subs)


@pytest.mark.parametrize(
    "answer",
    [
        RuntimeError("provider down"),
        "not json at all",
        json.dumps({"subtasks": [{"agent": "nobody", "kind": "attack_result", "value": "x"}]}),
    ],
)
def test_without_a_usable_model_answer_the_fixed_rules_split_it(
    tmp_path: Path, answer: str | Exception
) -> None:
    t = _ceo_task(tmp_path, "Attack the momentum result for overfitting")
    out = _head(tmp_path, "research", answer)
    known = tasks.load(tmp_path)
    subs = tasks.children(known, t.id)
    assert known[t.id].planned_by == "rules"
    assert [(s.owner, s.kind) for s in subs] == [("skeptic", "attack_result")]
    assert any("fixed rules used" in n for n in out.notes)


def test_no_budget_means_rules_without_asking(tmp_path: Path) -> None:
    _ceo_task(tmp_path, "Find papers on the topic of quality", dept="research")
    asked: list[str] = []

    def ask(system: str, user: str, accept: Callable[[str], object] | None) -> str:
        asked.append(user)
        return "{}"

    agents = all_effective(tmp_path)
    spec = agents["head_research"].spec.model_copy(update={"daily_requests": 0})
    agents["head_research"] = agents["head_research"].model_copy(
        update={"spec": spec, "daily_requests": 0}
    )
    runtime.run("head_research", root=tmp_path, asker=ask, agents=agents, now=_at(1))
    assert asked == []
    subs = [t for t in tasks.load(tmp_path).values() if t.parent]
    assert [(s.owner, s.kind) for s in subs] == [("research", "research_topic")]


def test_a_task_no_agent_can_do_is_blocked_and_names_what_they_can(tmp_path: Path) -> None:
    # "morning" is one of the market brief's fallback words; the model's judgement wins.
    t = _ceo_task(tmp_path, "Buy shares tomorrow morning", dept="portfolio")
    out = _head(
        tmp_path, "portfolio", json.dumps({"subtasks": [], "why": "no agent trades"}), minute=1
    )
    blocked = tasks.load(tmp_path)[t.id]
    assert blocked.status == "blocked"
    note = blocked.history[-1]["note"]
    assert "no agent here can do this" in note and "no agent trades" in note
    assert "market_brief can" in note
    assert any(i.kind == "alert" and i.ref == t.id for i in out.items)


def test_without_a_model_a_task_sharing_no_word_with_any_skill_is_blocked(tmp_path: Path) -> None:
    t = _ceo_task(tmp_path, "Order lunch", dept="portfolio")
    _head(tmp_path, "portfolio", RuntimeError("no model"))
    assert tasks.load(tmp_path)[t.id].status == "blocked"


def test_a_choice_argument_is_held_to_its_choices(tmp_path: Path) -> None:
    _ceo_task(tmp_path, "Write the market brief after the close", dept="portfolio")
    answer = json.dumps(
        {"subtasks": [{"agent": "market_brief", "kind": "write_brief", "value": "lunchtime"}]}
    )
    _head(tmp_path, "portfolio", answer)
    sub = next(t for t in tasks.load(tmp_path).values() if t.parent)
    assert sub.args == {"mode": "after-close"}


# --- the checklist, the runner and the roll-up -----------------------------------


def _split_one(tmp_path: Path) -> tuple[tasks.Task, tasks.Task]:
    t = _ceo_task(tmp_path, "Find papers on low volatility")
    _head(tmp_path, "research", RuntimeError("no model"))
    known = tasks.load(tmp_path)
    return known[t.id], tasks.children(known, t.id)[0]


def test_a_finished_task_that_passes_the_checklist_is_passed_up(tmp_path: Path) -> None:
    parent, sub = _split_one(tmp_path)
    seen: list[dict[str, object]] = []

    def worker(ctx: Context) -> WorkerResult:
        seen.append(dict(ctx.args))
        return WorkerResult("3 leads, 1 draft")

    ran = work.run_due(root=tmp_path, now=_at(5), worker=worker)
    assert [t.id for t in ran] == [sub.id]
    assert seen == [{"topic": sub.args["topic"], "task": sub.id}]
    known = tasks.load(tmp_path)
    assert known[sub.id].status == "done"
    assert known[parent.id].status == "done" and "3 leads, 1 draft" in known[parent.id].summary
    tasks.record(parent.id, "closed", "ceo", root=tmp_path)
    assert tasks.load(tmp_path)[parent.id].status == "closed"


def test_a_failed_run_is_sent_back_twice_then_blocked_for_you(tmp_path: Path) -> None:
    parent, sub = _split_one(tmp_path)

    def broken(ctx: Context) -> WorkerResult:
        raise RuntimeError("boom")

    for i in range(tasks.MAX_RETURNS + 1):
        work.run_due(root=tmp_path, now=_at(5 + i), worker=broken)
    known = tasks.load(tmp_path)
    assert known[sub.id].status == "blocked" and known[sub.id].returns == tasks.MAX_RETURNS
    assert known[parent.id].status == "blocked"
    assert work.run_due(root=tmp_path, now=_at(20), worker=broken) == []  # nothing more runs


def test_a_refused_run_is_blocked_at_once(tmp_path: Path) -> None:
    _, sub = _split_one(tmp_path)
    work.run_due(
        root=tmp_path,
        now=_at(5),
        worker=lambda ctx: WorkerResult("no such report", status="refused"),
    )
    assert tasks.load(tmp_path)[sub.id].status == "blocked"


def test_retrying_a_blocked_parent_cancels_the_old_round_and_splits_afresh(tmp_path: Path) -> None:
    parent, sub = _split_one(tmp_path)
    work.run_due(root=tmp_path, now=_at(5), worker=lambda ctx: WorkerResult("no", status="refused"))
    manager.roll_up("head_research", tmp_path, _at(6))
    tasks.reopen(parent.id, "ceo", "try a narrower topic", root=tmp_path, now=_at(7))
    _head(tmp_path, "research", RuntimeError("no model"), minute=8)
    known = tasks.load(tmp_path)
    assert known[sub.id].status == "cancelled"
    fresh = tasks.children(known, parent.id)
    assert len(fresh) == 1 and fresh[0].id != sub.id and fresh[0].status == "assigned"


def test_a_skill_that_is_not_auto_waits_for_you(tmp_path: Path) -> None:
    t = tasks.create(
        title="Fix x.py",
        owner="engineering",
        department="platform",
        created_by="head_platform",
        kind="fix_code",
        root=tmp_path,
        now=_at(0),
    )
    assert work.run_due(root=tmp_path, now=_at(1), worker=_ok()) == []
    seen: list[dict[str, object]] = []

    def worker(ctx: Context) -> WorkerResult:
        seen.append(dict(ctx.args))
        return WorkerResult("1 fix ready")

    done = work.run_one(t.id, by="ceo", root=tmp_path, now=_at(2), worker=worker)
    assert done.status == "done" and seen == [{"mode": "fix", "task": t.id}]


def test_a_terminal_only_agent_is_never_started_from_a_task(tmp_path: Path) -> None:
    t = tasks.create(
        title="Test card c1",
        owner="lab",
        department="research",
        created_by="head_research",
        kind="test_card",
        args={"card": "hypotheses/c1"},
        root=tmp_path,
    )
    with pytest.raises(tasks.Refused, match="make agent NAME=lab ARGS='card=hypotheses/c1"):
        work.run_one(t.id, root=tmp_path, worker=_ok())


def test_a_task_for_a_kind_the_agent_does_not_list_is_refused(tmp_path: Path) -> None:
    t = tasks.create(
        title="Run the gate",
        owner="research",
        department="research",
        created_by="x",
        kind="run_gate",
        root=tmp_path,
    )
    with pytest.raises(tasks.Refused, match="does not list run_gate"):
        work.run_one(t.id, root=tmp_path, worker=_ok())


# --- hand-offs become tasks ------------------------------------------------------


def test_doctor_and_research_hand_offs_become_tasks_once(tmp_path: Path) -> None:
    doc = tmp_path / "doctor"
    doc.mkdir()
    problem = {
        "kind": "code_error",
        "agent": "lab",
        "run": "r1",
        "detail": "x",
        "file": "src/eulerlab/a.py",
        "error": "E",
    }
    (doc / "code_queue.jsonl").write_text(json.dumps(problem) + "\n", encoding="utf-8")
    refused = {
        "kind": "data_refused",
        "agent": "skeptic",
        "run": "r2",
        "detail": "needs grade B prices",
    }
    (doc / "log.jsonl").write_text(json.dumps(refused) + "\n", encoding="utf-8")
    out = runtime.Output(
        agent="research",
        run_id="20261103T030000Z-abcdef",
        started=NOW.isoformat(),
        finished=NOW.isoformat(),
        status="ok",
        summary="s",
        items=[
            runtime.Item(
                kind="data_request", title="NSE bulk deals", data={"dataset": "bulk_deals"}
            )
        ],
    )
    folder = tmp_path / "research" / out.run_id
    folder.mkdir(parents=True)
    (folder / "output.json").write_text(out.model_dump_json(), encoding="utf-8")

    work.handoffs(tmp_path, _at(0))
    work.handoffs(tmp_path, _at(1))
    known = tasks.load(tmp_path)
    assert sorted((t.owner, t.kind, t.created_by) for t in known.values()) == [
        ("data", "check_dataset", "doctor"),
        ("data", "check_dataset", "research"),
        ("engineering", "fix_code", "doctor"),
    ]
    # The engineering agent's own run fixed the file: it leaves the queue, and its task is done.
    (doc / "code_queue.jsonl").write_text("", encoding="utf-8")
    work.handoffs(tmp_path, _at(2))
    fix = next(t for t in tasks.load(tmp_path).values() if t.kind == "fix_code")
    assert fix.status == "done"


# --- plans ---------------------------------------------------------------------------


def test_todays_plan_lists_duties_schedule_and_tasks_due_first(tmp_path: Path) -> None:
    for title, due in (("later", "2026-11-05"), ("sooner", "2026-11-03")):
        tasks.create(
            title=title, owner="data", department="platform", created_by="x", due=due, root=tmp_path
        )
    specs = load_specs()
    slots = [
        {
            "time": "08:45",
            "job": "agents-preopen",
            "what": "pre",
            "state": "ran",
            "agents": [{"name": "data", "run_id": "r", "status": "ok"}],
        },
        {
            "time": "16:15",
            "job": "agents-close",
            "what": "close",
            "state": "upcoming",
            "agents": [{"name": "data"}],
        },
    ]
    day = plans.for_agent(specs["data"], tasks.load(tmp_path), slots, NOW)
    assert day["duties"] == list(specs["data"].duties)
    assert [(s["time"], s["state"]) for s in day["scheduled"]] == [
        ("08:45", "ran"),
        ("16:15", "upcoming"),
    ]
    assert [t["title"] for t in day["tasks"]] == ["sooner", "later"]


def test_a_heads_plan_lists_its_agents_work_waiting_for_the_checklist(tmp_path: Path) -> None:
    t = tasks.create(
        title="Look",
        owner="research",
        department="research",
        created_by="head_research",
        root=tmp_path,
    )
    tasks.record(t.id, "started", "x", root=tmp_path)
    tasks.record(t.id, "finished", "x", root=tmp_path)
    day = plans.for_agent(load_specs()["head_research"], tasks.load(tmp_path), [], NOW)
    assert [x["id"] for x in day["to_check"]] == [t.id]


def test_the_head_writes_every_plan_into_its_run(tmp_path: Path) -> None:
    out = _head(tmp_path, "platform", RuntimeError("no model"))
    saved = json.loads(
        (tmp_path / "head_platform" / out.run_id / "plans.json").read_text(encoding="utf-8")
    )
    assert sorted(saved) == ["data", "engineering", "head_platform", "operations", "watchdog"]


# --- capabilities --------------------------------------------------------------------


def test_every_committed_agent_can_do_what_it_may_be_given() -> None:
    assert capabilities.report()["gaps"] == []


def test_a_skill_whose_argument_the_worker_never_reads_is_a_gap() -> None:
    specs = load_specs()
    data = specs["data"]
    specs["data"] = data.model_copy(
        update={
            "can_do": [
                *data.can_do,
                Skill(kind="nonsense", what="a thing it cannot", arg="colour", words=["x"]),
            ]
        }
    )
    found = capabilities.gaps(capabilities.audit(specs))
    assert any("data: reads colour" in g for g in found)


def test_an_agent_with_no_duties_or_skills_is_a_gap() -> None:
    specs = load_specs()
    specs["operations"] = specs["operations"].model_copy(update={"duties": [], "can_do": []})
    found = capabilities.gaps(capabilities.audit(specs))
    assert "operations: duties (0 listed)" in found
    assert "operations: takes work (none)" in found


def test_every_doctor_problem_has_an_owner() -> None:
    from eulerlab.agents import doctor

    assert set(capabilities.DOCTOR_OWNERS) == set(doctor.REMEDIES)


def test_a_head_never_imports_what_agents_may_not() -> None:
    from eulerlab.agents import boundaries

    source = Path("src/eulerlab/agents/workers/manager.py").read_text(encoding="utf-8")
    assert not any(f"import {m}" in source or f"from {m}" in source for m in boundaries.FORBIDDEN)


def test_the_spec_refuses_an_unknown_skill_field() -> None:
    with pytest.raises(ValueError):
        AgentSpec.model_validate(
            {
                "name": "x_agent",
                "title": "X agent",
                "job": "Does a thing well.",
                "worker": "eulerlab.agents.workers.data",
                "can_do": [{"kind": "abc", "what": "a thing", "spends": "money"}],
            }
        )


def test_a_run_that_failed_on_a_refusal_is_blocked_not_retried(tmp_path: Path) -> None:
    _, sub = _split_one(tmp_path)

    def no_key(ctx: Context) -> WorkerResult:
        return WorkerResult("Refused: No GROQ_API_KEY in .env.", status="failed")

    work.run_due(root=tmp_path, now=_at(5), worker=no_key)
    done = tasks.load(tmp_path)[sub.id]
    assert done.status == "blocked" and done.returns == 0
    assert "Running it again would not change that" in done.history[-1]["note"]


def test_the_data_agent_finds_a_dataset_named_by_its_words() -> None:
    from types import SimpleNamespace

    from eulerlab.agents.workers import data

    graded = {n: SimpleNamespace(name=n) for n in ("bulk_deals", "deals", "fii_dii")}
    found = data._held(graded, "check whether the bulk deals dataset is fresh")  # type: ignore[arg-type]
    assert found is not None and found.name == "bulk_deals"
    assert data._held(graded, "options chain") is None  # type: ignore[arg-type]


# --- AI help for a stuck task ------------------------------------------------------


def _stuck_skeptic(root: Path) -> tuple[tasks.Task, tasks.Task]:
    """A CEO task split to the skeptic, whose run refused: the subtask is blocked."""
    t = _ceo_task(root, "Attack the momentum result for overfitting")
    _head(root, "research", RuntimeError("no model"), minute=1)
    sub = tasks.children(tasks.load(root), t.id)[0]
    work.run_due(
        root=root,
        now=_at(2),
        worker=lambda ctx: WorkerResult(
            "No stored result for that report. Pick one from the list.", status="refused"
        ),
    )
    manager.roll_up("head_research", root, _at(3))
    known = tasks.load(root)
    assert known[sub.id].status == "blocked" and known[t.id].status == "blocked"
    return known[t.id], known[sub.id]


def test_a_stuck_task_is_fixed_by_ai_help_and_runs_again(tmp_path: Path) -> None:
    parent, sub = _stuck_skeptic(tmp_path)
    seen: list[str] = []

    def ask(system: str, user: str, accept: Callable[[str], object] | None) -> str:
        seen.append(user)
        return json.dumps(
            {
                "action": "retry",
                "value": "momentum_12_1",
                "why": "The stored result is momentum_12_1.",
            }
        )

    out = runtime.run("head_research", root=tmp_path, asker=ask, now=_at(4))
    known = tasks.load(tmp_path)
    fixed = known[sub.id]
    assert fixed.status == "assigned" and fixed.args == {"strategy": "momentum_12_1"}
    assert fixed.assists == 1 and fixed.returns == 0
    assert "AI help (retry)" in fixed.history[-1]["note"]
    assert known[parent.id].status == "assigned"  # nothing blocked any more
    assert "No stored result" in seen[0] and "<untrusted" in seen[0]
    assert sub.id in out.data["helped"]
    work.run_due(root=tmp_path, now=_at(5), worker=_ok("attacked: 3 of 5 attacks hurt it"))
    assert tasks.load(tmp_path)[parent.id].status == "done"


def test_ai_help_may_hand_the_task_to_another_agent_on_the_team(tmp_path: Path) -> None:
    _, sub = _stuck_skeptic(tmp_path)
    answer = {
        "action": "reassign",
        "agent": "knowledge",
        "kind": "answer_question",
        "value": "Which momentum results do we hold?",
    }
    runtime.run("head_research", root=tmp_path, asker=_asker(json.dumps(answer)), now=_at(4))
    fixed = tasks.load(tmp_path)[sub.id]
    assert (fixed.owner, fixed.kind, fixed.args) == (
        "knowledge",
        "answer_question",
        {"question": answer["value"]},
    )


@pytest.mark.parametrize(
    "answer",
    [
        {"action": "needs_ceo", "why": "No momentum result is stored; run the backtest first."},
        {
            "action": "reassign",
            "agent": "trader",
            "kind": "buy",
            "value": "x",
            "why": "off the roster",
        },
        {"action": "retry", "value": "", "why": "same as before"},
    ],
)
def test_ai_help_that_cannot_fix_it_writes_you_a_diagnosis_once(
    tmp_path: Path, answer: dict[str, str]
) -> None:
    _, sub = _stuck_skeptic(tmp_path)
    asked: list[int] = []

    def ask(system: str, user: str, accept: Callable[[str], object] | None) -> str:
        asked.append(1)
        return json.dumps(answer)

    runtime.run("head_research", root=tmp_path, asker=ask, now=_at(4))
    still = tasks.load(tmp_path)[sub.id]
    assert still.status == "blocked" and still.assists == 1
    assert still.history[-1]["note"].startswith("AI help")
    runtime.run("head_research", root=tmp_path, asker=ask, now=_at(5))
    assert len(asked) == 1  # not asked again on its own
    tasks.record(sub.id, "help_asked", "ceo", root=tmp_path, now=_at(6))
    runtime.run("head_research", root=tmp_path, asker=ask, now=_at(7))
    assert len(asked) == 2  # you asked, so once more


def test_without_a_model_a_stuck_task_waits_and_says_so_only_if_you_asked(tmp_path: Path) -> None:
    _, sub = _stuck_skeptic(tmp_path)
    runtime.run("head_research", root=tmp_path, asker=_asker(RuntimeError("down")), now=_at(4))
    quiet = tasks.load(tmp_path)[sub.id]
    assert (
        quiet.status == "blocked" and quiet.assists == 0 and quiet.history[-1]["event"] == "blocked"
    )
    tasks.record(sub.id, "help_asked", "ceo", root=tmp_path, now=_at(5))
    runtime.run("head_research", root=tmp_path, asker=_asker(RuntimeError("down")), now=_at(6))
    told = tasks.load(tmp_path)[sub.id]
    assert told.status == "blocked" and not told.help_wanted
    assert "AI help failed this time" in told.history[-1]["note"]


def test_a_rules_only_agent_gets_ai_help_through_its_head(tmp_path: Path) -> None:
    """The data agent has no model; when its task is stuck, its head's model helps."""
    t = tasks.create(
        title="Is the bulk deals data fresh?",
        owner="data",
        department="platform",
        created_by="head_platform",
        kind="check_dataset",
        args={"dataset": "Is the bulk deals data fresh?"},
        root=tmp_path,
        now=_at(0),
    )
    work.run_one(
        t.id,
        root=tmp_path,
        now=_at(1),
        worker=lambda ctx: WorkerResult("dataset not named", status="refused"),
    )
    answer = {"action": "retry", "value": "bulk_deals", "why": "The dataset is called bulk_deals."}
    runtime.run("head_platform", root=tmp_path, asker=_asker(json.dumps(answer)), now=_at(2))
    fixed = tasks.load(tmp_path)[t.id]
    assert fixed.status == "assigned" and fixed.args == {"dataset": "bulk_deals"}
    assert (
        all_effective(tmp_path)["data"].spec.uses_model is all_effective()["data"].spec.uses_model
    )


def test_a_value_sent_as_json_is_unwrapped(tmp_path: Path) -> None:
    _, sub = _stuck_skeptic(tmp_path)
    answer = {"action": "retry", "value": '{"strategy": "momentum_12_1"}', "why": "seen on Groq"}
    runtime.run("head_research", root=tmp_path, asker=_asker(json.dumps(answer)), now=_at(4))
    assert tasks.load(tmp_path)[sub.id].args == {"strategy": "momentum_12_1"}


def test_ai_help_is_shown_the_valid_names_and_held_to_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        manager,
        "known_values",
        lambda arg: ["momentum_12_1", "low_vol_30"] if arg == "strategy" else [],
    )
    _, sub = _stuck_skeptic(tmp_path)
    seen: list[str] = []

    def ask(system: str, user: str, accept: Callable[[str], object] | None) -> str:
        seen.append(user)
        return json.dumps({"action": "retry", "value": "momentum_best", "why": "guess"})

    runtime.run("head_research", root=tmp_path, asker=ask, now=_at(4))
    still = tasks.load(tmp_path)[sub.id]
    assert "Valid values for strategy: momentum_12_1, low_vol_30" in seen[0]
    assert still.status == "blocked" and "not a valid strategy" in still.history[-1]["note"]
    tasks.record(sub.id, "help_asked", "ceo", root=tmp_path, now=_at(5))
    runtime.run(
        "head_research",
        root=tmp_path,
        asker=_asker(
            json.dumps({"action": "retry", "value": "momentum_12_1", "why": "the stored one"})
        ),
        now=_at(6),
    )
    assert tasks.load(tmp_path)[sub.id].args == {"strategy": "momentum_12_1"}
