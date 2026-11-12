"""`make restore-local` — pull pruned files back down from B2.

The counterpart to `prune-local` (ADR-010). Pruning is only safe if restoring
is easy, and it is not easy if it does not exist. This closes that loop.

Restores are verified: the downloaded bytes must hash to the SHA-256 recorded
in the manifest. A cloud copy that has silently changed is a far worse problem
than a missing file, so it is caught here rather than trusted.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from eulerlab.ingest.cloud import S3ObjectStore, load_storage_config
from eulerlab.ingest.landing import READ_ONLY, Landing, sha256_of
from eulerlab.paths import data_path

DEFAULT_LANDING = data_path("landing/nse")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="restore-local",
        description="Download pruned landing-zone files back from B2.",
    )
    parser.add_argument("--landing", type=Path, default=DEFAULT_LANDING)
    parser.add_argument("--segment", default=None, help="e.g. cm, fo, participant_oi")
    parser.add_argument("--from", dest="start", type=date.fromisoformat, default=None)
    parser.add_argument("--to", dest="end", type=date.fromisoformat, default=None)
    args = parser.parse_args(argv)

    config = load_storage_config(Path("config/storage.yaml"))
    store = S3ObjectStore(config)
    landing = Landing(args.landing)

    wanted = []
    for entry in landing.entries().values():
        if args.segment and entry.segment != args.segment:
            continue
        day = date.fromisoformat(entry.trade_date)
        if args.start and day < args.start:
            continue
        if args.end and day > args.end:
            continue
        if not (args.landing / entry.path).exists():
            wanted.append(entry)

    if not wanted:
        print("nothing to restore — every matching file is already on disk")
        return 0

    print(f"restoring {len(wanted)} files from {config.bucket}...")
    restored = failed = 0
    for entry in wanted:
        key = f"{config.prefix}{entry.path}"
        target = args.landing / entry.path
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            payload = store.get(key)
        except Exception as exc:
            print(f"  {entry.path}: {exc}")
            failed += 1
            continue

        if sha256_of(payload) != entry.sha256:
            print(f"  {entry.path}: CHECKSUM MISMATCH — cloud copy differs from the manifest")
            failed += 1
            continue

        tmp = target.with_suffix(target.suffix + ".part")
        tmp.write_bytes(payload)
        tmp.chmod(READ_ONLY)
        tmp.replace(target)
        restored += 1
        if restored % 200 == 0:
            print(f"  {restored}/{len(wanted)}")

    print(f"\nrestored {restored}, failed {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
