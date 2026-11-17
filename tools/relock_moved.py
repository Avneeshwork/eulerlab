"""``make relock-moved`` — relock deployments whose code only moved (ADR-219).

A deployment's version lock is a hash of the source text that defines its
strategy (ADR-087). ADR-219 moved the strategy files and rewrote import lines,
so the hash of some unchanged strategies changed too, and their deployments
would report "code changed" although nothing they do changed.

This tool tells the two apart. For each deployment it computes the hash on the
code from just before the move (a temporary git worktree) and on the code now:

- lock == now                  nothing to do
- lock == before, now differs  only the move changed it: relock, with a note
- lock != before               the code changed before the move as well: left
                               alone, for the operator's own review

Dry run by default. ``--apply`` writes the new locks, each with its old hash
kept in the lock's history, so the step can be read back and undone.

Usage
  uv run python tools/relock_moved.py            report only
  uv run python tools/relock_moved.py --apply    relock the moved-only ones
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MARKER = "src/eulerlab/strategies/daily/__init__.py"
"""Added by the ADR-219 move: its first commit's parent is the code before it."""
NOTE = "ADR-219: strategy files moved, code unchanged (the lock matched the code before the move)"

_HASH_BEFORE = """
import json, sys
from eulerlab.deploy import version_lock
print(json.dumps({s: version_lock.fingerprint(s) for s in sys.argv[1:]}))
"""


def decide(locked: str, before: str, now: str) -> str:
    """``same``, ``relock`` or ``review`` for one deployment."""
    if locked == now:
        return "same"
    if before and locked == before and now:
        return "relock"
    return "review"


def pre_move_commit() -> str:
    added = subprocess.run(
        ["git", "log", "--format=%H", "--diff-filter=A", "-1", "--", MARKER],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if not added:
        msg = f"{MARKER} is not in this branch's history: nothing has moved"
        raise SystemExit(msg)
    return f"{added}^"


def hashes_at(commit: str, strategy_ids: Sequence[str]) -> dict[str, str]:
    """Fingerprints on the code at `commit`, read with today's cards and data."""
    with tempfile.TemporaryDirectory() as tmp:
        tree = Path(tmp) / "tree"
        subprocess.run(
            ["git", "worktree", "add", "--detach", "-q", str(tree), commit], cwd=REPO, check=True
        )
        try:
            env = {**os.environ, "PYTHONPATH": str(tree / "src")}
            out = subprocess.run(
                [sys.executable, "-c", _HASH_BEFORE, *strategy_ids],
                cwd=REPO,
                env=env,
                check=True,
                capture_output=True,
                text=True,
            ).stdout
        finally:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(tree)], cwd=REPO, check=False
            )
    result: dict[str, str] = json.loads(out.strip().splitlines()[-1])
    return result


def main(argv: Sequence[str] | None = None) -> int:
    sys.path.insert(0, str(REPO / "src"))
    from eulerlab.deploy import deployments, version_lock
    from eulerlab.deploy.deployments import Deployment

    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--apply", action="store_true", help="write the new locks")
    parser.add_argument("--before", help="the commit before the move (found from git if absent)")
    args = parser.parse_args(argv)

    locked: dict[str, tuple[Deployment, str]] = {}
    for d in deployments.all_deployments():
        path = d.folder / version_lock.FILE
        if path.exists():
            locked[d.id] = (d, str(json.loads(path.read_text(encoding="utf-8")).get("fingerprint")))
    ids = sorted({d.strategy_id for d, _ in locked.values()})
    before: Mapping[str, str] = hashes_at(args.before or pre_move_commit(), ids)
    counts = {"same": 0, "relock": 0, "review": 0}
    for deployment_id, (d, lock) in sorted(locked.items()):
        sid = d.strategy_id
        action = decide(lock, before.get(sid, ""), version_lock.fingerprint(sid))
        counts[action] += 1
        if action == "same":
            continue
        print(f"{action:7} {deployment_id}")
        if action == "relock" and args.apply:
            version_lock.relock(d.folder, sid, NOTE)
    verb = "relocked" if args.apply else "would relock"
    print(
        f"{counts['same']} unchanged, {verb} {counts['relock']} that only moved, "
        f"{counts['review']} changed before the move (left for review)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
