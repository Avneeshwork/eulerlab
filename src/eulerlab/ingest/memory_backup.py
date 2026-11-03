"""`make agents-backup` / `make agents-restore`: the agents' memory, kept in B2 (ADR-128).

Operator, 2026-11-03: "all things memory should be retained and store in B2".
What the agents know lives in four places, none of them in git and, until
now, none of them in the bucket:

    data/agents/              every run's output, the lab's memory of each idea
                              tested, tasks, the hash-chained log, plans
    research/agent_drafts/    the research agent's drafts and each run's record
    research/papers/          the library, which the research agent adds to daily
    data/derived/trials.jsonl the trial ledger every test is logged in first

**Compared by content, not size.** The landing-zone mirror compares sizes and
refuses to replace a bucket copy with a smaller file, which is right for raw
data that only grows. Memory files are rewritten (a plan, a task's state) and
can shrink, so here a file is sent when its MD5 differs from the bucket's
ETag (one listing per tree, `S3ObjectStore.list_md5`). Nothing in the bucket is
ever deleted; B2 keeps the earlier version of an overwritten file (A-098).

**Restore never overwrites.** `restore` writes a tree only into a folder that
is missing or empty, so a slip cannot replace today's memory with yesterday's.
"""

from __future__ import annotations

import argparse
import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from eulerlab.ingest.cloud import MissingCredentials, load_storage_config
from eulerlab.ingest.landing import sha256_of

DEFAULT_CONFIG = Path("config/storage.yaml")


@dataclass(frozen=True)
class Tree:
    name: str
    root: Path
    key: str
    """Under the bucket's prefix. The ledger keeps `make sync-derived`'s key."""
    pattern: str = "**/*"


TREES: tuple[Tree, ...] = (
    Tree("agents", Path("data/agents"), "memory/agents/"),
    Tree("drafts", Path("research/agent_drafts"), "memory/research/agent_drafts/"),
    Tree("papers", Path("research/papers"), "memory/research/papers/"),
    Tree("ledger", Path("data/derived"), "derived/", pattern="trials.jsonl"),
)

SKIP_PARTS = frozenset({"worktrees", "__pycache__", ".git"})
"""Folders never sent: the engineering agent's temporary git checkouts, caches."""
SKIP_SUFFIXES = (".lock", ".partial", ".tmp")


class Store(Protocol):
    def list_md5(self, prefix: str) -> dict[str, str]: ...
    def put(self, key: str, payload: bytes, sha256: str) -> None: ...
    def get(self, key: str) -> bytes: ...


@dataclass
class Result:
    tree: str
    sent: int = 0
    same: int = 0
    failed: list[str] = field(default_factory=list)


def files(tree: Tree) -> list[Path]:
    """The tree's files worth keeping, sorted."""
    if not tree.root.is_dir():
        return []
    return sorted(
        p
        for p in tree.root.glob(tree.pattern)
        if p.is_file()
        and not SKIP_PARTS & set(p.relative_to(tree.root).parts)
        and not p.name.endswith(SKIP_SUFFIXES)
    )


def backup(
    store: Store, prefix: str, trees: Sequence[Tree] = TREES, *, dry_run: bool = False
) -> list[Result]:
    """Send every file whose content differs from the bucket's copy. Deletes nothing."""
    out: list[Result] = []
    for tree in trees:
        result = Result(tree.name)
        remote = store.list_md5(prefix + tree.key)
        for path in files(tree):
            key = f"{prefix}{tree.key}{path.relative_to(tree.root).as_posix()}"
            try:
                payload = path.read_bytes()
                if remote.get(key) == hashlib.md5(payload, usedforsecurity=False).hexdigest():
                    result.same += 1
                    continue
                if not dry_run:
                    store.put(key, payload, sha256_of(payload))
                result.sent += 1
            except Exception as exc:  # one file must not stop the rest
                result.failed.append(f"{path}: {type(exc).__name__}: {str(exc)[:120]}")
        out.append(result)
    return out


def restore(store: Store, prefix: str, trees: Sequence[Tree] = TREES) -> list[Result]:
    """Download each tree into its folder, only when that folder is missing or empty."""
    out: list[Result] = []
    for tree in trees:
        result = Result(tree.name)
        if files(tree):
            result.failed.append(f"{tree.root} is not empty; restore only into an empty folder")
            out.append(result)
            continue
        for key in sorted(store.list_md5(prefix + tree.key)):
            relative = key[len(prefix + tree.key) :]
            target = (tree.root / relative).resolve()
            if not relative or tree.root.resolve() not in target.parents:
                result.failed.append(f"{key}: outside {tree.root}; skipped")
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(store.get(key))
            result.sent += 1
        out.append(result)
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agents-backup", description=__doc__)
    parser.add_argument("--restore", action="store_true", help="download into empty folders")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args(argv)
    from eulerlab.ingest.cloud import S3ObjectStore

    config = load_storage_config(args.config)
    try:
        store = S3ObjectStore(config)
    except MissingCredentials as exc:
        print(f"agents-backup: {exc}")
        return 2
    results = (
        restore(store, config.prefix)
        if args.restore
        else backup(store, config.prefix, dry_run=args.dry_run)
    )
    verb = "restored" if args.restore else ("would send" if args.dry_run else "sent")
    for r in results:
        print(f"{r.tree:<7} {verb} {r.sent}, unchanged {r.same}, failed {len(r.failed)}")
        for problem in r.failed[:10]:
            print(f"  {problem}")
    return 1 if any(r.failed for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
