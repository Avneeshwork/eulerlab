"""`make health` reads what the scheduler, the live book and the kill switch leave behind."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from eulerlab import health, paths
from eulerlab.scheduler import IST


@pytest.fixture
def data_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv(paths.ENV_VAR, str(tmp_path))
    return tmp_path


def at(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=IST)


def test_no_scheduler_heartbeat_is_red(data_dir: Path) -> None:
    body = health.summary(at("2026-11-12T12:00"))
    assert not body["ok"]
    assert body["red"] == ["scheduler"]
    assert body["scheduler"]["why"] == "no heartbeat"
    assert body["kill_switch"]["status"] == "ok"
    assert "RED" in health.render(body)


def test_a_fresh_heartbeat_and_clean_runs_are_green(data_dir: Path) -> None:
    sched = data_dir / "scheduler"
    sched.mkdir()
    (sched / "heartbeat.json").write_text(
        json.dumps({"at": "2026-11-12T12:00:00+05:30", "running": []})
    )
    (sched / "state.json").write_text(
        json.dumps(
            {
                "depth": {"slot": "2026-11-12T09:10+05:30", "code": 0},
                "agents-preopen": {"slot": "2026-11-12T08:45+05:30", "code": 0},
                "live-shadow-open": {"slot": "2026-11-12T09:16+05:30", "code": 0},
                "data-watch": {"slot": "2026-11-12T10:00+05:30", "code": 0},
            }
        )
    )
    body = health.summary(at("2026-11-12T10:05"))
    jobs = {row["job"]: row for row in body["jobs"]}
    assert body["ok"], body["red"]
    assert jobs["depth"]["status"] == "ok"
    assert jobs["daily"]["why"] == "no run recorded yet"


def test_a_failed_or_missed_job_is_red(data_dir: Path) -> None:
    sched = data_dir / "scheduler"
    sched.mkdir()
    (sched / "heartbeat.json").write_text(
        json.dumps({"at": "2026-11-12T14:00:00+05:30", "running": []})
    )
    (sched / "state.json").write_text(
        json.dumps(
            {
                "depth": {"slot": "2026-11-12T09:10+05:30", "code": 2},
                "agents-preopen": {"slot": "2026-11-11T08:45+05:30", "code": 0},
            }
        )
    )
    body = health.summary(at("2026-11-12T14:00"))
    jobs = {row["job"]: row for row in body["jobs"]}
    assert jobs["depth"]["status"] == "bad" and "exit 2" in jobs["depth"]["why"]
    # 08:45 agents-preopen never ran and its three-hour grace has passed.
    assert (
        jobs["agents-preopen"]["status"] == "bad" and "never ran" in jobs["agents-preopen"]["why"]
    )
    assert "job depth" in body["red"] and "job agents-preopen" in body["red"]


def test_a_tripped_switch_is_red(data_dir: Path) -> None:
    (data_dir / "oms").mkdir()
    (data_dir / "oms" / "KILL_SWITCH").write_text(json.dumps({"reason": "drill", "by": "test"}))
    body = health.summary(at("2026-11-12T12:00"))
    assert "kill_switch" in body["red"]
    assert body["kill_switch"]["status"] == "bad"


# --- the halt and liveness lines (ADR-217) ----------------------------------------------


@pytest.fixture
def no_db(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EULERLAB_DATABASE_URL", raising=False)


def _run(data_dir: Path, agent: str, started: str, status: str = "ok") -> None:
    from eulerlab.agents.runtime import Output

    out = Output(
        agent=agent, run_id=started, started=started, finished=started, status=status, summary="s"
    )
    folder = data_dir / "agents" / agent / started.replace(":", "")
    folder.mkdir(parents=True)
    (folder / "output.json").write_text(out.model_dump_json())


def _experiment(asked_by: str, now: datetime) -> None:
    from datetime import date

    from eulerlab.research import experiments

    experiments.record(
        purpose="screen",
        fingerprint=f"f-{asked_by}-{now.isoformat()}",
        first=date(2020, 1, 1),
        end=date(2020, 6, 1),
        metrics={"count": 1},
        asked_by=asked_by,
        now=now,
    )


def test_a_halt_is_red_with_its_age(data_dir: Path) -> None:
    (data_dir / "agents").mkdir()
    (data_dir / "agents" / "HALT").write_text("protected_changed: gates.py\n")
    body = health.summary(at("2026-11-12T12:00"))
    assert "agents_halt" in body["red"]
    assert "gates.py" in body["agents_halt"]["why"]
    assert "agents_halt" in health.render(body)


def test_nothing_ever_run_is_not_red_yet(data_dir: Path, no_db: None) -> None:
    body = health.summary(at("2026-11-12T22:00"))
    assert body["agents_halt"]["status"] == "ok"
    assert body["autopilot_rows"]["why"] == "no run recorded yet"
    assert body["experiments_today"]["status"] == "ok"
    assert all(row["status"] == "ok" for row in body["agent_runs"])


def test_an_agent_past_its_deadline_is_red(data_dir: Path, no_db: None) -> None:
    # research has 26 h in the watchdog's `expect`; a failed run does not count
    _run(data_dir, "research", "2026-11-10T11:30:00+00:00")
    _run(data_dir, "research", "2026-11-12T01:00:00+00:00", status="failed")
    _run(data_dir, "lab", "2026-11-12T03:00:00+00:00")
    body = health.summary(at("2026-11-12T12:00"))
    rows = {row["agent"]: row for row in body["agent_runs"]}
    assert rows["research"]["status"] == "bad"
    assert "last ok 2026-11-10T11:30" in rows["research"]["why"]
    assert rows["lab"]["status"] == "ok"
    assert "agent research" in body["red"] and "agent lab" not in body["red"]
    assert "agent research" in health.render(body)


def test_autopilot_rows_and_todays_experiments(data_dir: Path, no_db: None) -> None:
    _run(data_dir, "autopilot", "2026-11-10T11:30:00+00:00")
    _experiment("autopilot", at("2026-11-10T17:20"))
    late = health.summary(at("2026-11-12T21:30"))
    assert late["autopilot_rows"]["status"] == "bad"
    assert late["experiments_today"]["status"] == "bad"
    assert {"autopilot_rows", "experiments_today"} <= set(late["red"])
    # before 21:00 IST today's rows are not due yet
    assert health.summary(at("2026-11-12T15:00"))["experiments_today"]["status"] == "ok"
    _experiment("autopilot", at("2026-11-12T17:20"))
    _experiment("operator", at("2026-11-12T18:00"))
    fresh = health.summary(at("2026-11-12T21:30"))
    assert fresh["autopilot_rows"]["status"] == "ok"
    assert "1 rows in 26 h" in fresh["autopilot_rows"]["why"]
    assert fresh["experiments_today"]["why"] == "2 rows today"


def test_an_autopilot_that_ran_but_wrote_nothing_is_red(data_dir: Path, no_db: None) -> None:
    _run(data_dir, "autopilot", "2026-11-12T11:30:00+00:00")
    body = health.summary(at("2026-11-12T18:00"))
    assert body["autopilot_rows"]["status"] == "bad"
    assert "none ever" in body["autopilot_rows"]["why"]
