"""The agent runtime: budgets, switches, failures, the log chain, briefs and the inbox (ADR-085)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from eulerlab.agents import boundaries, briefs, inbox, log, runtime
from eulerlab.agents.runtime import Context, Item, WorkerResult
from eulerlab.agents.spec import AgentSpec, Effective, Settings, effective, load_specs

NOW = datetime(2026, 10, 29, 4, 0, tzinfo=UTC)


def _agents(**overrides: Any) -> dict[str, Effective]:
    spec = AgentSpec(
        name="demo",
        title="Demo agent",
        job="does one small thing for a test",
        worker="eulerlab.agents.workers.data",
        uses_model=True,
        daily_requests=2,
        **overrides,
    )
    return {"demo": effective(spec, None)}


def _asker(system: str, user: str, accept: object) -> str:
    return "fine"


def test_every_definition_loads_and_names_a_worker_that_exists() -> None:
    specs = load_specs()
    assert {"data", "knowledge", "market_brief", "research", "skeptic", "engineering"} <= set(specs)
    for spec in specs.values():
        module = spec.worker.removeprefix("eulerlab.agents.workers.")
        assert (Path("src/eulerlab/agents/workers") / f"{module}.py").exists()


def test_settings_only_narrow_a_definition() -> None:
    spec = AgentSpec(
        name="xy",
        title="X agent",
        job="a job for the test",
        worker="eulerlab.agents.workers.data",
        enabled=False,
        daily_requests=5,
    )
    on = effective(spec, Settings(enabled=True, daily_requests=50))
    assert on.enabled is False and on.daily_requests == 5
    lower = effective(spec, Settings(daily_requests=1))
    assert lower.daily_requests == 1 and lower.switched == "operator"


def test_a_run_writes_its_output_and_one_log_entry(tmp_path: Path) -> None:
    def worker(ctx: Context) -> WorkerResult:
        ctx.ask("system", "user")
        return WorkerResult("done", [Item(kind="finding", title="something", needs_approval=True)])

    out = runtime.run("demo", root=tmp_path, agents=_agents(), asker=_asker, now=NOW, worker=worker)
    assert out.status == "ok" and out.requests == 1 and out.items[0].id.startswith("demo-")
    saved = json.loads((tmp_path / "demo" / out.run_id / "output.json").read_text())
    assert saved["summary"] == "done"
    assert log.requests_on("demo", "2026-10-29", tmp_path) == 1
    assert log.verify(tmp_path) == (True, "")


def test_the_daily_budget_carries_across_runs(tmp_path: Path) -> None:
    def greedy(ctx: Context) -> WorkerResult:
        for _ in range(5):
            ctx.ask("s", "u")
        return WorkerResult("never")

    first = runtime.run(
        "demo", root=tmp_path, agents=_agents(), asker=_asker, now=NOW, worker=greedy
    )
    assert first.status == "over_budget"

    def one(ctx: Context) -> WorkerResult:
        return WorkerResult(f"can ask: {ctx.can_ask()}")

    second = runtime.run("demo", root=tmp_path, agents=_agents(), asker=_asker, now=NOW, worker=one)
    assert second.summary == "can ask: False"  # the over-budget run spent both


def test_a_switched_off_agent_does_not_run(tmp_path: Path) -> None:
    called: list[bool] = []

    def worker(ctx: Context) -> WorkerResult:
        called.append(True)
        return WorkerResult("ran")

    out = runtime.run("demo", root=tmp_path, agents=_agents(enabled=False), now=NOW, worker=worker)
    assert out.status == "skipped" and not called


def test_a_crashing_worker_is_recorded_not_raised(tmp_path: Path) -> None:
    def worker(ctx: Context) -> WorkerResult:
        raise RuntimeError("boom")

    out = runtime.run("demo", root=tmp_path, agents=_agents(), now=NOW, worker=worker)
    assert out.status == "failed" and "boom" in out.summary and out.notes


def test_a_worker_cannot_write_outside_its_run_folder(tmp_path: Path) -> None:
    def worker(ctx: Context) -> WorkerResult:
        ctx.write("../escape.txt", "x")
        return WorkerResult("wrote")

    out = runtime.run("demo", root=tmp_path, agents=_agents(), now=NOW, worker=worker)
    assert out.status == "failed" and not (tmp_path / "escape.txt").exists()


def test_an_edited_log_line_breaks_the_chain(tmp_path: Path) -> None:
    log.append("run", "demo", {"n": 1}, root=tmp_path)
    log.append("run", "demo", {"n": 2}, root=tmp_path)
    path = log.path_for(tmp_path)
    lines = path.read_text().splitlines()
    lines[0] = lines[0].replace('"n": 1', '"n": 9')
    path.write_text("\n".join(lines) + "\n")
    ok, problem = log.verify(tmp_path)
    assert not ok and problem


def test_briefs_reach_the_model_and_are_recorded(tmp_path: Path) -> None:
    briefs.write("all", "be brief", root=tmp_path)
    mine = briefs.write("demo", "look at banks", root=tmp_path)
    seen: list[str] = []

    def asker(system: str, user: str, accept: object) -> str:
        seen.append(system)
        return "ok"

    def worker(ctx: Context) -> WorkerResult:
        ctx.ask("system", "user")
        return WorkerResult("ok")

    out = runtime.run("demo", root=tmp_path, agents=_agents(), asker=asker, now=NOW, worker=worker)
    assert "look at banks" in seen[0] and "be brief" in seen[0]
    assert mine.id in out.briefs


def test_the_inbox_records_one_decision_per_item(tmp_path: Path) -> None:
    def worker(ctx: Context) -> WorkerResult:
        return WorkerResult(
            "two",
            [
                Item(kind="proposal", title="do it", needs_approval=True),
                Item(kind="finding", title="just so you know"),
            ],
        )

    runtime.run("demo", root=tmp_path, agents=_agents(), now=NOW, worker=worker)
    waiting = inbox.pending(tmp_path, names=["demo"])
    assert [w["title"] for w in waiting] == ["do it"]
    inbox.decide(waiting[0]["id"], "approved", root=tmp_path, names=["demo"])
    assert inbox.pending(tmp_path, names=["demo"]) == []
    with pytest.raises(ValueError):
        inbox.decide(waiting[0]["id"], "dismissed", root=tmp_path, names=["demo"])


def test_no_agent_module_imports_the_order_path_gate_ledger_env_or_a_shell() -> None:
    modules = boundaries.agent_modules()
    assert len(modules) >= 15
    problems = [v for m in modules for v in boundaries.violations(m)]
    assert problems == []


def test_the_boundary_check_catches_a_forbidden_import(tmp_path: Path) -> None:
    bad = tmp_path / "bad.py"
    bad.write_text("from eulerlab.oms import ems\nimport subprocess\n")
    assert len(boundaries.violations(bad)) == 3
