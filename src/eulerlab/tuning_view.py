"""What the Optimisation tab shows: a recorded parameter sweep, read back.

Read-only. A sweep is started from `make tune-sharpe-momentum`, never from a
page, for the reason `/api/optimize` gives: every setting tried is a selection,
and that is not a thing to put behind a button.

The summary (`research/tune_sharpe_momentum.py`) already holds the table and
the overfitting checks. This adds the equity curves of the chosen and the
paper setting, and the Nifty over the same days, sampled weekly so the page
receives a few hundred points rather than 2,646 per line.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from eulerlab.paths import data_path

SWEEPS = data_path("derived/sweeps")
SAMPLE_EVERY = 5


def _curve(days: list[str], equity: list[float]) -> list[tuple[str, float]]:
    """Growth of 1, every fifth session, always ending on the last."""
    if not equity:
        return []
    base = equity[0]
    picks = list(range(0, len(equity), SAMPLE_EVERY))
    if picks[-1] != len(equity) - 1:
        picks.append(len(equity) - 1)
    return [(days[i], round(equity[i] / base, 4)) for i in picks]


def _runs(path: Path, keys: set[str]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            # The key leads each line, so a run not wanted is skipped unparsed.
            head = line[:60]
            if any(f'"key": "{k}"' in head for k in keys):
                record = json.loads(line)
                out[record["key"]] = record
    return out


def tuning(strategy_id: str, root: Path = SWEEPS) -> dict[str, Any] | None:
    """The recorded sweep for one strategy, or None when none was run."""
    folder = root / strategy_id
    summary_path = folder / "summary.json"
    if not summary_path.exists():
        return None
    summary: dict[str, Any] = json.loads(summary_path.read_text(encoding="utf-8"))
    chosen = summary["chosen"]["setting"]
    paper = (summary.get("paper") or {}).get("setting")
    wanted = {chosen, *([paper] if paper else [])}
    runs = _runs(folder / "runs.jsonl", wanted) if (folder / "runs.jsonl").exists() else {}

    curves: dict[str, list[tuple[str, float]]] = {}
    for label, key in (("chosen", chosen), ("paper", paper)):
        if key and key in runs:
            curves[label] = _curve(runs[key]["days"], runs[key]["equity"])
    if "chosen" in curves:
        from eulerlab.benchmark import _nifty_closes

        days = {d for d, _ in curves["chosen"]}
        first = date.fromisoformat(curves["chosen"][0][0])
        nifty = [(d, v) for d, v in _nifty_closes() if d >= first]
        if nifty:
            base = nifty[0][1]
            curves["nifty"] = [
                (d.isoformat(), round(v / base, 4)) for d, v in nifty if d.isoformat() in days
            ]
    return {**summary, "curves": curves}
