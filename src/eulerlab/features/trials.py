"""The append-only trial counter.

`CLAUDE.md`: *every strategy configuration evaluated increments the trial
counter in the append-only log. Never bypass it, never reset it.*

This is the first sprint that evaluates anything, so the counter starts here
rather than at Sprint 13 when it is first consumed. The reason it must start
now is that the number it protects is a *count of everything ever tried*, and
a count that begins late is worse than no count — it looks authoritative while
understating the denominator, which is exactly the direction that flatters.

The file is append-only and never rewritten. Each line records what was
evaluated, on what data, and what came out, so a later multiple-testing
correction can be computed from evidence rather than from memory of how many
things were tried.

With `EULERLAB_DATABASE_URL` set, a trials path under the data directory is a
stream in Postgres's `append_log` instead (ADR-165), where the table itself
refuses an update or delete. Readers go through `lines`, so both homes agree.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from eulerlab.db.stream import parse_time, stream_for
from eulerlab.paths import data_path

TRIALS_PATH = data_path("derived/trials.jsonl")
KIND = "trials"
"""The counter's kind in the database's append-only log."""


@dataclass(frozen=True)
class Trial:
    """One evaluated configuration."""

    logged_at: str
    feature: str
    horizon_days: int
    step_days: int
    panel_start: str
    panel_end: str
    n_periods: int
    mean_ic: float
    t_stat: float


def append(trial: Trial, path: Path = TRIALS_PATH) -> int:
    """Record a trial. Returns the new total count.

    Opened in append mode only. There is deliberately no update, no delete and
    no rewrite anywhere in this module.
    """
    line = json.dumps(asdict(trial), sort_keys=True)
    stream = stream_for(path, KIND)
    if stream is not None:
        stream.append(lambda _last, _seq: (line, parse_time(trial.logged_at)))
        return stream.count()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
    return count(path)


def lines(path: Path = TRIALS_PATH) -> list[str]:
    """Every recorded trial, as its JSON line, from whichever home it has."""
    stream = stream_for(path, KIND)
    if stream is not None:
        return stream.read()
    if not path.exists():
        return []
    return [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def count(path: Path = TRIALS_PATH) -> int:
    stream = stream_for(path, KIND)
    return stream.count() if stream is not None else len(lines(path))


def now_iso() -> str:
    return datetime.now(UTC).isoformat()
