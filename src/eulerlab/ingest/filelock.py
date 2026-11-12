"""Cross-process locks, so two data runs cannot write the same file at once.

`make daily` runs from launchd at 19:30 and the Instruments button runs inside
the API. Nothing stopped both running together, and every derived file here is
append-only by day: two builders that each see 8 Oct missing would each append
it, and the panel would hold the day twice (T-4032).

Two layers:

- **`feed`** — held for a whole run, by `make daily` (through `main` below) and
  by the button. The second one to start is refused with who holds it, rather
  than queued behind a run that can take an hour.
- **one per appender** (`panel`, `nifty_options`, `market_history`,
  `paper_daily`) — held while that file is read-then-appended, so a manual
  `make build-panel` during a feed waits and then finds the day already there.

`fcntl.flock` is released by the kernel when the process dies, so a crashed run
never leaves a stale lock behind. POSIX only, which is what this project runs on.
"""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import IO

from eulerlab.paths import data_path

LOCK_DIR = data_path("derived/.locks")


class Busy(RuntimeError):
    """Another process holds the lock."""


def holder(name: str, directory: Path | None = None) -> dict[str, object] | None:
    """Who holds `name`, or None when it is free."""
    path = (directory or LOCK_DIR) / f"{name}.lock"
    if not path.exists():
        return None
    with path.open("a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.seek(0)
            try:
                found = json.loads(handle.read() or "{}")
            except json.JSONDecodeError:
                found = {}
            return found if isinstance(found, dict) else {}
        fcntl.flock(handle, fcntl.LOCK_UN)
    return None


@contextmanager
def exclusive(
    name: str,
    *,
    wait: bool = True,
    what: str = "",
    directory: Path | None = None,
) -> Iterator[None]:
    """Hold lock `name` for the block.

    `wait=False` raises `Busy` at once when it is held; `wait=True` blocks
    until it is free, which is right for an appender (the other writer finishes
    in seconds and leaves the day already written).
    """
    # Resolved per call, not bound as a default, so tests can point LOCK_DIR
    # at a temporary folder and never meet a real run's lock.
    directory = directory or LOCK_DIR
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.lock"
    handle: IO[str] = path.open("a+", encoding="utf-8")
    try:
        flags = fcntl.LOCK_EX if wait else fcntl.LOCK_EX | fcntl.LOCK_NB
        try:
            fcntl.flock(handle, flags)
        except BlockingIOError:
            handle.seek(0)
            raw = handle.read()
            msg = f"{name} is held by another run: {raw or 'unknown holder'}"
            raise Busy(msg) from None
        handle.seek(0)
        handle.truncate()
        handle.write(
            json.dumps(
                {
                    "pid": os.getpid(),
                    "since": datetime.now(UTC).isoformat(timespec="seconds"),
                    "what": what or name,
                }
            )
        )
        handle.flush()
        yield
    finally:
        # Unlocking by closing; the holder record is left as written, and
        # `holder()` only believes it while the lock is actually held.
        handle.close()


def main(argv: Sequence[str] | None = None) -> int:
    """`python -m eulerlab.ingest.filelock NAME -- command...`

    Runs the command while holding NAME, or exits 75 (EX_TEMPFAIL) at once when
    another run holds it. `make daily` goes through this so the button and the
    overnight job cannot overlap.
    """
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 3 or args[1] != "--":
        print("usage: python -m eulerlab.ingest.filelock NAME -- command...", file=sys.stderr)
        return 2
    name, command = args[0], args[2:]
    try:
        with exclusive(name, wait=False, what=" ".join(command)):
            started = time.monotonic()
            code = subprocess.call(command)
            print(f"[{name}] finished in {time.monotonic() - started:.0f}s, exit {code}")
            return code
    except Busy as exc:
        print(f"[{name}] not started: {exc}")
        return 75


if __name__ == "__main__":
    raise SystemExit(main())
