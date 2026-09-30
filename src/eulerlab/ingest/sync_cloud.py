"""`make sync-cloud` — mirror the landing zone to object storage."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from eulerlab.ingest import landing_reader
from eulerlab.ingest.cloud import (
    InsufficientCapabilities,
    MissingCredentials,
    S3ObjectStore,
    SyncResult,
    full_listing,
    load_storage_config,
    plan_sync,
    sync,
    sync_directory,
)
from eulerlab.ingest.landing import Landing
from eulerlab.ingest.manifest import TREES

DEFAULT_LANDING = Path("data/landing/nse")
DEFAULT_CONFIG = Path("config/storage.yaml")

MAX_DISCOVERY_SWEEPS = 5
"""How many times to re-scan the landing root for trees that appeared mid-run.

Bounded rather than looping until stable: a writer producing a new tree faster
than the sync drains them would otherwise never let the command finish, and
anything still arriving by the fifth sweep is honestly the next run's work.
"""


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

    # One enumeration of the bucket, shared by everything below. Previously the
    # bhavcopy diff listed the whole prefix, then each tree listed its own
    # again, then the census listed all twelve a third time: 25 listings and
    # 314 of the mirror's 578 seconds, every one of them a subset of the first.
    remote_sizes = full_listing(store, config.prefix)
    print(f"listed: {len(remote_sizes):,} objects")

    # NB: dry-run must NOT return early here. It did once, which meant it
    # reported only on the nse tree and printed a reassuring "would upload: 0"
    # while thousands of files in other trees were unsynced.
    if args.dry_run:
        plan = plan_sync(landing, store, config, verify=args.verify, remote_sizes=remote_sizes)
        print(f"would upload : {len(plan.upload)}")
        print(f"already there: {len(plan.already_present)}")
        print(f"mismatched   : {len(plan.mismatched)}")
        result = SyncResult(0, len(plan.already_present), [], [])
    else:
        result = sync(landing, store, config, verify=args.verify, remote_sizes=remote_sizes)
        print(f"uploaded : {result.uploaded}")
        print(f"skipped  : {result.skipped}  (already present, matching {check})")

    # Every dataset tree under the landing root is mirrored, discovered rather
    # than listed. Hardcoding each one meant a new dataset was silently never
    # backed up until someone noticed - which happened twice (participant OI,
    # then fundamentals). Discovery makes forgetting impossible.
    #
    # But discovery ONCE is not enough, and that cost a full re-run. This walk
    # used to enumerate the landing root a single time, at the start. A tree
    # created while the sync was running - a backfill finishing after the sync
    # began - was simply not in the list, so it was never uploaded, and the run
    # still exited 0. A gigabyte of crypto sat unmirrored while the command
    # reported success.
    #
    # So the root is re-scanned after each pass and any tree that has appeared
    # is picked up, until a pass finds nothing new. Bounded, because a
    # sufficiently fast writer could otherwise keep it going forever - and
    # anything still arriving after that is genuinely the next run's job.
    tree_uploads: list[str] = []
    done: set[str] = set()
    for sweep in range(1, MAX_DISCOVERY_SWEEPS + 1):
        others = sorted(
            d
            for d in args.landing_root.iterdir()
            if d.is_dir() and d.name != args.landing.name and d.name not in done
        )
        if not others:
            break
        if sweep > 1:
            print(f"\n-- sweep {sweep}: {len(others)} tree(s) appeared mid-run --")

        for tree_root in others:
            done.add(tree_root.name)
            print(f"\n{tree_root.name} from {tree_root}:")
            tree = sync_directory(
                tree_root,
                store,
                prefix=f"{config.prefix}{tree_root.name}/",
                dry_run=args.dry_run,
                # Sweeps after the first re-list: a tree that appeared mid-run
                # is by definition not in a listing taken before it existed.
                remote_sizes=remote_sizes if sweep == 1 else None,
            )
            tree_uploads.extend(tree.uploaded_keys)
            print(f"  uploaded : {tree.uploaded}")
            print(f"  skipped  : {tree.skipped}")
            if tree.failed:
                print(f"  FAILED   : {len(tree.failed)}")
                for problem in tree.failed[:10]:
                    print(f"    {problem}")
                result = SyncResult(
                    result.uploaded,
                    result.skipped,
                    result.mismatched,
                    [*result.failed, *tree.failed],
                )

    # The census reads the bucket next, tree by tree. It can read this instead
    # — but the listing was taken *before* the uploads, so what this run just
    # wrote is added to it first. Without that the primed answer describes the
    # bucket as it was on arrival, and a caller that prunes local files
    # between the sync and the census would see the files uploaded this run in
    # neither place and count them as gone. Today the two run in separate
    # processes so the cache never crosses; relying on that is not a design.
    post_upload = {*remote_sizes, *result.uploaded_keys, *tree_uploads}
    landing_reader.prime_listing(post_upload, config.prefix, [(t, p) for _, t, p in TREES])

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
