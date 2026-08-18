"""`make check-landing` — re-hash every landed file against the manifest.

The landing zone claims its files are never modified after they are written.
This is what turns that claim into something the operator can check in seconds
rather than something they have to take on trust.
"""

from __future__ import annotations

import sys
from pathlib import Path

from eulerlab.ingest.landing import Landing

DEFAULT_LANDING = Path("data/landing/nse")


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    root = Path(args[0]) if args else DEFAULT_LANDING

    landing = Landing(root)
    entries = landing.entries()
    if not entries:
        print(f"landing zone {root} is empty — nothing ingested yet")
        return 0

    problems = landing.verify()
    total_bytes = sum(e.size_bytes for e in entries.values())
    print(f"landed files : {len(entries)}")
    print(f"total size   : {total_bytes / 1_000_000:.1f} MB")
    print(f"total rows   : {sum(e.rows for e in entries.values()):,}")

    if problems:
        print(f"\nIMMUTABILITY VIOLATED — {len(problems)} problem(s):")
        for problem in problems:
            print(f"  {problem}")
        return 1

    print("\nall files match their recorded checksums")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
