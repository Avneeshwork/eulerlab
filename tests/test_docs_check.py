"""The docs gate, tested against throwaway git repositories.

Sprint 0's acceptance criteria require proving that a commit touching ``src/``
with no doc change actually fails. That proof lives here rather than in a
one-off manual run, so it keeps being true.
"""

from __future__ import annotations

import os
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
    # A pre-commit hook in a linked worktree runs with GIT_DIR (and
    # GIT_INDEX_FILE) set. Inherited, they point every `git` below at the real
    # repository: on 2026-10-16 `git init` here set core.bare and a "Test"
    # identity in the real config. The throwaway repo must be the only target.
    for name in [n for n in os.environ if n.startswith("GIT_")]:
        monkeypatch.delenv(name)
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


def test_staged_only_ignores_history(repo: Path) -> None:
    """The pre-commit hook must not be blocked by an earlier bad commit.

    Checking full history at commit time is circular: one undocumented commit
    would block every later commit, including the one adding the missing docs.
    """
    from tools.docs_check import check_staged

    _write(repo, "src/eulerlab/bad.py")
    _commit(repo, "feat: undocumented")  # a violation now in history

    _write(repo, "src/eulerlab/good.py")
    _write(repo, "docs/good.md")
    _git(repo, "add", "-A")

    assert collect_violations(repo)  # the branch is dirty...
    assert check_staged(repo) == []  # ...but this change is fine


def test_staged_only_still_catches_an_undocumented_change(repo: Path) -> None:
    from tools.docs_check import check_staged

    _write(repo, "src/eulerlab/thing.py")
    _git(repo, "add", "-A")

    assert len(check_staged(repo)) == 1


def test_an_unstaged_first_file_keeps_its_full_path(repo: Path) -> None:
    """`git status --porcelain` writes " M path" for unstaged changes.

    _git() used to .strip() the whole stdout, which ate the leading space on
    the first line only — so the first unstaged file lost a character from its
    path ("docs/x.md" -> "ocs/x.md") and stopped counting as documentation.
    Every later line was fine, which is exactly why it survived from Sprint 0
    until an audit found it.
    """
    from tools.docs_check import _worktree_files

    _write(repo, "docs/note.md", "hello\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "docs: note")

    # Modify it without staging -> porcelain emits " M docs/note.md"
    (repo / "docs" / "note.md").write_text("changed\n", encoding="utf-8")

    assert "docs/note.md" in _worktree_files(repo)


def test_an_unstaged_doc_change_satisfies_the_gate(repo: Path) -> None:
    """The bug's real consequence: a legitimate doc edit was not seen."""
    _write(repo, "src/eulerlab/thing.py")
    _write(repo, "docs/why.md")
    _git(repo, "add", "src/eulerlab/thing.py")  # code staged, doc left unstaged

    assert collect_violations(repo) == []
