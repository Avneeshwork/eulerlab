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
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from eulerlab.paths import data_path

TRIALS_PATH = data_path("derived/trials.jsonl")


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
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(asdict(trial), sort_keys=True) + "\n")
    return count(path)


def count(path: Path = TRIALS_PATH) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def now_iso() -> str:
    return datetime.now(UTC).isoformat()
