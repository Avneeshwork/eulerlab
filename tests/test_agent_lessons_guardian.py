"""Lessons and the guardian (ADR-152)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from eulerlab.agents import guardian, lessons, runtime
from eulerlab.agents.runtime import Output
from eulerlab.intraday import rule_engine as engine

HISTORY_SAMPLE = """# What was built

**1. Download time was being used as knowledge time.** (Sprint 4) Every landed
file recorded when we fetched it. More text.

**85. The autopilot's first three passes were one bet, already held.** (2026-11-08) The first nightly batch gated three. Each shorts a stock.

**68a. A lettered entry.** (2026-11-02) It counts too.
"""


def test_history_entries_parse_number_title_and_first_sentence() -> None:
    found = lessons.history_entries(HISTORY_SAMPLE)
    assert [n for n, _, _ in found] == ["1", "85", "68a"]
    assert found[1][1] == "The autopilot's first three passes were one bet, already held"
    assert found[1][2] == "The first nightly batch gated three."


def test_seeding_is_idempotent(tmp_path: Path) -> None:
    history = tmp_path / "HISTORY.md"
    history.write_text(HISTORY_SAMPLE, encoding="utf-8")
    root = tmp_path / "agents"
    first = lessons.seed(root, history)
    again = lessons.seed(root, history)
    assert first.history == 3
    assert again.history == 0
    assert again.total == first.total == 3 + len(lessons.BUILT_IN)
    assert again.checks == sorted(c for c, _, _ in lessons.BUILT_IN)


def test_relevant_puts_operator_first_and_needs_overlap(tmp_path: Path) -> None:
    root = tmp_path
    lessons.add("Never short small caps at the open price", source="operator", ref="m1", root=root)
    lessons.add(
        "Delivery ratio rallies fade intraday on thin delivery",
        source="history",
        ref="H1",
        root=root,
    )
    lessons.add("Unrelated note about crypto bars", source="history", ref="H2", root=root)
    lessons.add("For the data agent only", source="doctor", ref="D1", agents=["data"], root=root)
    found = lessons.relevant("research", "a rule on thin delivery ratio rallies", root=root)
    assert [x.ref for x in found] == ["m1", "H1"]
    assert "data agent" in lessons.relevant("data", "anything", root=root)[1].text


def test_retired_lessons_are_not_served(tmp_path: Path) -> None:
    lesson = lessons.add(
        "Old rule about delivery ratio", source="operator", ref="m2", root=tmp_path
    )
    lessons.retire(lesson.id, why="superseded", root=tmp_path)
    assert lessons.load(tmp_path) == []
    assert lessons.load(tmp_path, include_retired=True)[0].retired


def _spec(**body: Any) -> engine.RuleSpec:
    return engine.RuleSpec.model_validate(body)


def test_price_only_intraday_rule_breaks_the_coded_lesson(tmp_path: Path) -> None:
    lessons.seed_checks(tmp_path)
    price_only = _spec(
        kind="intraday",
        side="short",
        when=[{"signal": "gap", "op": ">=", "value": 0.03}],
        rank_by={"signal": "gap"},
    )
    with_delivery = _spec(
        kind="intraday",
        side="short",
        when=[
            {"signal": "gap", "op": ">=", "value": 0.02},
            {"signal": "delivery_ratio", "lag": 1, "op": "<=", "value": 0.8},
        ],
        rank_by={"signal": "gap"},
    )
    assert lessons.violations(price_only, root=tmp_path)
    assert lessons.violations(with_delivery, root=tmp_path) == []


def test_autopilot_accept_drops_a_card_that_breaks_a_lesson() -> None:
    from eulerlab.agents.workers import autopilot as writer

    lessons.seed_checks()  # the default root, redirected to a private file by conftest
    raw = [
        {
            "title": "gap fade",
            "engine": {
                "kind": "intraday",
                "side": "short",
                "when": [{"signal": "gap", "op": ">=", "value": 0.03}],
                "rank_by": {"signal": "gap"},
            },
        }
    ]
    kept, dropped = writer.accept(raw, {})
    assert kept == []
    assert "breaks a lesson" in dropped[0]


def test_context_ask_carries_relevant_lessons(tmp_path: Path) -> None:
    lessons.add("Never trade on stale delivery data", source="operator", ref="m3", root=tmp_path)
    seen: dict[str, str] = {}

    def asker(system: str, user: str, accept: Any) -> str:
        seen["system"] = system
        return "ok"

    def worker(ctx: runtime.Context) -> runtime.WorkerResult:
        ctx.ask("You write rules", "about delivery data")
        return runtime.WorkerResult("done")

    agents = _agents()
    out = runtime.run("tester", root=tmp_path, agents=agents, asker=asker, worker=worker)
    assert "Never trade on stale delivery data" in seen["system"]
    assert out.lessons == [lessons.lesson_id("operator", "m3")]


def _agents() -> dict[str, Any]:
    from eulerlab.agents.spec import AgentSpec, effective

    spec = AgentSpec.model_validate(
        {
            "name": "tester",
            "title": "Tester",
            "worker": "eulerlab.agents.workers.tester",
            "uses_model": True,
            "daily_requests": 5,
            "job": "a test agent that asks once",
        }
    )
    return {"tester": effective(spec, None)}


def _out(status: str = "ok", summary: str = "s", **kw: Any) -> Output:
    now = datetime(2026, 11, 9, 4, 0, tzinfo=UTC).isoformat()
    return Output(
        agent=kw.pop("agent", "tester"),
        run_id=kw.pop("run_id", "r"),
        started=now,
        finished=now,
        status=status,
        summary=summary,
        **kw,
    )


def _facts(tmp_path: Path, output: Output, recent: list[Output]) -> guardian.Facts:
    return guardian.Facts(output, recent, tmp_path, datetime(2026, 11, 9, tzinfo=UTC), tmp_path)


def test_three_failures_in_a_row_are_held(tmp_path: Path) -> None:
    runs = [_out("failed", run_id=f"r{i}") for i in range(3)]
    trip = guardian.repeated_failure(_facts(tmp_path, runs[0], runs))
    assert trip is not None and trip.action == "hold"
    mixed = [runs[0], _out("ok"), runs[2]]
    assert guardian.repeated_failure(_facts(tmp_path, runs[0], mixed)) is None


def test_made_up_figures_suspend(tmp_path: Path) -> None:
    note = "answer withheld: unsupported figures (12.5%)"
    runs = [_out(notes=[note], run_id=f"r{i}") for i in range(3)]
    trip = guardian.made_up_figures(_facts(tmp_path, runs[0], runs))
    assert trip is not None and trip.action == "suspend"


def test_too_good_holds_without_switching_off(tmp_path: Path) -> None:
    out = _out(agent="autopilot", data={"net_sharpe": {"H-0175": 3.966, "H-0174": 2.3}})
    trip = guardian.too_good(_facts(tmp_path, out, [out]))
    assert trip is not None and trip.action == "hold" and "H-0175" in trip.why
    assert "H-0174" not in trip.why


def test_ledger_over_allowance(tmp_path: Path) -> None:
    log = tmp_path / "autopilot" / "gates.jsonl"
    log.parent.mkdir(parents=True)
    rows = [
        {"at": "2026-11-08T10:00:00+00:00", "hypothesis": f"H-{i}", "entries": 2} for i in range(6)
    ]
    log.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    out = _out(agent="autopilot")
    trip = guardian.ledger_over_allowance(_facts(tmp_path, out, [out]))
    assert trip is not None and "12 ledger entries" in trip.why


def test_protected_change_halts_every_agent_until_cleared(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "src/eulerlab").mkdir(parents=True)
    (repo / "mandate.yaml").write_text("a: 1\n", encoding="utf-8")
    (repo / "src/eulerlab/gates.py").write_text("x = 1\n", encoding="utf-8")
    root = tmp_path / "agents"
    told: list[str] = []
    out = _out()
    assert guardian.after_run(out, root, repo=repo, tell=told.append) == []  # baseline written
    (repo / "mandate.yaml").write_text("a: 2\n", encoding="utf-8")
    acted = guardian.after_run(out, root, repo=repo, tell=told.append)
    assert [t.rule for t in acted] == ["protected_changed"]
    assert guardian.halted(root)
    assert told and "halt" in told[0]
    # the halt stops the next run before its worker starts
    called: list[bool] = []

    def worker(ctx: runtime.Context) -> runtime.WorkerResult:
        called.append(True)
        return runtime.WorkerResult("ran")

    skipped = runtime.run("tester", root=root, agents=_agents(), worker=worker)
    assert skipped.status == "skipped" and not called
    # acting twice changes nothing; clearing needs a reason and re-baselines
    assert guardian.after_run(out, root, repo=repo, tell=told.append) == []
    with pytest.raises(ValueError):
        guardian.clear("", root, repo)
    guardian.clear("I changed the mandate myself", root, repo)
    assert not guardian.halted(root)
    assert guardian.after_run(out, root, repo=repo, tell=told.append) == []


def test_a_trip_writes_a_lesson(tmp_path: Path) -> None:
    trip = guardian.Trip("too_good", "autopilot", "hold", "net Sharpe 3.97")
    guardian.act(trip, tmp_path, tell=lambda _: None)
    held = lessons.load(tmp_path)
    assert held and held[0].source == "guardian" and held[0].agents == ("autopilot",)


def test_after_run_never_raises(tmp_path: Path) -> None:
    class Broken:
        agent = "x"
        run_id = "y"

    assert guardian.after_run(Broken(), tmp_path, tell=lambda _: None) == []


# --- the feedback desk ------------------------------------------------------------------


def test_feedback_classifies_rules_agents_and_heads() -> None:
    from eulerlab.agents import feedback

    agents = {"autopilot", "research"}
    assert feedback.classify("Never short stocks under 50", agents)[:2] == ("lesson", "all")
    assert feedback.classify("autopilot: try F&O ban days", agents)[:2] == ("lesson", "autopilot")
    assert feedback.classify("lesson: results days are noisy", agents)[:2] == ("lesson", "all")
    assert feedback.classify("make the data page faster", agents)[:2] == ("task", "head_platform")
    assert feedback.classify("goal: second paper book live", agents)[:2] == (
        "task",
        "head_portfolio",
    )
    assert feedback.classify("look at block deals in midcaps", agents)[:2] == (
        "task",
        "head_research",
    )


def test_feedback_routes_to_a_lesson_and_a_task(tmp_path: Path) -> None:
    from eulerlab.agents import feedback, tasks

    a = feedback.route("Always skip ASM stocks", root=tmp_path, agents=set())
    assert a.kind == "lesson" and lessons.load(tmp_path)[0].source == "operator"
    b = feedback.route("check the kite token every morning", root=tmp_path, agents=set())
    assert b.kind == "task" and tasks.load(tmp_path)[b.target].owner == "head_platform"
    assert [r.id for r in feedback.history(tmp_path)] == [a.id, b.id]
