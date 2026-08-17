"""The docs gate, tested against throwaway git repositories.

Sprint 0's acceptance criteria require proving that a commit touching ``src/``
with no doc change actually fails. That proof lives here rather than in a
one-off manual run, so it keeps being true.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from tools.docs_check import check_change, collect_violations


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _write(repo: Path, relpath: str, text: str = "x\n") -> None:
    path = repo / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.delenv("DOCS_CHECK_BASE", raising=False)
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")
    _write(root, "README.md", "# test\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "chore: init")
    yield root


def _commit(repo: Path, message: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)


def test_code_without_docs_fails(repo: Path) -> None:
    _write(repo, "src/eulerlab/thing.py")
    _commit(repo, "feat: add thing")

    violations = collect_violations(repo)

    assert len(violations) == 1
    assert violations[0].files == ["src/eulerlab/thing.py"]


def test_code_with_docs_passes(repo: Path) -> None:
    _write(repo, "src/eulerlab/thing.py")
    _write(repo, "docs/DECISIONS/ADR-009-thing.md")
    _commit(repo, "feat: add thing")

    assert collect_violations(repo) == []


def test_root_markdown_counts_as_docs(repo: Path) -> None:
    _write(repo, "src/eulerlab/thing.py")
    _write(repo, "STATE.md", "**Sprint:** 1\n")
    _commit(repo, "feat: add thing")

    assert collect_violations(repo) == []


def test_skip_token_is_honoured(repo: Path) -> None:
    _write(repo, "src/eulerlab/thing.py")
    _commit(repo, "refactor: rename internals [skip docs]")

    assert collect_violations(repo) == []


def test_docs_only_change_passes(repo: Path) -> None:
    _write(repo, "docs/notes.md")
    _commit(repo, "docs: notes")

    assert collect_violations(repo) == []


def test_uncommitted_code_is_caught(repo: Path) -> None:
    _write(repo, "src/eulerlab/thing.py")

    violations = collect_violations(repo)

    assert len(violations) == 1
    assert "working tree" in violations[0].what


# --- the rule as a pure function, without git in the way ---


def test_check_change_ignores_non_code() -> None:
    assert check_change("x", ["tests/test_a.py", "Makefile"]) is None


def test_check_change_flags_nested_source_paths() -> None:
    violation = check_change("x", ["src/eulerlab/a/b/c.py"])
    assert violation is not None
    assert violation.files == ["src/eulerlab/a/b/c.py"]


def test_nested_markdown_outside_docs_is_not_a_doc() -> None:
    # src/eulerlab/NOTES.md must not let a code change through.
    assert check_change("x", ["src/eulerlab/a.py", "src/eulerlab/NOTES.md"]) is not None
