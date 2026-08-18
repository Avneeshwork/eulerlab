"""`make check-landing` — re-hash every landed file against the manifest.

The landing zone claims its files are never modified after they are written.
This is what turns that claim into something the operator can check in seconds
rather than something they have to take on trust.

A file the manifest lists but that is absent from disk is not automatically a
problem: `prune-local` deletes files once B2 has confirmed an identical copy,
and the manifest is deliberately left unedited when that happens (ADR-010). So
a missing local file is checked against the bucket before being called a
defect — genuinely missing (nowhere) is reported as IMMUTABILITY VIOLATED;
missing locally but present in B2 at the recorded size is reported separately
and does not fail the check.
"""

from __future__ import annotations

import sys
from pathlib import Path

from eulerlab.ingest.cloud import InsufficientCapabilities, S3ObjectStore, load_storage_config
from eulerlab.ingest.landing import Landing, sha256_of

DEFAULT_LANDING = Path("data/landing/nse")
STORAGE_CONFIG = Path("config/storage.yaml")


def _remote_sizes(prefix: str) -> dict[str, int] | None:
    """B2 object sizes under prefix, or None when B2 cannot be reached.

    None is a legitimate outcome — no credentials, no network — and the caller
    must fall back to treating every locally-absent file as a violation rather
    than silently skipping the check.
    """
    if not STORAGE_CONFIG.exists():
        return None
    try:
        config = load_storage_config(STORAGE_CONFIG)
        store = S3ObjectStore(config)
        return store.list_sizes(config.prefix)
    except (InsufficientCapabilities, Exception):
        return None


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    root = Path(args[0]) if args else DEFAULT_LANDING

    landing = Landing(root)
    entries = landing.entries()
    if not entries:
        print(f"landing zone {root} is empty — nothing ingested yet")
        return 0

    remote = _remote_sizes("nse/")
    real_problems: list[str] = []
    pruned: list[str] = []
    on_disk = 0

    for entry in entries.values():
        path = root / entry.path
        if not path.exists():
            if remote is not None and remote.get(f"nse/{entry.path}") == entry.size_bytes:
                pruned.append(entry.path)
            else:
                real_problems.append(f"{entry.path}: missing, and not confirmed in B2")
            continue
        on_disk += 1
        if sha256_of(path.read_bytes()) != entry.sha256:
            real_problems.append(f"{entry.path}: checksum changed since it was written")

    total_bytes = sum(e.size_bytes for e in entries.values())
    print(f"landed files      : {len(entries)}  ({on_disk} on disk, {len(pruned)} pruned to B2)")
    print(f"total size        : {total_bytes / 1_000_000:.1f} MB")
    print(f"total rows        : {sum(e.rows for e in entries.values()):,}")
    if remote is None:
        print("note: could not reach B2, so a locally-absent file cannot be told apart")
        print("      from a genuinely lost one. Treating all as violations.")

    if real_problems:
        print(f"\nIMMUTABILITY VIOLATED — {len(real_problems)} problem(s):")
        for problem in real_problems:
            print(f"  {problem}")
        return 1

    print("\nall on-disk files match their recorded checksums")
    if pruned:
        print(f"all {len(pruned)} pruned files confirmed present in B2 at their recorded size")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
