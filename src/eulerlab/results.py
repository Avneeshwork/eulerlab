"""Persisted backtest results, per workspace.

The library currently shows "not measured" against almost every strategy, which
is true and useless: results are computed and thrown away. This keeps them.

### Why every run is kept, not just the best one

The obvious design is one row per strategy holding its best result. That single
choice would quietly make this system into the thing it was built to prevent.

**Max-of-N is a biased estimator.** Run one strategy under twenty
configurations, keep the highest Sharpe, and the number you kept is not an
estimate of the strategy's performance — it is an estimate of the performance of
*the luckiest of twenty draws*. `ARCHITECTURE.md` §1 opens with exactly this,
and the entire deflated-Sharpe apparatus exists to correct for it. Storing only
the maximum discards the one fact needed to make the correction: **how many
attempts it was the maximum of.**

So the store is append-only and `best()` returns a `Best` that carries `runs`
alongside the number. A caller cannot obtain the best result without also
obtaining how many it beat — not by discipline, but because they arrive in the
same object.

### What is a different result rather than a repeat

A run is keyed by the strategy *and* the configuration that produced it: the
window, the tier, the data version, and the parameters. Two runs over different
windows are two results. Two runs over the same everything are one result
recomputed, and the later supersedes the earlier rather than adding to the
count — otherwise re-running the same backtest would inflate `runs` and make the
bias correction *stronger* than the search justifies.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from eulerlab.workspace import Workspace

CURVE_POINTS = 64
"""How many points of the equity curve a stored result keeps.

