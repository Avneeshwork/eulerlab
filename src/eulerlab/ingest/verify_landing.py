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

import signal
import sys
from pathlib import Path

from eulerlab.ingest.cloud import S3ObjectStore, load_storage_config
from eulerlab.ingest.landing import Landing, sha256_of
from eulerlab.paths import data_path

DEFAULT_LANDING = data_path("landing/nse")
STORAGE_CONFIG = Path("config/storage.yaml")
REMOTE_LIST_TIMEOUT_S = 15


def _list_sizes_bounded(store: S3ObjectStore, prefix: str) -> dict[str, int]:
    """Abort a slow multi-page cloud listing after one overall deadline."""
    if not hasattr(signal, "setitimer"):
        return store.list_sizes(prefix)

    def timeout_handler(_signum: int, _frame: object) -> None:
        raise TimeoutError("B2 listing exceeded its integrity-check deadline")

    previous_handler = signal.signal(signal.SIGALRM, timeout_handler)
    previous_timer = signal.getitimer(signal.ITIMER_REAL)
    signal.setitimer(signal.ITIMER_REAL, REMOTE_LIST_TIMEOUT_S)
    try:
        return store.list_sizes(prefix)
    finally:
        signal.setitimer(signal.ITIMER_REAL, *previous_timer)
        signal.signal(signal.SIGALRM, previous_handler)


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
        # Bound both individual requests and the full multi-page listing so
        # an unavailable endpoint cannot stall this integrity check for minutes.
        store = S3ObjectStore(config, connect_timeout_s=3, read_timeout_s=5, max_attempts=1)
        return _list_sizes_bounded(store, prefix)
    except Exception:
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
    violations: list[str] = []
    pruned: list[str] = []
    unconfirmed: list[str] = []
    on_disk = 0

    for entry in entries.values():
        path = root / entry.path
        if not path.exists():
            if remote is None:
                unconfirmed.append(entry.path)
            elif remote.get(f"nse/{entry.path}") == entry.size_bytes:
                pruned.append(entry.path)
            else:
                violations.append(
                    f"{entry.path}: missing, and not present at the recorded size in B2"
                )
            continue
        on_disk += 1
        if sha256_of(path.read_bytes()) != entry.sha256:
            violations.append(f"{entry.path}: checksum changed since it was written")

    total_bytes = sum(e.size_bytes for e in entries.values())
    print(f"landed files      : {len(entries)}  ({on_disk} on disk, {len(pruned)} pruned to B2)")
    print(f"total size        : {total_bytes / 1_000_000:.1f} MB")
    print(f"total rows        : {sum(e.rows for e in entries.values()):,}")
    if remote is None:
        print("note: could not reach B2, so a locally-absent file cannot be told apart")
        print("      from a genuinely lost one.")

    if violations:
        print(f"\nIMMUTABILITY VIOLATED — {len(violations)} problem(s):")
        for problem in violations[:20]:
            print(f"  {problem}")
        if len(violations) > 20:
            print(f"  ... and {len(violations) - 20} more")
        return 1

    if unconfirmed:
        print(
            f"\nINTEGRITY UNVERIFIED — {len(unconfirmed)} locally pruned file(s) could not be checked in B2"
        )
        return 1

    print("\nall on-disk files match their recorded checksums")
    if pruned:
        print(f"all {len(pruned)} pruned files confirmed present in B2 at their recorded size")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
