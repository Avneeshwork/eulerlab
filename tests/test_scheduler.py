"""The scheduler runs the job table on a server the way launchd ran it on the Mac (ADR-164)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from eulerlab import paths, scheduler
from eulerlab.jobs import JOBS, SUNDAY, WEEKDAYS, Job
from eulerlab.scheduler import IST, Due, Scheduler, due, next_slot, slots


def at(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=IST)


def job(name: str = "j", *, hour: int = 10, minute: int = 0, **kw: Any) -> Job:
    base: dict[str, Any] = {
        "name": name,
        "label": f"com.test.{name}",
        "command": "true",
        "hour": hour,
        "minute": minute,
        "weekdays": (),
        "log": name,
        "what": f"{name}, every day",
        "why_then": "a test",
    }
    base.update(kw)
    return Job(**base)


@pytest.fixture
def data_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv(paths.ENV_VAR, str(tmp_path))
    return tmp_path


# --- slots ------------------------------------------------------------------------------------


def test_a_weekday_job_has_no_slot_on_saturday() -> None:
    weekday = job(weekdays=WEEKDAYS)
    assert slots(weekday, at("2026-11-14T00:00")) == []  # Saturday
    assert slots(weekday, at("2026-11-13T12:00")) == [at("2026-11-13T10:00")]  # Friday


def test_an_hours_job_has_one_slot_per_hour() -> None:
    watch = job(hours=(6, 8, 22), minute=5)
    assert slots(watch, at("2026-11-15T01:00")) == [
        at("2026-11-15T06:05"),
        at("2026-11-15T08:05"),
        at("2026-11-15T22:05"),
    ]


def test_next_slot_crosses_the_week() -> None:
    sunday = job(weekdays=(SUNDAY,), hour=7)
    assert next_slot(sunday, at("2026-11-12T08:00")) == at("2026-11-15T07:00")
    assert next_slot(sunday, at("2026-11-15T07:00")) == at("2026-11-22T07:00")


def test_the_real_table_has_a_next_slot_for_every_job() -> None:
    now = at("2026-11-12T18:00")
    for j in JOBS.values():
        assert next_slot(j, now) > now


# --- due --------------------------------------------------------------------------------------


def test_a_slot_just_passed_is_due_once() -> None:
    j = job(hour=19, minute=30)
    found = due([j], at("2026-11-12T19:30:20"), {})
    assert [d.slot for d in found] == [at("2026-11-12T19:30")]
    assert found[0].skipped == ()
    state = {"j": {"slot": found[0].slot.isoformat(timespec="minutes")}}
    assert due([j], at("2026-11-12T19:31"), state) == []


def test_a_missed_catch_up_slot_runs_late_within_grace() -> None:
    j = job(hour=19, minute=30)
    found = due([j], at("2026-11-12T21:00"), {})
    assert found and found[0].slot == at("2026-11-12T19:30")
    assert found[0].late == timedelta(hours=1, minutes=30)
    # Beyond grace: the slot is reported as missed, not run. A first start, with
    # no state, says nothing about slots it was never meant to run.
    ran_yesterday = {"j": {"slot": "2026-11-11T19:30+05:30"}}
    assert due([j], at("2026-11-13T01:00"), ran_yesterday) == [
        Due(j, at("2026-11-12T19:30"), timedelta(hours=5, minutes=30), (at("2026-11-12T19:30"),))
    ]
    assert due([j], at("2026-11-13T01:00"), {}) == []


def test_two_missed_hourly_slots_run_the_latest_and_skip_the_rest() -> None:
    watch = job(hours=(6, 8, 10), minute=0)
    found = due([watch], at("2026-11-12T10:30"), {"j": {"slot": "2026-11-12T06:00+05:30"}})
    assert len(found) == 1
    assert found[0].slot == at("2026-11-12T10:00")
    assert found[0].skipped == (at("2026-11-12T08:00"),)


def test_a_clock_tied_job_is_skipped_when_late() -> None:
    sweep = job(hour=9, minute=16, catch_up=False)
    found = due([sweep], at("2026-11-12T09:20"), {})
    assert found[0].skipped == ()
    found = due([sweep], at("2026-11-12T09:40"), {"j": {"slot": "2026-11-11T09:16+05:30"}})
    assert found[0].skipped == (at("2026-11-12T09:16"),)


def test_a_running_job_is_not_started_again() -> None:
    j = job(hour=19, minute=30)
    assert due([j], at("2026-11-12T19:31"), {}, running=["j"]) == []


# --- the scheduler ----------------------------------------------------------------------------


def _recording(runs: list[str]) -> Any:
    def runner(j: Job, repo: Path) -> int:
        runs.append(j.name)
        return 0

    return runner


def test_a_look_runs_what_is_due_and_records_it(data_dir: Path) -> None:
    runs: list[str] = []
    told: list[dict[str, Any]] = []

    def runner(j: Job, repo: Path) -> int:
        runs.append(j.name)
        return 3 if j.name == "bad" else 0

    jobs = {"good": job("good", hour=19, minute=30), "bad": job("bad", hour=19, minute=30)}
    clock = lambda: at("2026-11-12T19:30:10")  # noqa: E731
    sched = Scheduler(
        jobs, repo=data_dir, runner=runner, clock=clock, notifier=lambda *a, **k: told.append(k)
    )
    found = sched.look()
    sched.wait()
    assert {d.job.name for d in found} == {"good", "bad"}
    assert sorted(runs) == ["bad", "good"]
    state = json.loads((data_dir / "scheduler" / "state.json").read_text())
    assert state["good"]["code"] == 0 and state["bad"]["code"] == 3
    assert state["good"]["slot"] == "2026-11-12T19:30+05:30"
    lines = [
        json.loads(ln) for ln in (data_dir / "scheduler" / "runs.jsonl").read_text().splitlines()
    ]
    assert {ln["job"]: ln["code"] for ln in lines} == {"good": 0, "bad": 3}
    assert told == [{"code": 3, "log": None}]
    beat = json.loads((data_dir / "scheduler" / "heartbeat.json").read_text())
    assert beat["at"] == "2026-11-12T19:30:10+05:30"
    # The same minute again: nothing fires twice.
    assert sched.look() == []
    assert runs.count("good") == 1


def test_a_restart_does_not_rerun_a_slot_already_run(data_dir: Path) -> None:
    runs: list[str] = []
    jobs = {"j": job(hour=19, minute=30)}
    first = Scheduler(
        jobs,
        repo=data_dir,
        runner=_recording(runs),
        clock=lambda: at("2026-11-12T19:30:05"),
    )
    first.look()
    first.wait()
    second = Scheduler(
        jobs,
        repo=data_dir,
        runner=_recording(runs),
        clock=lambda: at("2026-11-12T19:45"),
    )
    assert second.look() == []
    assert runs == ["j"]


def test_a_skipped_clock_tied_slot_is_logged_not_run(data_dir: Path) -> None:
    runs: list[str] = []
    jobs = {"j": job(hour=9, minute=16, catch_up=False)}
    (data_dir / "scheduler").mkdir()
    (data_dir / "scheduler" / "state.json").write_text('{"j": {"slot": "2026-11-11T09:16+05:30"}}')
    sched = Scheduler(
        jobs,
        repo=data_dir,
        runner=_recording(runs),
        clock=lambda: at("2026-11-12T11:00"),
    )
    sched.look()
    sched.wait()
    assert runs == []
    line = json.loads((data_dir / "scheduler" / "runs.jsonl").read_text().splitlines()[0])
    assert line["skipped"] is True and line["job"] == "j"


def test_run_once_runs_the_real_command_in_a_shell(data_dir: Path) -> None:
    jobs = {"echo": job("echo", command="echo hello from {repo} && exit 0")}
    sched = Scheduler(jobs, repo=data_dir, clock=lambda: at("2026-11-12T12:00"))
    assert sched.run_once("echo") == 0
    assert "hello from" in (data_dir / "logs" / "echo.log").read_text()


def test_listing_names_every_job() -> None:
    text = scheduler.listing(JOBS, at("2026-11-12T18:00"))
    for name in JOBS:
        assert name in text
