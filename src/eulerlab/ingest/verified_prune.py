"""`make upload-verified TREES=...` — upload a tree, then delete only what B2 proves it holds.

`upload-tree DELETE=1` deletes a local file when the bucket lists an object of
the same size. This is the stricter path the operator asked for on 2026-10-30
for the new datasets: a file goes only when the bucket's object has the same
size **and** the SHA-256 recorded on upload equals the hash of the local
bytes, computed now. Anything that fails either check is kept and named.
The manifests stay, so `landed()` checks and restores still work.
"""

from __future__ import annotations

import argparse
import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from eulerlab.ingest.cloud import ObjectStore, S3ObjectStore, load_storage_config, sync_directory
from eulerlab.ingest.prune_local import SKIP_NAMES

DEFAULT_ROOT = Path("data/landing")
DEFAULT_CONFIG = Path("config/storage.yaml")


@dataclass
class VerifiedPrune:
    deleted: list[Path] = field(default_factory=list)
    kept: list[tuple[Path, str]] = field(default_factory=list)
    bytes_freed: int = 0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def prune_verified(
    root: Path, name: str, store: ObjectStore, *, prefix: str, dry_run: bool = False
) -> VerifiedPrune:
    """Delete each local file of `root/name` that B2 holds byte-for-byte."""
    tree = root / name
    result = VerifiedPrune()
    remote = store.list_sizes(f"{prefix}{name}/")
    for path in sorted(p for p in tree.rglob("*") if p.is_file() and p.name not in SKIP_NAMES):
        key = f"{prefix}{path.relative_to(root).as_posix()}"
        size = path.stat().st_size
        if remote.get(key) != size:
            result.kept.append((path, "not in the bucket at this size"))
            continue
        if store.head_sha256(key) != _sha256(path):
            result.kept.append((path, "SHA-256 differs from the bucket's"))
            continue
        if not dry_run:
            path.unlink()
        result.deleted.append(path)
        result.bytes_freed += size
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="upload-verified")
    parser.add_argument("trees", nargs="+")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--keep", action="store_true", help="upload and verify, delete nothing")
    args = parser.parse_args(argv)

    config = load_storage_config(args.config)
    store = S3ObjectStore(config)
    failed = 0
    for name in args.trees:
        if name == "nse" or Path(name).name != name or not (args.root / name).is_dir():
            print(f"{name}: not a dataset tree on this machine, skipped")
            continue
        upload = sync_directory(args.root / name, store, prefix=f"{config.prefix}{name}/")
        print(f"{name}: uploaded {upload.uploaded}, already there {upload.skipped}")
        failed += len(upload.failed)
        pruned = prune_verified(args.root, name, store, prefix=config.prefix, dry_run=args.keep)
        verb = "verified" if args.keep else "verified and deleted"
        print(
            f"{name}: {verb} {len(pruned.deleted)} files ({pruned.bytes_freed / 1e6:.1f} MB), "
            f"kept {len(pruned.kept)}"
        )
        for path, why in pruned.kept[:10]:
            print(f"    kept {path}: {why}")
        failed += len(pruned.kept)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
