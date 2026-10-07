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

    # One full read of the panel, not three: the days already held are passed
    # to `build`, and afterwards only the bytes it appended are read.
    size = PANEL_PATH.stat().st_size if PANEL_PATH.exists() else 0
    held = cached_days()
    before = len(held)
    print(f"panel: {before:,} days already cached; fetching {args.start} to {args.end}")
    print("  (one B2 download per trading day; cached and resumable)")

    def progress(done: int, total: int) -> None:
        if done % 100 == 0 or done == total:
            print(f"  {done:,}/{total:,}")

    written, note = build(start=args.start, end=args.end, progress=progress, already=held)
    print(f"\nwrote {written:,} new days -> {PANEL_PATH}")
    print(f"panel now covers {len(held | cached_days(offset=size)):,} trading days")
    if note:
        print(f"\nincomplete: {note}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
