"""Protected files need an Operator-Ack trailer; a halt is loud until lifted (ADR-217, #160)."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from eulerlab import operator_ack
from eulerlab.agents import guardian
from eulerlab.agents.runtime import Output

ACK = "Operator-Ack: path refactor approved by the operator"
GATES = "src/eulerlab/gates.py"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    ).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "src/eulerlab").mkdir(parents=True)
    (repo / "mandate.yaml").write_text("a: 1\n", encoding="utf-8")
    (repo / GATES).write_text("x = 1\n", encoding="utf-8")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "t")
    _git(repo, "config", "commit.gpgsign", "false")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


def _commit(repo: Path, message: str) -> None:
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", message)


def _out() -> Output:
    now = datetime(2026, 11, 16, 4, 0, tzinfo=UTC).isoformat()
    return Output(agent="tester", run_id="r", started=now, finished=now, status="ok", summary="s")


# --- the commit-msg hook ------------------------------------------------------------------


def test_a_commit_to_gates_without_the_trailer_is_refused(repo: Path) -> None:
    protected = operator_ack.protected_paths()
    why = operator_ack.check_message("fix: path\n\nbody\n", [GATES, "README.md"], protected, repo)
    assert "refused" in why and GATES in why and "Operator-Ack" in why


def test_a_commit_with_the_trailer_passes(repo: Path) -> None:
    protected = operator_ack.protected_paths()
    message = f"fix: path\n\nbody\n\n{ACK}\nCo-Authored-By: C <c@example.invalid>\n"
    assert operator_ack.check_message(message, [GATES], protected, repo) == ""


def test_other_files_need_no_trailer_and_a_short_reason_is_not_one(repo: Path) -> None:
    protected = operator_ack.protected_paths()
    assert operator_ack.check_message("feat: x\n", ["src/eulerlab/x.py"], protected, repo) == ""
    weak = "fix: x\n\nOperator-Ack: ok\n"
    assert operator_ack.check_message(weak, ["mandate.yaml"], protected, repo)
    # a trailer-like line in the body, not the trailer block, does not count
    buried = f"fix: x\n\n{ACK}\n\nmore words after it.\n"
    assert operator_ack.check_message(buried, ["mandate.yaml"], protected, repo)


def test_the_hook_reads_the_staged_files_and_the_message_file(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (repo / GATES).write_text("x = 2\n", encoding="utf-8")
    _git(repo, "add", GATES)
    monkeypatch.chdir(repo)
    bare = repo / "msg_bare"
    bare.write_text("fix: path\n# Please enter the commit message\n", encoding="utf-8")
    acked = repo / "msg_acked"
    acked.write_text(f"fix: path\n\n{ACK}\n# comment\n", encoding="utf-8")
    assert operator_ack.main(["check-msg", str(bare)]) == 1
    assert operator_ack.main(["check-msg", str(acked)]) == 0


def test_the_hook_is_wired_at_commit_msg() -> None:
    import yaml

    config = yaml.safe_load(Path(".pre-commit-config.yaml").read_text(encoding="utf-8"))
    hooks = {h["id"]: h for r in config["repos"] for h in r["hooks"]}
    assert hooks["operator-ack"]["stages"] == ["commit-msg"]
    assert "eulerlab.operator_ack check-msg" in hooks["operator-ack"]["entry"]


# --- the guardian accepts an acked commit ----------------------------------------------


def test_an_acked_commit_is_logged_and_does_not_halt(repo: Path, tmp_path: Path) -> None:
    root = tmp_path / "agents"
    told: list[str] = []
    assert guardian.after_run(_out(), root, repo=repo, tell=told.append) == []  # baseline
    (repo / GATES).write_text("x = 2\n", encoding="utf-8")
    _commit(repo, f"refactor: gates path\n\n{ACK}\n")
    assert guardian.after_run(_out(), root, repo=repo, tell=told.append) == []
    assert not guardian.halted(root) and told == []
    logged = guardian.trips(root)
    assert [t.rule for t in logged] == ["acked_change"]
    assert GATES in logged[0].why and "path refactor approved" in logged[0].why
    # accepted once: the next run finds nothing to log
    assert guardian.after_run(_out(), root, repo=repo, tell=told.append) == []
    assert len(guardian.trips(root)) == 1


def test_an_unacked_commit_halts(repo: Path, tmp_path: Path) -> None:
    root = tmp_path / "agents"
    guardian.after_run(_out(), root, repo=repo, tell=lambda _t: None)
    (repo / GATES).write_text("x = 2\n", encoding="utf-8")
    _commit(repo, "refactor: gates path")
    acted = guardian.after_run(_out(), root, repo=repo, tell=lambda _t: None)
    assert [t.rule for t in acted] == ["protected_changed"] and guardian.halted(root)


def test_an_edit_after_the_acked_commit_still_halts(repo: Path, tmp_path: Path) -> None:
    root = tmp_path / "agents"
    guardian.after_run(_out(), root, repo=repo, tell=lambda _t: None)
    (repo / GATES).write_text("x = 2\n", encoding="utf-8")
    _commit(repo, f"refactor: gates path\n\n{ACK}\n")
    (repo / GATES).write_text("x = 3\n", encoding="utf-8")  # not what the ack covered
    acted = guardian.after_run(_out(), root, repo=repo, tell=lambda _t: None)
    assert [t.rule for t in acted] == ["protected_changed"]


# --- halt escalation ----------------------------------------------------------------------


def test_a_simulated_halt_sends_three_lines(tmp_path: Path) -> None:
    root = tmp_path / "agents"
    root.mkdir()
    told: list[str] = []
    stamped = guardian.act(
        guardian.Trip("protected_changed", "all", "halt", "gates.py changed"),
        root,
        tell=told.append,
    )
    start = datetime.fromisoformat(stamped.at)
    assert len(told) == 1 and "halt" in told[0]
    assert guardian.escalate(root, start + timedelta(hours=1), tell=told.append) == []
    assert (
        len(guardian.escalate(root, start + timedelta(hours=2, minutes=5), tell=told.append)) == 1
    )
    assert guardian.escalate(root, start + timedelta(hours=3), tell=told.append) == []
    assert (
        len(guardian.escalate(root, start + timedelta(hours=8, minutes=1), tell=told.append)) == 1
    )
    assert guardian.escalate(root, start + timedelta(hours=30), tell=told.append) == []
    assert len(told) == 3
    assert "after 2 h" in told[1] and "after 8 h" in told[2] and "agents-resume" in told[2]
    guardian.clear("understood, resuming", root, tmp_path)
    assert guardian.halt_state(root) == {}
    assert guardian.escalate(root, start + timedelta(hours=40), tell=told.append) == []


def test_a_hand_written_halt_is_told_once_then_escalated(tmp_path: Path) -> None:
    root = tmp_path / "agents"
    root.mkdir()
    (root / guardian.HALT_FILE).write_text("manual: stop everything\n", encoding="utf-8")
    told: list[str] = []
    since = datetime.fromisoformat(guardian.halt_state(root)["since"])
    guardian.escalate(root, since + timedelta(minutes=5), tell=told.append)
    assert len(told) == 1 and "manual" in told[0]
    # a job that missed the 2 h line sends one line at 9 h, not two
    guardian.escalate(root, since + timedelta(hours=9), tell=told.append)
    assert len(told) == 2 and guardian.halt_state(root)["sent"] == [0, 2, 8]


def test_the_halt_watch_job_runs_every_hour() -> None:
    from eulerlab.jobs import JOBS

    job = JOBS["halt-watch"]
    assert job.hours == tuple(range(24)) and "agents-halt-watch" in job.command
    assert "agents-halt-watch:" in Path("Makefile").read_text(encoding="utf-8")
