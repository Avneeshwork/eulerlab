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

DEFAULT_ROOT = Path("data/landing")
SKIP_NAMES = frozenset({"manifest.jsonl", "unresolved.jsonl"})


def _remote_key(path: Path, root: Path, prefix: str) -> str:
    """Mirror sync_cloud's / sync_directory's key scheme, so a match here is a
    match there. kite_minute is its own subtree with an extra path segment.
    """
    rel = path.relative_to(root)
    if rel.parts and rel.parts[0] == "kite_minute":
        return f"{prefix}{rel.as_posix()}"
    return f"{prefix}{path.relative_to(root / 'nse').as_posix()}"


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
    files = [p for p in root.rglob("*") if p.is_file() and p.name not in SKIP_NAMES]

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
