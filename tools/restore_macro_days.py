"""Restore macro days whose B2 copy lost rows to a shorter overwrite (T-4365).

HISTORY #54 found six `macro/` day files whose current bucket object holds
fewer readings than an older version of it. Each day file is append-only, so
the true file is the union of its versions (`macro.merge_day_versions`). This
writes that union as the current object. B2 keeps every older version, so the
write loses nothing and can be undone by restoring the version it replaced.

Dry run by default: it prints, per day, the versions found, the rows in the
current object, the rows in the union, and the rows the Mac's local copy has.
`--apply` uploads, then reads the object back and checks it is the union.

It never touches `data/landing/`: the local copy is raw landed data and is
reported, not rewritten. It never writes a union that is not a superset of
every version, and never writes when the current object already is the union.

    uv run python tools/restore_macro_days.py                 # dry run, the six days
    uv run python tools/restore_macro_days.py --apply
    uv run python tools/restore_macro_days.py --day 2026-10-29
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

DAYS = ("2026-08-24", "2026-10-07", "2026-10-14", "2026-10-15", "2026-10-18", "2026-10-29")
"""The days HISTORY #54 (c) found short."""


class VersionedStore(Protocol):
    def versions(self, key: str) -> list[tuple[str, str, int]]: ...

    def get_version(self, key: str, version_id: str) -> bytes: ...

    def get(self, key: str) -> bytes: ...

    def put(self, key: str, payload: bytes, sha256: str) -> None: ...


@dataclass(frozen=True)
class DayPlan:
    day: str
    key: str
    versions: int
    current_rows: int
    merged_rows: int
    local_rows: int | None
    merged: bytes

    @property
    def recovered(self) -> int:
        return self.merged_rows - self.current_rows

    @property
    def needed(self) -> bool:
        return self.recovered > 0


def _rows(payload: bytes) -> list[str]:
    return [line for line in payload.decode("utf-8", "replace").splitlines() if line.strip()]


def _is_superset(merged: bytes, version: bytes) -> bool:
    have = Counter(_rows(merged))
    return all(have[line] >= count for line, count in Counter(_rows(version)).items())


def plan_day(store: VersionedStore, day: str, *, prefix: str, landing: Path) -> DayPlan:
    from eulerlab.macro import merge_day_versions

    key = f"{prefix}macro/{day}.jsonl"
    listed = store.versions(key)
    if not listed:
        msg = f"{key}: no versions in the bucket"
        raise LookupError(msg)
    payloads = [store.get_version(key, version_id) for version_id, _, _ in listed]
    texts = [payload.decode("utf-8", "replace") for payload in payloads]
    merged = merge_day_versions(texts).encode("utf-8")
    for version, payload in zip(listed, payloads, strict=True):
        if not _is_superset(merged, payload):  # a bug in the merge, never expected
            msg = f"{key}: the union is missing rows of version {version[0]}"
            raise AssertionError(msg)
    current = store.get(key)
    local = landing / "macro" / f"{day}.jsonl"
    return DayPlan(
        day=day,
        key=key,
        versions=len(listed),
        current_rows=len(_rows(current)),
        merged_rows=len(_rows(merged)),
        local_rows=len(_rows(local.read_bytes())) if local.exists() else None,
        merged=merged,
    )


def apply_day(store: VersionedStore, plan: DayPlan) -> None:
    sha = hashlib.sha256(plan.merged).hexdigest()
    store.put(plan.key, plan.merged, sha)
    back = store.get(plan.key)
    if hashlib.sha256(back).hexdigest() != sha:
        msg = f"{plan.key}: the object read back is not what was written"
        raise RuntimeError(msg)


def run(
    store: VersionedStore,
    days: Sequence[str],
    *,
    prefix: str,
    landing: Path,
    apply: bool,
) -> int:
    print(f"{'day':<12}{'versions':>9}{'current':>9}{'union':>8}{'recover':>9}{'local':>7}  action")
    failures = 0
    for day in days:
        try:
            plan = plan_day(store, day, prefix=prefix, landing=landing)
        except Exception as exc:
            print(f"{day:<12}  FAILED: {exc}")
            failures += 1
            continue
        local = "-" if plan.local_rows is None else str(plan.local_rows)
        if not plan.needed:
            action = "nothing to do: the current object is the union"
        elif apply:
            try:
                apply_day(store, plan)
                action = "restored, read back and checked"
            except Exception as exc:
                action = f"FAILED: {exc}"
                failures += 1
        else:
            action = "would restore (dry run)"
        print(
            f"{plan.day:<12}{plan.versions:>9}{plan.current_rows:>9}{plan.merged_rows:>8}"
            f"{plan.recovered:>9}{local:>7}  {action}"
        )
    if not apply:
        print("dry run: nothing written. Add --apply to upload.")
    print("data/landing is never changed. A local copy shorter than the union is reported only.")
    return 1 if failures else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--day", action="append", help="a day to check (default: the six)")
    parser.add_argument("--apply", action="store_true", help="upload the union")
    args = parser.parse_args(argv)

    from eulerlab.ingest import landing_reader
    from eulerlab.ingest.cloud import S3ObjectStore, load_storage_config

    config = load_storage_config(landing_reader.STORAGE_CONFIG)
    store = S3ObjectStore(config)
    return run(
        store,
        args.day or DAYS,
        prefix=config.prefix,
        landing=landing_reader.LANDING_ROOT,
        apply=args.apply,
    )


if __name__ == "__main__":
    sys.exit(main())
