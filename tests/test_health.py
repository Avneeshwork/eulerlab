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
