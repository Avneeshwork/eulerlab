"""Fail when code changes without documentation changes.

The rule, in one sentence: **any change that touches ``src/`` must also touch
``docs/`` or a top-level Markdown file.**

This is checked for every commit in ``BASE..HEAD`` and, separately, for the
current uncommitted working tree. It is deliberately dumb — it cannot tell good
documentation from bad. What it prevents is the specific failure mode where six
sprints of code accumulate and nobody can say why any of it is the way it is.

Two modes. ``--staged-only`` checks just the change being committed, which is
what the pre-commit hook wants. The default walks the whole branch, which is
what ``make verify`` and CI want.

BASE is, in order of preference:
  1. ``$DOCS_CHECK_BASE`` (CI sets this to the PR base SHA)
  2. the merge-base with ``main``, when on a branch other than ``main``
  3. ``HEAD~1``

Escape hatch: put ``[skip docs]`` in a commit message. Use it for pure
refactors with no behaviour change, and expect to justify it in the review.

Every function takes the repository root as an argument so this can be tested
against a throwaway repo rather than only against itself.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

CODE_PREFIX = "src/"
DOC_PREFIX = "docs/"
SKIP_TOKEN = "[skip docs]"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    # rstrip only. `git status --porcelain` encodes an unstaged change as
    # " M path" with a leading space, and a full .strip() eats that space on
    # the FIRST line only - so the first unstaged file silently lost a
    # character from its path ("docs/x.md" -> "ocs/x.md") and stopped being
    # recognised as documentation. Every other line was unaffected, which is
    # why it went unnoticed from Sprint 0 until an audit on 2026-08-18.
    return result.stdout.rstrip("\n")


def _ref_exists(repo: Path, ref: str) -> bool:
    try:
        _git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    except subprocess.CalledProcessError:
        return False
    return True


def _is_doc(path: str) -> bool:
    """Docs are anything under docs/, or a Markdown file at the repo root."""
    return path.startswith(DOC_PREFIX) or (path.endswith(".md") and "/" not in path)


def _base_ref(repo: Path) -> str | None:
    env_base = os.environ.get("DOCS_CHECK_BASE", "").strip()
    if env_base and _ref_exists(repo, env_base):
        return env_base

    branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    if branch != "main" and _ref_exists(repo, "main"):
        return _git(repo, "merge-base", "main", "HEAD")

    if _ref_exists(repo, "HEAD~1"):
        return "HEAD~1"
    return None


@dataclass(frozen=True)
class Violation:
    what: str
    files: list[str]

    def render(self) -> str:
        shown = ", ".join(self.files[:4])
        more = f" (+{len(self.files) - 4} more)" if len(self.files) > 4 else ""
        return (
            f"  {self.what}\n    touched: {shown}{more}\n    no change under docs/ or a root *.md"
        )


def check_change(what: str, files: list[str], message: str = "") -> Violation | None:
    """The whole rule, as a pure function. Returns None when the change is fine."""
    code = sorted(f for f in files if f.startswith(CODE_PREFIX))
    if not code:
        return None
    if SKIP_TOKEN in message:
        return None
    if any(_is_doc(f) for f in files):
        return None
    return Violation(what=what, files=code)


def _commit_files(repo: Path, sha: str) -> list[str]:
    out = _git(repo, "show", "--name-only", "--pretty=format:", sha)
    return [line for line in out.splitlines() if line]


def _staged_files(repo: Path) -> list[str]:
    out = _git(repo, "diff", "--cached", "--name-only")
    return [line for line in out.splitlines() if line]


def check_staged(repo: Path = REPO_ROOT) -> list[Violation]:
    """Check only what is about to be committed.

    This is the pre-commit hook's entry point, and it deliberately ignores
    history. The full-range check cannot be used at commit time: it inspects
    commits already made, so a single earlier violation would block every
    subsequent commit including the one fixing it. Ask "is *this* change
    documented" here, and "is the branch clean" in `make verify` and CI.
    """
    violation = check_change("staged changes", _staged_files(repo))
    return [violation] if violation else []


def _worktree_files(repo: Path) -> list[str]:
    out = _git(repo, "status", "--porcelain")
    files: list[str] = []
    for line in out.splitlines():
        if not line:
            continue
        path = line[3:]
        # Renames are reported as "old -> new"; the new path is what matters.
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        files.append(path.strip('"'))
    return files


def collect_violations(repo: Path = REPO_ROOT) -> list[Violation]:
    violations: list[Violation] = []

    base = _base_ref(repo)
    rev_range = f"{base}..HEAD" if base else "HEAD"
    for sha in _git(repo, "rev-list", rev_range).splitlines():
        if not sha:
            continue
        message = _git(repo, "log", "-1", "--format=%s%n%b", sha)
        short = _git(repo, "log", "-1", "--format=%h %s", sha)
        violation = check_change(f"commit {short}", _commit_files(repo, sha), message)
        if violation:
            violations.append(violation)

    worktree = check_change("uncommitted working tree", _worktree_files(repo))
    if worktree:
        violations.append(worktree)

    return violations


def main() -> int:
    staged_only = "--staged-only" in sys.argv
    try:
        violations = check_staged() if staged_only else collect_violations()
    except subprocess.CalledProcessError as exc:
        print(f"docs-check: git failed: {exc.stderr or exc}", file=sys.stderr)
        return 1

    if violations:
        print(f"docs-check FAILED — {len(violations)} change(s) touched src/ with no docs:")
        for violation in violations:
            print(violation.render())
        print("\nFix: update the relevant doc (an ADR, a research note, STATE.md),")
        print(f"or add '{SKIP_TOKEN}' to the commit message if it is a pure refactor.")
        return 1

    print("all src changes have docs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
