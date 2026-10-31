"""What an agent is doing now: the progress trail and the activity route (ADR-091)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from eulerlab.agents import runtime
from eulerlab.agents.runtime import Context, WorkerResult
from eulerlab.agents.spec import AgentSpec, Effective, effective, home
from eulerlab.api import agent_routes as r


def _agents() -> dict[str, Effective]:
    spec = AgentSpec(
        name="demo",
        title="Demo agent",
        job="does one small thing for a test",
        worker="eulerlab.agents.workers.data",
        uses_model=True,
        daily_requests=3,
    )
    return {"demo": effective(spec, None)}


def _worker(ctx: Context) -> WorkerResult:
    ctx.step("Reading the thing")
    ctx.notes.append("a note from deep inside a helper")
    ctx.ask("system", "user")
    return WorkerResult("did it")


def _steps(output: runtime.Output, root: Path) -> list[dict[str, Any]]:
    path = root / output.agent / output.run_id / runtime.PROGRESS
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_a_run_reports_each_step_as_it_goes(tmp_path: Path) -> None:
    out = runtime.run(
        "demo", root=tmp_path, agents=_agents(), asker=lambda s, u, a: "fine", worker=_worker
    )
    steps = _steps(out, tmp_path)
    kinds = [s["kind"] for s in steps]
    texts = [s["text"] for s in steps]
    assert kinds[0] == "start" and texts[0].startswith("Started Demo agent")
    assert "Reading the thing" in texts
    # A note appended anywhere becomes a step, without the worker knowing.
    assert "a note from deep inside a helper" in texts
    assert out.notes == ["a note from deep inside a helper"]
    assert kinds.count("model") == 2
    assert kinds[-1] == "end" and texts[-1] == "Finished: ok · did it"


def test_a_failed_run_ends_its_trail_with_the_failure(tmp_path: Path) -> None:
    def broken(ctx: Context) -> WorkerResult:
        ctx.step("About to fail")
        raise RuntimeError("boom")

    out = runtime.run("demo", root=tmp_path, agents=_agents(), worker=broken)
    last = _steps(out, tmp_path)[-1]
    assert last["kind"] == "end" and "failed" in last["text"] and "boom" in last["text"]


def test_activity_says_running_finished_or_stopped() -> None:
    root = home()
    # Finished: a real run of a real agent with a stub worker.
    runtime.run("data", worker=lambda ctx: WorkerResult("graded"))
    # Running: a run folder with steps and no output yet.
    now = datetime.now(UTC)
    live = root / "skeptic" / f"{now:%Y%m%dT%H%M%SZ}-aaaaaa"
    live.mkdir(parents=True)
    (live / runtime.PROGRESS).write_text(
        json.dumps({"at": now.isoformat(timespec="seconds"), "kind": "step", "text": "Attacking x"})
        + "\n"
    )
    # Stopped: no output and quiet for an hour.
    old = now - timedelta(hours=1)
    dead = root / "research" / f"{old:%Y%m%dT%H%M%SZ}-bbbbbb"
    dead.mkdir(parents=True)
    (dead / runtime.PROGRESS).write_text(
        json.dumps({"at": old.isoformat(timespec="seconds"), "kind": "step", "text": "Searching"})
        + "\n"
    )

    body = r.agents_activity()
    rows = {row["name"]: row for row in body["agents"]}
    assert rows["data"]["state"] == "ok" and rows["data"]["summary"] == "graded"
    assert rows["skeptic"]["state"] == "running" and rows["skeptic"]["now"] == "Attacking x"
    assert rows["research"]["state"] == "stopped"
    assert rows["knowledge"]["state"] == "idle" and rows["knowledge"]["steps"] == []
    assert body["running"] == 1
    # The feed is every agent's steps, newest first.
    ats = [step["at"] for step in body["feed"]]
    assert ats == sorted(ats, reverse=True)
    assert {step["agent"] for step in body["feed"]} >= {"data", "skeptic", "research"}


def test_make_agent_runs_an_agent_that_returns_items(monkeypatch: Any) -> None:
    """`python -m eulerlab.agents.runtime` crashed on any item (HISTORY #34)."""
    import runpy
    import sys
    import warnings

    import pytest

    monkeypatch.setattr(sys, "argv", ["runtime", "portfolio"])
    with pytest.raises(SystemExit) as done, warnings.catch_warnings():
        # runpy warns that the module is already imported; that is the point.
        warnings.simplefilter("ignore", RuntimeWarning)
        runpy.run_module("eulerlab.agents.runtime", run_name="__main__")
    assert done.value.code == 0
