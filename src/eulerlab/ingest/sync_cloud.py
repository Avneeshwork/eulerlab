"""`make sync-cloud` — mirror the landing zone to object storage."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from eulerlab.ingest.cloud import (
    InsufficientCapabilities,
    MissingCredentials,
    S3ObjectStore,
    SyncResult,
    load_storage_config,
    plan_sync,
    sync,
    sync_directory,
)
from eulerlab.ingest.landing import Landing

DEFAULT_LANDING = Path("data/landing/nse")
DEFAULT_CONFIG = Path("config/storage.yaml")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sync-cloud",
        description="Mirror the landing zone to S3-compatible object storage.",
    )
    parser.add_argument("--landing", type=Path, default=DEFAULT_LANDING)
    parser.add_argument(
        "--landing-root",
        type=Path,
        default=Path("data/landing"),
        help="root under which every dataset tree is discovered and mirrored",
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would be uploaded, send nothing",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help=(
            "compare every object's recorded SHA-256, not just its size. "
            "One request per object, so slow; run it as an occasional audit."
        ),
    )
    args = parser.parse_args(argv)

    config = load_storage_config(args.config)
    landing = Landing(args.landing)
    if not landing.entries():
        print(f"landing zone {args.landing} is empty — nothing to sync")
        return 0

    try:
        store = S3ObjectStore(config)
    except MissingCredentials as exc:
        print(f"sync-cloud: {exc}")
        print("\nCreate a Backblaze B2 application key, then put it in .env:")
        print("  B2_KEY_ID=...")
        print("  B2_APP_KEY=...")
        return 2

    print(f"target: {config.provider} {config.bucket}/{config.prefix} @ {config.endpoint_url}")

    try:
        _ = store.head_sha256(f"{config.prefix}__preflight_probe__")
    except InsufficientCapabilities as exc:
        print(f"\nsync-cloud: {exc}")
        return 2

    check = "sha256" if args.verify else "size"
    print(f"comparing by: {check}")

    # NB: dry-run must NOT return early here. It did once, which meant it
    # reported only on the nse tree and printed a reassuring "would upload: 0"
    # while thousands of files in other trees were unsynced.
    if args.dry_run:
        plan = plan_sync(landing, store, config, verify=args.verify)
        print(f"would upload : {len(plan.upload)}")
        print(f"already there: {len(plan.already_present)}")
        print(f"mismatched   : {len(plan.mismatched)}")
        result = SyncResult(0, len(plan.already_present), [], [])
    else:
        result = sync(landing, store, config, verify=args.verify)
        print(f"uploaded : {result.uploaded}")
        print(f"skipped  : {result.skipped}  (already present, matching {check})")

    # Every dataset tree under the landing root is mirrored, discovered rather
    # than listed. Hardcoding each one meant a new dataset was silently never
    # backed up until someone noticed - which happened twice (participant OI,
    # then fundamentals). Discovery makes forgetting impossible.
    others = sorted(
        d for d in args.landing_root.iterdir() if d.is_dir() and d.name != args.landing.name
    )
    for tree_root in others:
        print(f"\n{tree_root.name} from {tree_root}:")
        tree = sync_directory(
            tree_root,
            store,
            prefix=f"{config.prefix}{tree_root.name}/",
            dry_run=args.dry_run,
        )
        print(f"  uploaded : {tree.uploaded}")
        print(f"  skipped  : {tree.skipped}")
        if tree.failed:
            print(f"  FAILED   : {len(tree.failed)}")
            for problem in tree.failed[:10]:
                print(f"    {problem}")
            result = SyncResult(
                result.uploaded, result.skipped, result.mismatched, [*result.failed, *tree.failed]
            )

    if result.mismatched:
        print("\nMISMATCHED — in the bucket with a different hash, left untouched:")
        for key in result.mismatched:
            print(f"  {key}")
        print("  Investigate before overwriting. This should not happen.")
    if result.failed:
        print(f"\nFAILED — {len(result.failed)}:")
        for problem in result.failed:
            print(f"  {problem}")

    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
