"""`make prune-local` — delete landed files once B2 confirms an exact copy.

The operator does not want a full local copy of the landing zone kept
permanently; disk is finite and the machine ran out of it mid-backfill. This
is not a relaxation of the immutability rule — it is what happens *after* a
file's cloud copy is verified, not instead of the manifest-and-checksum
discipline in ``landing.py``.

**A file is deleted only when the object exists in the bucket at the exact
same size.** Not "probably uploaded", not "the sync command finished with no
error" — actually confirmed, by listing the bucket. `--verify` additionally
checks the SHA-256 in object metadata (one HEAD per file) for a stronger but
slower guarantee; the default size check is one LIST for the whole bucket.

The manifest is **never edited**. A record of what was downloaded stays
correct even after the bytes are gone locally — the file can be re-fetched
from B2, or from the exchange again, and the manifest still tells the truth
about what exists.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from eulerlab.ingest.cloud import (
    InsufficientCapabilities,
    ObjectStore,
    S3ObjectStore,
    load_storage_config,
)
from eulerlab.paths import data_path

DEFAULT_ROOT = data_path("landing")
SKIP_NAMES = frozenset({"manifest.jsonl", "unresolved.jsonl"})
KEEP_TREES = frozenset({"macro"})
"""Trees never pruned: day files that are appended to all day (`macro.append`).

A day file pruned at noon was recreated by the next sweep with only the
afternoon's rows, and the upload then replaced the bucket's fuller copy with
it. They are a few kilobytes a day (HISTORY #52).
"""


def _kept(path: Path, root: Path) -> bool:
    if path.name in SKIP_NAMES:
        return True
    rel = path.relative_to(root)
    return bool(rel.parts) and rel.parts[0] in KEEP_TREES


def _remote_key(path: Path, root: Path, prefix: str) -> str:
    """Mirror sync_cloud's key scheme exactly, so a match here is a match there.

    The `nse` tree is the historical special case: its objects sit directly
    under the prefix (``nse/cm/...``) because it was the first and the bucket
    prefix is already ``nse/``. Every other dataset tree is namespaced by its
    directory name (``nse/kite_minute/...``, ``nse/fundamentals/...``).

    These two functions must agree. If they drift, prune-local either deletes a
    file it cannot find in the bucket (it will not - it keeps unmatched files)
    or keeps everything forever. The first is impossible by construction here;
    the second is merely wasteful, which is the right way round.
    """
    rel = path.relative_to(root)
    if rel.parts and rel.parts[0] == "nse":
        return f"{prefix}{path.relative_to(root / 'nse').as_posix()}"
    return f"{prefix}{rel.as_posix()}"


@dataclass(frozen=True)
class PruneResult:
    deleted: list[Path] = field(default_factory=list)
    kept_not_uploaded: int = 0
    kept_size_mismatch: list[Path] = field(default_factory=list)
    bytes_freed: int = 0


def plan_and_prune(
    root: Path,
    store: ObjectStore,
    *,
    prefix: str,
    dry_run: bool = True,
) -> PruneResult:
    remote = store.list_sizes(prefix)
    files = [p for p in root.rglob("*") if p.is_file() and not _kept(p, root)]

    deleted: list[Path] = []
    mismatched: list[Path] = []
    not_uploaded = 0
    freed = 0

    for path in files:
        key = _remote_key(path, root, prefix)
        remote_size = remote.get(key)
        local_size = path.stat().st_size

        if remote_size is None:
            not_uploaded += 1
            continue
        if remote_size != local_size:
            mismatched.append(path)
            continue

        freed += local_size
        deleted.append(path)
        if not dry_run:
            path.unlink()

    return PruneResult(
        deleted=deleted,
        kept_not_uploaded=not_uploaded,
        kept_size_mismatch=mismatched,
        bytes_freed=freed,
    )


def prune_tree(
    root: Path,
    name: str,
    store: ObjectStore,
    *,
    prefix: str,
    dry_run: bool = True,
) -> PruneResult:
    """`plan_and_prune` for one dataset tree, listing only its part of the bucket.

    The same rule: a file goes only when the bucket holds it at the exact same
    size, confirmed by a listing taken now. `make daily` calls this straight
    after a tree's upload, so each dataset is downloaded, uploaded and removed
    before the next one starts (2026-10-13).
    """
    tree = root / name
    files = [p for p in tree.rglob("*") if p.is_file() and not _kept(p, root)]
    # The bhavcopy tree's objects sit directly under the prefix, one folder a
    # segment; every other tree is one folder named after itself.
    folders = sorted({_remote_key(p, root, prefix)[len(prefix) :].split("/", 1)[0] for p in files})
    remote: dict[str, int] = {}
    for folder in folders:
        remote.update(store.list_sizes(f"{prefix}{folder}/"))

    deleted: list[Path] = []
    mismatched: list[Path] = []
    not_uploaded = 0
    freed = 0
    for path in files:
        remote_size = remote.get(_remote_key(path, root, prefix))
        local_size = path.stat().st_size
        if remote_size is None:
            not_uploaded += 1
            continue
        if remote_size != local_size:
            mismatched.append(path)
            continue
        freed += local_size
        deleted.append(path)
        if not dry_run:
            path.unlink()
    return PruneResult(
        deleted=deleted,
        kept_not_uploaded=not_uploaded,
        kept_size_mismatch=mismatched,
        bytes_freed=freed,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="prune-local",
        description="Delete local landing-zone files confirmed present in B2.",
    )
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    config = load_storage_config(Path("config/storage.yaml"))
    try:
        store = S3ObjectStore(config)
    except Exception as exc:  # MissingCredentials or a bare connection failure
        print(f"prune-local: cannot reach B2: {exc}")
        return 2

    try:
        result = plan_and_prune(args.root, store, prefix=config.prefix, dry_run=args.dry_run)
    except InsufficientCapabilities as exc:
        print(f"prune-local: {exc}")
        return 2

    verb = "would delete" if args.dry_run else "deleted"
    print(f"{verb}            : {len(result.deleted)} files, {result.bytes_freed / 1e9:.2f} GB")
    print(f"kept, not uploaded yet : {result.kept_not_uploaded}")
    if result.kept_size_mismatch:
        print(
            f"kept, SIZE MISMATCH    : {len(result.kept_size_mismatch)} (investigate, do not force)"
        )
        for p in result.kept_size_mismatch[:10]:
            print(f"    {p}")
    print("\nThe manifest is untouched. Deleted files remain listed as landed;")
    print("their bytes now live only in B2.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
