"""`make sync-cloud` — mirror the landing zone to object storage."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from eulerlab.ingest.cloud import (
    MissingCredentials,
    S3ObjectStore,
    load_storage_config,
    plan_sync,
    sync,
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
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would be uploaded, send nothing",
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

    if args.dry_run:
        plan = plan_sync(landing, store, config)
        print(f"would upload : {len(plan.upload)}")
        print(f"already there: {len(plan.already_present)}")
        print(f"mismatched   : {len(plan.mismatched)}")
        return 1 if plan.mismatched else 0

    result = sync(landing, store, config)
    print(f"uploaded : {result.uploaded}")
    print(f"skipped  : {result.skipped}  (already present with a matching hash)")

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
