"""The doctor: finds known trouble after a run and takes only a listed remedy (ADR-113)."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from eulerlab.agents import doctor, runtime
from eulerlab.agents.runtime import Context, WorkerResult
from eulerlab.agents.spec import AgentSpec, Effective, effective

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)

TRACE = """Traceback (most recent call last):
  File "/Users/a/eulerlab/src/eulerlab/agents/runtime.py", line 326, in run
    result = run_worker(ctx)
  File "/Users/a/eulerlab/src/eulerlab/agents/workers/lab.py", line 210, in run
    cards = plan(ctx)
  File "/Users/a/eulerlab/.venv/lib/python3.12/site-packages/polars/frame.py", line 90, in x
    raise KeyError
KeyError: 'turnover'
"""


class _Out:
    def __init__(self, **kw: Any) -> None:
        self.agent = kw.get("agent", "lab")
        self.run_id = kw.get("run_id", "20261101T120000Z-abcdef")
        self.status = kw.get("status", "ok")
        self.summary = kw.get("summary", "")
        self.notes = kw.get("notes", [])
        self.data = kw.get("data", {})


def test_the_suspect_file_is_the_deepest_frame_inside_the_project() -> None:
    assert doctor.suspect_file(TRACE) == ("src/eulerlab/agents/workers/lab.py", 210)
    assert doctor.suspect_file("no traceback here") == ("", 0)


def test_a_crash_becomes_a_code_problem_for_engineering() -> None:
    found = doctor.examine(_Out(status="failed", summary="KeyError: 'turnover'", notes=[TRACE]))
    assert [p.kind for p in found] == ["code_error"]
    assert found[0].file == "src/eulerlab/agents/workers/lab.py" and found[0].line == 210


def test_a_spent_quota_or_missing_key_is_model_down_not_a_code_error() -> None:
    # HISTORY #64: a Groq rate limit was queued for the engineering agent as a bug.
    for summary in (
        "ModelUnavailable: The free quota is used up for the moment. Try again in a minute.",
        "Refused: No GROQ_API_KEY in .env.",
    ):
        found = doctor.examine(_Out(status="failed", summary=summary, notes=[TRACE, "Refused"]))
        assert [p.kind for p in found] == ["model_down"], summary


def test_too_good_results_are_flagged_and_a_refusal_for_data_goes_to_the_data_agent() -> None:
    lab = _Out(
        data={
            "results": [
                {
                    "card": "low-vol",
                    "screens": [{"feature": "x", "t_stat": 14.0}],
                    "backtests": [{"label": "top30", "robust_sharpe": 5.6}],
                }
            ]
        }
    )
    assert [p.kind for p in doctor.examine(lab)] == ["suspicious", "suspicious"]
    refused = _Out(status="refused", summary="data grade C: not enough history")
    assert [p.kind for p in doctor.examine(refused)] == ["data_refused"]
    assert doctor.examine(_Out()) == []


def test_every_remedy_comes_from_the_fixed_list(tmp_path: Path) -> None:
    problems = [
        doctor.Problem("suspicious", "lab", "r", "x"),
        doctor.Problem("code_error", "lab", "r", "y", file="src/eulerlab/a.py"),
    ]
    doctor.treat(problems, tmp_path)
    assert [p.remedy for p in problems] == ["flagged", "queued_for_engineering"]
    log = (tmp_path / "doctor" / "log.jsonl").read_text().splitlines()
    assert len(log) == 2
    assert [p.file for p in doctor.queued(tmp_path)] == ["src/eulerlab/a.py"]


def _old(path: Path, hours: float) -> None:
    stamp = (NOW - timedelta(hours=hours)).timestamp()
    os.utime(path, (stamp, stamp))


def test_a_dead_run_is_closed_and_live_runs_and_other_folders_are_left(tmp_path: Path) -> None:
    dead = tmp_path / "lab" / "20261101T050000Z-aaaaaa"
    live = tmp_path / "lab" / "20261101T113000Z-bbbbbb"
    other = tmp_path / "engineering" / "worktrees"
    for folder in (dead, live, other):
        folder.mkdir(parents=True)
        (folder / "progress.jsonl").write_text("{}\n")
    _old(dead / "progress.jsonl", 5)
    _old(live / "progress.jsonl", 0.5)
    _old(other / "progress.jsonl", 9)
    found = doctor.after_run(_Out(), tmp_path, NOW)
    assert [(p.kind, p.run) for p in found] == [("stalled", dead.name)]
    closed = json.loads((dead / "output.json").read_text())
    assert closed["status"] == "failed" and closed["data"] == {"closed_by": "doctor"}
    assert not (live / "output.json").exists() and not (other / "output.json").exists()


def test_the_queue_keeps_one_problem_per_file_and_done_takes_it_off(tmp_path: Path) -> None:
    a = doctor.Problem("code_error", "lab", "r1", "x", file="src/eulerlab/a.py")
    a2 = doctor.Problem("code_error", "lab", "r2", "x again", file="src/eulerlab/a.py")
    b = doctor.Problem("code_error", "data", "r3", "y", file="src/eulerlab/b.py")
    doctor.treat([a, a2, b], tmp_path)
    assert [(p.file, p.run) for p in doctor.queued(tmp_path)] == [
        ("src/eulerlab/a.py", "r1"),
        ("src/eulerlab/b.py", "r3"),
    ]
    doctor.done("src/eulerlab/a.py", "branch pushed", tmp_path)
    assert [p.file for p in doctor.queued(tmp_path)] == ["src/eulerlab/b.py"]


def test_the_doctor_never_breaks_the_run_it_inspects(tmp_path: Path) -> None:
    assert doctor.after_run(object(), tmp_path, NOW) == []


def _agents() -> dict[str, Effective]:
    spec = AgentSpec(
        name="demo",
        title="Demo agent",
        job="does one small thing for a test",
        worker="eulerlab.agents.workers.data",
    )
    return {"demo": effective(spec, None)}


def test_a_crashing_agent_reaches_the_engineering_queue(tmp_path: Path) -> None:
    def worker(ctx: Context) -> WorkerResult:
        raise KeyError("turnover")

    runtime.run("demo", root=tmp_path, agents=_agents(), worker=worker)
    queue = doctor.queued(tmp_path)
    # The worker lives in this test file, so the deepest project frame is the runtime's.
    assert [(p.file, p.agent) for p in queue] == [("src/eulerlab/agents/runtime.py", "demo")]
