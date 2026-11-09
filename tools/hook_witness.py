"""Record every commit that was made without the pre-commit hooks.

``git commit --no-verify`` skips pre-commit and commit-msg, but git still runs
post-commit. git runs commit-msg only after every pre-commit hook passed, so a
commit-msg hook writes the tree they approved, and the post-commit hook
compares it with the tree that was committed. A mismatch means
the hooks did not run on this commit; it is appended to
``data/logs/skipped_hooks.jsonl`` and ``make hygiene`` reports the count.

This does not block anything. It makes skipping visible, which is the part that
was missing (audit 2026-11-09, ADR-161).

  tools/hook_witness.py mark     commit-msg stage
  tools/hook_witness.py check    post-commit stage
  tools/hook_witness.py report   print the log
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LOG = REPO / "data" / "logs" / "skipped_hooks.jsonl"


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout.strip()


def _marker() -> Path:
    return Path(_git("rev-parse", "--absolute-git-dir")) / "eulerlab-hooks-approved"


def mark() -> int:
    _marker().write_text(_git("write-tree") + "\n")
    return 0


def check() -> int:
    marker = _marker()
    approved = marker.read_text().strip() if marker.exists() else ""
    marker.unlink(missing_ok=True)
    tree = _git("rev-parse", "HEAD^{tree}")
    if approved == tree:
        return 0
    entry = {
        "at": datetime.now(UTC).isoformat(timespec="seconds"),
        "commit": _git("rev-parse", "--short", "HEAD"),
        "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "subject": _git("log", "-1", "--format=%s"),
    }
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")
    print(f"hook-witness: {entry['commit']} was committed without the hooks; logged.")
    return 0


def report() -> int:
    rows = [json.loads(x) for x in LOG.read_text().splitlines()] if LOG.exists() else []
    print(f"commits made without hooks: {len(rows)}")
    for row in rows[-20:]:
        print(f"  {row['at']} {row['commit']} {row['branch']}: {row['subject']}")
    return 0


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "report"
    sys.exit({"mark": mark, "check": check, "report": report}[action]())
