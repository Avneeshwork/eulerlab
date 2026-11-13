"""Durable jobs (ADR-174): resume, budgets before a step, once-only steps, dead letters."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from eulerlab import jobrun

RULES = Path(__file__).parents[1] / "config" / "constitution.yaml"


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "constitution.yaml").write_text(RULES.read_text())
    (tmp_path / "config" / "llm.yaml").write_text(RULES.with_name("llm.yaml").read_text())
    monkeypatch.setenv("EULERLAB_DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "jobs"


def test_a_killed_job_resumes_without_repeating_finished_steps(root: Path) -> None:
    ran: list[str] = []

    def step(name: str, fail: bool = False) -> dict[str, str]:
        ran.append(name)
        if fail:
            raise KeyboardInterrupt  # the process is killed here
        return {"did": name}

    first = jobrun.open("night", "2026-11-13", root=root)
    first.do("a", lambda: step("a"))
    with pytest.raises(KeyboardInterrupt):
        first.do("b", lambda: step("b", fail=True))

    again = jobrun.open("night", "2026-11-13", root=root)
    assert again.id == first.id
    assert again.do("a", lambda: step("a")) == {"did": "a"}
    again.do("b", lambda: step("b"))
    again.finish("done")
    assert ran == ["a", "b", "b"]
    assert again.replayed == ["a"]
    assert jobrun.status("night", root)["finished"] is True
    # A finished job is not resumed: the same key starts run 2.
    assert jobrun.open("night", "2026-11-13", root=root).id.endswith(":2")


def test_a_step_over_the_weeks_ledger_cap_is_not_started(root: Path) -> None:
    ran: list[int] = []
    job = jobrun.open("night", "k", root=root, ledger_used=lambda: 9)
    with pytest.raises(jobrun.Refused, match="9 of 10"):
        job.do("gate", lambda: ran.append(1), cost=jobrun.Cost(ledger_entries=2))
    assert ran == []
    assert jobrun.status("night", root)["refused"] == ["gate"]


def test_a_step_over_the_months_ai_budget_is_not_started(root: Path) -> None:
    job = jobrun.open("night", "k", root=root, clock=lambda: datetime(2026, 11, 13, tzinfo=UTC))
    with pytest.raises(jobrun.Refused, match="AI budget"):
        job.do("big", lambda: 1, cost=jobrun.Cost(ai_inr=1001.0))
    assert job.do("small", lambda: 1, cost=jobrun.Cost(ai_inr=5.0)) == 1


def test_a_once_only_step_is_settled_by_looking_not_by_running_again(root: Path) -> None:
    spent: list[int] = []

    def gate() -> dict[str, int]:
        spent.append(2)
        raise KeyboardInterrupt  # dies after spending, before the result is kept

    first = jobrun.open("night", "k", root=root)
    with pytest.raises(KeyboardInterrupt):
        first.do("gate", gate, once=True)
    again = jobrun.open("night", "k", root=root)
    found = again.do("gate", gate, once=True, settle=lambda: {"entries": 2})
    assert found == {"entries": 2}
    assert spent == [2]


def test_a_once_only_step_with_no_way_to_check_goes_to_the_dead_letters(root: Path) -> None:
    def dies() -> None:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        jobrun.open("night", "k", root=root).do("pay", dies, once=True)
    with pytest.raises(jobrun.Unknown):
        jobrun.open("night", "k", root=root).do("pay", dies, once=True)
    assert [d["step"] for d in jobrun.dead_letters(root)] == ["pay"]


def test_retries_back_off_then_leave_a_dead_letter_that_can_be_settled(root: Path) -> None:
    waits: list[float] = []
    tries: list[int] = []

    def flaky() -> str:
        tries.append(1)
        if len(tries) < 3:
            raise OSError("feed down")
        return "ok"

    job = jobrun.open("feed", "k", root=root, sleep=waits.append)
    assert job.do("pull", flaky, retries=2) == "ok"
    assert waits == [2.0, 10.0]

    def broken() -> None:
        raise OSError("still down")

    with pytest.raises(OSError, match="still down"):
        job.do("push", broken, retries=1)
    (letter,) = jobrun.dead_letters(root)
    assert letter["step"] == "push" and "still down" in letter["error"]
    jobrun.settle_dead(jobrun.letter_key(letter), "re-ran the feed", root=root)
    assert jobrun.dead_letters(root) == []
