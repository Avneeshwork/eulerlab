"""Operator-owned files change only with an `Operator-Ack:` trailer (ADR-217, issue #160).

On 2026-11-13 a one-line path refactor in `gates.py` halted every agent for
days: the guardian (`agents/guardian.py`) saw a protected file change and
nobody had said the change was meant. Two halves close that:

- **at commit time** (`check-msg`, a commit-msg hook in `.pre-commit-config.yaml`):
  a commit whose staged files include any of `guardian.PROTECTED` is refused
  unless its message carries a trailer `Operator-Ack: <reason>` (at least
  five characters, in the last paragraph with `Co-Authored-By:`). A merge is
  not checked: the commits it brings in were checked when they were made, and
  the hook witness logs any that skipped the hooks (ADR-161).
- **at run time** (`acked`): the guardian accepts a changed protected file when
  the last commit that touched it carries the trailer and the file on disk is
  exactly what that commit left. Any later edit, committed or not, trips it.

Only fixed, read-only git commands run here (`git diff --cached`, `git log`,
`git show`, `git interpret-trailers`). It lives outside `agents/` because no
agent module may import `subprocess` (`agents/boundaries.py`); the guardian
imports this one reviewed reader, as the engineering agent imports `devtools`.
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path

TRAILER = "Operator-Ack"
MIN_REASON = 5


def _git(repo: Path, *args: str, stdin: str | None = None) -> str:
    done = subprocess.run(
        ["git", *args],
        cwd=repo,
        input=stdin,
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout


def _git_bytes(repo: Path, *args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, check=True).stdout


def reasons(message: str, repo: Path = Path(".")) -> list[str]:
    """The `Operator-Ack:` reasons in a commit message's trailers, as git parses them."""
    parsed = _git(repo, "interpret-trailers", "--parse", stdin=message)
    found = []
    for line in parsed.splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip().lower() == TRAILER.lower() and len(value.strip()) >= MIN_REASON:
            found.append(value.strip())
    return found


def protected_paths() -> tuple[str, ...]:
    from eulerlab.agents import guardian

    return tuple(str(p) for p in guardian.PROTECTED)


def touched(staged: Iterable[str], protected: Iterable[str]) -> list[str]:
    wanted = set(protected)
    return sorted(p for p in staged if p in wanted)


def check_message(
    message: str,
    staged: Iterable[str],
    protected: Iterable[str],
    repo: Path = Path("."),
) -> str:
    """'' when the commit may go ahead, else why it is refused."""
    hit = touched(staged, protected)
    if not hit or reasons(message, repo):
        return ""
    return (
        f"refused: this commit changes operator-owned file(s) {', '.join(hit)}.\n"
        f"Add a trailer line `{TRAILER}: <why the operator wants this>` next to "
        "Co-Authored-By, or unstage them. Without it the guardian halts every agent "
        "(ADR-152, ADR-217)."
    )


def _merging(repo: Path) -> bool:
    try:
        _git(repo, "rev-parse", "-q", "--verify", "MERGE_HEAD")
    except subprocess.CalledProcessError:
        return False
    return True


def digest(data: bytes) -> str:
    """The guardian's fingerprint of a file's bytes (`guardian.fingerprints`)."""
    return hashlib.sha256(data).hexdigest()[:16]


def acked(repo: Path, rel: str, current: str) -> str:
    """The ack reason when the last commit touching `rel` is acked and left it as
    `current` (a `digest`, or "absent"); '' otherwise, and '' on any git error."""
    try:
        sha = _git(repo, "log", "-1", "--format=%H", "--", rel).strip()
        if not sha:
            return ""
        message = _git(repo, "log", "-1", "--format=%B", sha)
        why = reasons(message, repo)
        if not why:
            return ""
        try:
            left = digest(_git_bytes(repo, "show", f"{sha}:{rel}"))
        except subprocess.CalledProcessError:
            left = "absent"  # the acked commit deleted it
    except (OSError, subprocess.CalledProcessError):
        return ""
    return f"{sha[:10]} {why[0]}" if left == current else ""


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check-msg", help="the commit-msg hook")
    c.add_argument("message_file")
    args = parser.parse_args(argv)
    repo = Path(".")
    if _merging(repo):
        return 0
    staged = _git(repo, "diff", "--cached", "--name-only").splitlines()
    message = Path(args.message_file).read_text(encoding="utf-8")
    why = check_message(message, staged, protected_paths(), repo)
    if why:
        print(why, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