Enough for a sparkline to be truthful about shape, drawdown and where the
losses fell; far short of the several hundred a run produces. The alternative
was to store no curve and let the interface draw something from the Sharpe,
which would be an invented picture of a real run.
"""


def downsample(equity: list[float], points: int = CURVE_POINTS) -> list[float]:
    """Evenly-spaced samples, always including the first and last.

    The endpoints matter more than the interior: the last point is the total
    return the summary reports, and a curve whose end disagreed with the
    headline number would be worse than no curve.
    """
    if len(equity) <= points:
        return [round(value, 2) for value in equity]
    step = (len(equity) - 1) / (points - 1)
    picked = [equity[round(index * step)] for index in range(points)]
    picked[-1] = equity[-1]
    return [round(value, 2) for value in picked]


@dataclass(frozen=True)
class Run:
    """One evaluation of one configuration."""

    strategy_id: str
    sharpe: float
    total_return: float
    max_drawdown: float
    fills: int
    days: int
    tier: str
    window_days: int
    data_version: str
    params: dict[str, Any] = field(default_factory=dict)
    curve: list[float] = field(default_factory=list)
    """The equity curve, downsampled. An output, so deliberately not part of
    `configuration` — two runs of the same configuration are the same result
    even if a data revision moved the curve."""

    at: str = ""
    trial_recorded: bool = False
    """Whether this run appears in the trial ledger.

    Almost always False: screening in the workbench spends no trial (T-3321).
    Carried per run so a library can say how much of its own evidence the noise
    bar does not know about.
    """

    @property
    def configuration(self) -> str:
        """What makes this a distinct result rather than a repeat."""
        material = json.dumps(
            {
                "strategy": self.strategy_id,
                "tier": self.tier,
                "window": self.window_days,
                "data": self.data_version,
                "params": self.params,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(material.encode()).hexdigest()[:16]

    def to_row(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "sharpe": self.sharpe,
            "total_return": self.total_return,
            "max_drawdown": self.max_drawdown,
            "fills": self.fills,
            "days": self.days,
            "tier": self.tier,
            "window_days": self.window_days,
            "data_version": self.data_version,
            "params": self.params,
            "curve": self.curve,
            "at": self.at or datetime.now(UTC).isoformat(),
            "trial_recorded": self.trial_recorded,
            "configuration": self.configuration,
        }


@dataclass(frozen=True)
class Best:
    """The best result, and what it was the best *of*.

    These two fields travel together on purpose. A Sharpe of 2.19 means one
    thing as the only run and another as the highest of forty, and a caller
    that could take the first without the second would report the second as
    though it were the first.
    """

    run: Run
    runs: int
    """Distinct configurations evaluated. The denominator of the bias."""

    unrecorded: int
    """How many of those the trial ledger does not know about."""

    @property
    def is_a_maximum(self) -> bool:
        """True when this number is a max-of-N rather than a measurement.

        One run is a measurement. More than one and the reported figure is the
        winner of a search, which is a different kind of claim.
        """
        return self.runs > 1


def _path(workspace: Workspace, strategy_id: str) -> Path:
    return workspace.results / f"{strategy_id}.jsonl"


def record(workspace: Workspace, run: Run) -> Path:
    """Append one run. Never rewrites history."""
    path = _path(workspace, run.strategy_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(run.to_row(), sort_keys=True) + "\n")
    return path


def _read_rows(workspace: Workspace, strategy_id: str) -> list[dict[str, Any]]:
    path = _path(workspace, strategy_id)
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            # A torn final line is a crash mid-write; a result that never
            # finished being written is not a result.
            continue
    return out


def _to_run(row: dict[str, Any]) -> Run:
    return Run(
        strategy_id=str(row["strategy_id"]),
        sharpe=float(row["sharpe"]),
        total_return=float(row.get("total_return", 0.0)),
        max_drawdown=float(row.get("max_drawdown", 0.0)),
        fills=int(row.get("fills", 0)),
        days=int(row.get("days", 0)),
        tier=str(row.get("tier", "")),
        window_days=int(row.get("window_days", 0)),
        data_version=str(row.get("data_version", "")),
        params=dict(row.get("params") or {}),
        curve=[float(value) for value in (row.get("curve") or [])],
        at=str(row.get("at", "")),
        trial_recorded=bool(row.get("trial_recorded", False)),
    )


def distinct(workspace: Workspace, strategy_id: str) -> list[Run]:
    """One run per configuration, the latest of each.

    Re-running an identical backtest supersedes rather than accumulates. If it
    accumulated, running the same thing ten times would report ten
    configurations and make the bias correction stronger than the search
    justifies — punishing a re-run as though it were a new idea.
    """
    latest: dict[str, dict[str, Any]] = {}
    for row in _read_rows(workspace, strategy_id):
        key = str(row.get("configuration", ""))
        previous = latest.get(key)
        if previous is None or str(row.get("at", "")) >= str(previous.get("at", "")):
            latest[key] = row
    return [_to_run(row) for row in latest.values()]


def best(workspace: Workspace, strategy_id: str) -> Best | None:
    """The highest Sharpe, and how many configurations it beat.

    Returns None when nothing has been run — which the caller must render as
    "not measured" and never as zero.
    """
    runs = distinct(workspace, strategy_id)
    if not runs:
        return None
    # A run that never traded is not a result of zero. It is a run that did not
    # happen, and letting it win a max would be absurd; letting it lose one is
    # equally wrong, so it is excluded from the comparison entirely.
    tradeable = [r for r in runs if r.fills > 0]
    if not tradeable:
        return None
    # Ties are broken by recency, not by whatever order the dict happened to
    # produce. Two configurations scoring identically are equally good results,
    # so an arbitrary winner is not wrong on the number — but it is wrong on
    # everything travelling with it. A tier A and a tier B run of one strategy
    # scored the same 0.3324 and the arbitrary winner was the older one, which
    # predated stored curves, so the library drew no graph for a strategy that
    # had one.
    top = max(tradeable, key=lambda r: (r.sharpe, r.at))
    return Best(
        run=top,
        runs=len(tradeable),
        unrecorded=sum(1 for r in tradeable if not r.trial_recorded),
    )


def latest(workspace: Workspace, strategy_id: str) -> Run | None:
    """The most recent run, whatever it scored.

    Offered alongside `best` because "the last thing I ran" is a different and
    often more honest question than "the best thing I ever ran".
    """
    runs = distinct(workspace, strategy_id)
    if not runs:
        return None
    return max(runs, key=lambda r: r.at)


def summary(workspace: Workspace, strategy_id: str) -> dict[str, Any]:
    """What the library shows for one strategy.

    `caveat` is populated whenever the headline figure is a maximum, and it is
    part of the payload rather than the page — a result without its caveat is
    the worst artefact this project can produce.
    """
    top = best(workspace, strategy_id)
    if top is None:
        return {"sharpe": None, "runs": 0, "caveat": ""}

    caveat = ""
    if top.is_a_maximum:
        caveat = (
            f"Best of {top.runs} configurations. A maximum over several attempts is a "
            f"biased estimate of any one of them — it is the score of the luckiest draw, "
            f"not of the strategy."
        )
    if top.unrecorded:
        caveat += (
            f" {top.unrecorded} of those runs are not in the trial ledger, so the noise "
            f"bar does not know that search happened."
        )
    return {
        "sharpe": round(top.run.sharpe, 4),
        "total_return": round(top.run.total_return, 6),
        "max_drawdown": round(top.run.max_drawdown, 6),
        "fills": top.run.fills,
        "tier": top.run.tier,
        "window_days": top.run.window_days,
        "curve": top.run.curve,
        "runs": top.runs,
        "unrecorded": top.unrecorded,
        "is_a_maximum": top.is_a_maximum,
        "at": top.run.at,
        "caveat": caveat.strip(),
    }
