"""`make sync-derived` — mirror `data/derived/` to B2, and drop a confirmed file.

`make sync-cloud` mirrors the landing zone, which is what every derived table
is rebuilt from. The derived tables themselves were never mirrored: rebuilding
the price panel from landing takes hours, and the machine is short of disk.
This puts them in the same bucket under `<prefix>derived/`, compared by size
like every other tree, with the SHA-256 recorded as object metadata.

`--drop PATH` deletes one local derived file, and only when the bucket holds it
at the same size **and** the same SHA-256. Nothing is deleted on the strength
of "the upload finished". The derived files the engines read are not dropped by
default; the operator names each one.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from eulerlab.ingest.cloud import (
    MissingCredentials,
    S3ObjectStore,
    load_storage_config,
    sync_directory,
)
from eulerlab.ingest.landing import sha256_of

DERIVED = Path("data/derived")
DEFAULT_CONFIG = Path("config/storage.yaml")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sync-derived")
    parser.add_argument("--root", type=Path, default=DERIVED)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--verify", action="store_true", help="HEAD every object's SHA-256 after upload"
    )
    parser.add_argument("--drop", type=Path, action="append", default=[])
    args = parser.parse_args(argv)

    config = load_storage_config(args.config)
    try:
        store = S3ObjectStore(config)
    except MissingCredentials as exc:
        print(f"sync-derived: {exc}")
        return 2
    try:
        relative_root = args.root.resolve().relative_to(DERIVED.resolve())
    except ValueError:
        parser.error(f"--root must be inside {DERIVED}")
    suffix = "" if relative_root == Path(".") else relative_root.as_posix()
    prefix = f"{config.prefix}derived/{suffix + '/' if suffix else ''}"
    print(f"target: {config.bucket}/{prefix}")

    # One file at a time. The derived tree is a few very large files, and twelve
    # concurrent uploads of them saturated the uplink and dropped the machine
    # offline three times (2026-10-07). Small-file trees keep the default.
    tree = sync_directory(
        args.root, store, prefix=prefix, dry_run=args.dry_run, verify=args.verify, workers=1
    )
    print(f"{'would upload' if args.dry_run else 'uploaded'} : {tree.uploaded}")
    print(f"skipped  : {tree.skipped}  (already present, matching size)")
    for problem in tree.failed:
        print(f"  FAILED {problem}")
    # A failed upload of one file does not stop a drop of another: each drop
    # checks its own file against the bucket by size and SHA-256.
    status = 1 if tree.failed else 0

    remote = store.list_sizes(prefix)
    for path in args.drop:
        key = f"{prefix}{path.resolve().relative_to(args.root.resolve()).as_posix()}"
        if not path.is_file():
            print(f"drop {path}: not on disk")
            continue
        payload = path.read_bytes()
        if remote.get(key) != len(payload) or store.head_sha256(key) != sha256_of(payload):
            print(f"drop {path}: KEPT — the bucket copy is missing or differs")
            status = 1
            continue
        path.unlink()
        print(f"drop {path}: deleted, {len(payload) / 1e6:.0f} MB; B2 holds {key}")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
