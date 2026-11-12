"""How long each scheduled step took, and whether it finished: `data/derived/timings.jsonl`.

The operations agent reads this to say which job is getting slower and which
finished too close to its deadline; the data agent reads it to say which feed
step failed last night and why. Written by `ingest/daily_feed.py` for every
step it runs, and by anything else that wraps its work in `timed`.

Append-only, one line per step, small: a year of nightly runs is a few
thousand lines. Writing it can never fail the work it measures.
"""

from __future__ import annotations

import contextlib
import json
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from eulerlab.paths import data_path

PATH = data_path("derived/timings.jsonl")


def record(
    job: str,
    seconds: float,
    *,
    ok: bool,
    detail: str = "",
    finished: datetime | None = None,
    path: Path | None = None,
) -> None:
    path = path or PATH
    row = {
        "job": job,
        "seconds": round(seconds, 3),
        "ok": ok,
        "detail": detail[:300],
        "finished": (finished or datetime.now(UTC)).isoformat(timespec="seconds"),
    }
    with contextlib.suppress(OSError):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row) + "\n")


@contextlib.contextmanager
def timed(job: str, path: Path | None = None) -> Iterator[None]:
    began = time.monotonic()
    try:
        yield
    except BaseException as exc:
        record(
            job,
            time.monotonic() - began,
            ok=False,
            detail=f"{type(exc).__name__}: {exc}",
            path=path,
        )
        raise
    record(job, time.monotonic() - began, ok=True, path=path)


def read(path: Path | None = None, *, since: datetime | None = None) -> list[dict[str, Any]]:
    path = path or PATH
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if since is not None and str(row.get("finished", "")) < since.isoformat():
            continue
        out.append(row)
    return out
