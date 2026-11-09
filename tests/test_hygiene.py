"""The hygiene gate (ADR-161): fails on new clutter, not on known debt."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tools import hook_witness, hygiene


def test_the_repo_has_no_clutter_beyond_the_baseline() -> None:
    assert hygiene.main([]) == 0


def test_two_functions_with_the_same_body_are_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = "".join(f"    x{i} = {i}\n" for i in range(8)) + "    return x0\n"
    pkg = tmp_path / "eulerlab"
    pkg.mkdir()
    (pkg / "a.py").write_text(f"def one():\n{body}")
    (pkg / "b.py").write_text(f"def two():\n{body}\ndef short():\n    return 1\n")
    monkeypatch.setattr(hygiene, "SRC", tmp_path)
    assert hygiene.check_duplicate_functions() == ["a.py::one = b.py::two"]


def test_a_shared_decision_number_is_reported(tmp_path: Path) -> None:
    for name in ("ADR-007-a.md", "ADR-007-b.md", "ADR-008-c.md"):
        (tmp_path / name).write_text("x")
    found = hygiene._number_collisions(tmp_path, r"(ADR-\d+)")
    assert found == ["ADR-007-a.md = ADR-007-b.md"]


def test_new_clutter_fails_and_known_clutter_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    found = {"dead-module": ["eulerlab.old", "eulerlab.new"]}
    monkeypatch.setattr(hygiene, "collect", lambda: found)
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"dead-module": ["eulerlab.old", "eulerlab.gone"]}))
    monkeypatch.setattr(hygiene, "BASELINE", baseline)
    assert hygiene.main([]) == 1
    out = capsys.readouterr().out
    assert "NEW dead-module: eulerlab.new" in out
    assert "CLEANED (delete from baseline) dead-module: eulerlab.gone" in out
    assert hygiene.main(["--report"]) == 0


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def test_a_commit_the_hooks_never_saw_is_logged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "t")
    monkeypatch.setattr(hook_witness, "REPO", tmp_path)
    log = tmp_path / "skipped.jsonl"
    monkeypatch.setattr(hook_witness, "LOG", log)

    (tmp_path / "f").write_text("1")
    _git(tmp_path, "add", "f")
    hook_witness.mark()  # the hooks approved this tree
    _git(tmp_path, "commit", "-q", "-m", "with hooks")
    hook_witness.check()
    assert not log.exists()

    (tmp_path / "f").write_text("2")
    _git(tmp_path, "commit", "-q", "-am", "skipped hooks")
    hook_witness.check()
    rows = [json.loads(x) for x in log.read_text().splitlines()]
    assert [r["subject"] for r in rows] == ["skipped hooks"]


def test_the_commit_hook_ignores_clutter_in_files_it_does_not_commit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    found = {
        "dead-module": ["eulerlab.mine", "eulerlab.theirs"],
        "test-only": ["eulerlab.untested_yet"],
    }
    monkeypatch.setattr(hygiene, "collect", lambda: found)
    monkeypatch.setattr(hygiene, "BASELINE", tmp_path / "none.json")
    monkeypatch.setattr(hygiene, "_staged", lambda: {"src/eulerlab/theirs_other.py"})
    assert hygiene.main(["--staged"]) == 0  # neither file is in this commit
    monkeypatch.setattr(hygiene, "_staged", lambda: {"src/eulerlab/mine.py"})
    assert hygiene.main(["--staged"]) == 1
    monkeypatch.setattr(hygiene, "collect", lambda: {"test-only": ["eulerlab.untested_yet"]})
    monkeypatch.setattr(hygiene, "_staged", lambda: {"src/eulerlab/untested_yet.py"})
    assert hygiene.main(["--staged"]) == 0  # a warning, not a failure
