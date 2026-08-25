"""Where a sweep's results are kept so something other than a terminal can read them.

`make optimize` printed to stdout and nothing else, which meant the only record
of a sweep was whichever scrollback the operator still had open. This writes one
JSON document per run, and keeps the last few, so the terminal UI can show what
the last sweep found without re-running it — re-running being the one thing a
reader must never casually do here, since every candidate spends a permanent
trial.

**Read-only by construction.** Nothing in this module runs a sweep or touches
the trial ledger. A UI that could start a sweep from a button is a UI that can
spend the platform's evidential budget by accident.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SWEEPS_PATH = Path("data/derived/sweeps.jsonl")

KEEP = 20
"""How many past sweeps to retain. Enough to see whether a strategy's numbers
move between runs — which is itself evidence about how stable they are — and
few enough that the file stays readable by eye."""


@dataclass
class Row:
    """One strategy's sweep, flattened for transport."""

    strategy_id: str
    market: str
    symbol: str
    candidates: int
    best_pnl: float
    median_pnl: float
    fills: int
    win_rate: float
    sessions: int
    best_params: dict[str, float] = field(default_factory=dict)
    error: str = ""

    @property
    def spread_ratio(self) -> float:
        """Best over median, the number that says whether a sweep found a tail.

        Guarded rather than raw: a median at or below zero makes the ratio
        meaningless or negative, and a strategy that loses on most of its grid
        should not be able to report an impressive-looking multiple.
        """
        return self.best_pnl / self.median_pnl if self.median_pnl > 0 else 0.0


def record(
    rows: list[Row],
    *,
    trials_before: int,
    trials_after: int,
    required_t: float,
    start: str,
    end: str,
    dry_run: bool,
    skipped: list[str] | None = None,
    path: Path = SWEEPS_PATH,
) -> None:
    """Append one sweep. `dry_run` is stored, not filtered out.

    A dry run and a recorded run produce the same numbers and differ only in
    whether they spent trials, so the flag has to travel with the result —
    a reader who cannot tell them apart might cite a figure the ledger has no
    record of.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "at": datetime.now(UTC).isoformat(),
        "start": start,
        "end": end,
        "dry_run": dry_run,
        "trials_before": trials_before,
        "trials_after": trials_after,
        "required_t": required_t,
        "skipped": skipped or [],
        "rows": [
            {
                "strategy_id": row.strategy_id,
                "market": row.market,
                "symbol": row.symbol,
                "candidates": row.candidates,
                "best_pnl": row.best_pnl,
                "median_pnl": row.median_pnl,
                "fills": row.fills,
                "win_rate": row.win_rate,
                "sessions": row.sessions,
                "best_params": row.best_params,
                "error": row.error,
            }
            for row in rows
        ],
    }

    existing = read_all(path)
    existing.append(document)
    kept = existing[-KEEP:]
    path.write_text(
        "".join(json.dumps(entry, sort_keys=True) + "\n" for entry in kept),
        encoding="utf-8",
    )


def read_all(path: Path = SWEEPS_PATH) -> list[dict[str, Any]]:
    """Every retained sweep, oldest first. A corrupt line is skipped, not fatal."""
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict):
            out.append(entry)
    return out


def latest(path: Path = SWEEPS_PATH) -> dict[str, Any] | None:
    """The most recent sweep, or None if none has run."""
    entries = read_all(path)
    return entries[-1] if entries else None
