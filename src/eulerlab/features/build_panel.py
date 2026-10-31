"""`make build-panel` — fetch, adjust and cache the price panel."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from eulerlab.features.panel import PANEL_PATH, build, cached_days


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="build-panel", description=__doc__)
    parser.add_argument("--from", dest="start", default="2023-01-01")
    parser.add_argument("--to", dest="end", default="2026-12-31")
    args = parser.parse_args(argv)

    before = len(cached_days())
    print(f"panel: {before:,} days already cached; fetching {args.start} to {args.end}")
    print("  (one B2 download per trading day; cached and resumable)")

    def progress(done: int, total: int) -> None:
        if done % 100 == 0 or done == total:
            print(f"  {done:,}/{total:,}")

    written, note = build(start=args.start, end=args.end, progress=progress)
    print(f"\nwrote {written:,} new days -> {PANEL_PATH}")
    print(f"panel now covers {len(cached_days()):,} trading days")
    if note:
        print(f"\nincomplete: {note}")
        # A quarantined day is a finding for `make data-quality`, not a failed
        # build; only an early stop (the B2 cap) is worth a non-zero exit.
        return 2 if "cap" in note else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
