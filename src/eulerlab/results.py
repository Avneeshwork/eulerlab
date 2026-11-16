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

from eulerlab.filecache import FileMemo
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
    asset_class: str = "equity"
    """Which panel this ran against. Defaults to equity so rows written before
    crypto and funds were runnable read back correctly rather than as unknown."""

    cost_mode: str = "realistic"
    """`replication` means the run paid no costs, because no cost model covers
    that asset class. Carried per run so a gross-of-costs number can never be
    compared to a net one without the difference being visible."""

    universe: str = "all"
    """Which instruments the run could choose from.

    Part of `configuration`: the same strategy over nifty50 and over the whole
    panel are two different answers, not one answer recomputed. Defaults to
    "all" because that is what every run did before the selector existed —
    `_run_batch` passed the panel unfiltered — so reading an older row as "all"
    is a statement of fact rather than a guess.
    """

    symbols: int = 0
    """How many distinct instruments actually traded.

    Different from the universe size and more informative: a strategy offered
    4,002 names that held 20 of them is the useful fact, and it is the answer to
    "what did this run actually touch".
    """

    params: dict[str, Any] = field(default_factory=dict)
    curve: list[float] = field(default_factory=list)
    """The equity curve, downsampled. An output, so deliberately not part of
    `configuration` — two runs of the same configuration are the same result
    even if a data revision moved the curve."""

    at: str = ""
    superseded: int = 0
    """How many dropped configurations this row stands in for.

    `prune-runs` keeps one stored run per strategy and deletes the rest, which
    would silently shrink the denominator of the selection-bias correction —
    "a Sharpe of 2.19 means one thing as the only run and another as the highest
    of forty". The count is carried here so deleting the rows changes what is on
    disk and not what the statistics believe.

    Deliberately not part of `configuration`: it is bookkeeping about storage,
    not a property of the evaluation, and folding it into the hash would make a
    pruned run look like a different configuration from the same run unpruned.
    """

    trial_recorded: bool = False
    """Whether this run appears in the trial ledger.

    Almost always False: screening in the workbench spends no trial (T-3321).
    Carried per run so a library can say how much of its own evidence the noise
    bar does not know about.
    """

    @property
    def configuration(self) -> str:
        """What makes this a distinct result rather than a repeat.

        Built from **named fields only**, never from the free-form `params`
        dict. Params carried `days` and `universe` as well, duplicating the
        `window_days` and `universe` fields — so the day a `universe` key was
        added to params, every identical re-run started hashing differently and
        counted as a new configuration. That inflated `runs`, which is the
        denominator the whole selection-bias correction rests on: a strategy
        looked more searched-over than it was, and every figure looked less
        well attested than it is.

        `instruments` is the one thing params uniquely holds, so it is lifted
        out by name. Anything else added to params in future changes nothing
        here, which is the point.
        """
        material = json.dumps(
            {
                "strategy": self.strategy_id,
                "tier": self.tier,
                "window": self.window_days,
                "universe": self.universe,
                "asset_class": self.asset_class,
                "data": self.data_version,
                "instruments": sorted(self.params.get("instruments") or []),
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
            "asset_class": self.asset_class,
            "cost_mode": self.cost_mode,
            "window_days": self.window_days,
            "universe": self.universe,
            "symbols": self.symbols,
            "data_version": self.data_version,
            "params": self.params,
            "curve": self.curve,
            "at": self.at or datetime.now(UTC).isoformat(),
            "superseded": self.superseded,
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
    """The strategy's log, parsed once per version of the file (`filecache`).

    The strategy table asked once per row, 261 times per dashboard snapshot,
    and re-parsed every unchanged log each time (2026-10-27). Shared: callers
    read the rows and never change them."""
    return _ROWS(_path(workspace, strategy_id))


def _parse_rows(path: Path) -> list[dict[str, Any]]:
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


_ROWS = FileMemo(_parse_rows)


def drop_duplicates(workspace: Workspace, *, dry_run: bool = True) -> dict[str, tuple[int, int]]:
    """Remove rows that repeat another row in everything but the time written.

    Until 2026-10-12 a batch recorded each result two or three times (T-4050),
    milliseconds apart, and re-running an unchanged backtest adds a row that
    says the same thing again. Of rows identical apart from `at`, the latest
    is kept. Returns `{file name: (rows kept, rows dropped)}` for files that
    had any.

    Nothing the library reports can change. `distinct` already reads one row
    per configuration, the latest, and rows that differ only in `at` share a
    configuration, a result and a `superseded` count. This is not
    `make prune-runs`, which drops whole configurations and their reports.
    """
    outcome: dict[str, tuple[int, int]] = {}
    if not workspace.results.exists():
        return outcome
    for path in sorted(workspace.results.glob("*.jsonl")):
        kept: dict[str, tuple[str, str]] = {}
        total = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue  # a torn line is not a result (see `_read_rows`)
            if not isinstance(row, dict):
                continue
            total += 1
            at = str(row.get("at", ""))
            content = json.dumps({k: v for k, v in row.items() if k != "at"}, sort_keys=True)
            if content not in kept or at >= kept[content][0]:
                kept[content] = (at, line.strip())
        if len(kept) == total:
            continue
        outcome[path.name] = (len(kept), total - len(kept))
        if not dry_run:
            ordered = sorted(kept.values(), key=lambda item: item[0])
            tmp = path.with_suffix(".partial")
            tmp.write_text("".join(f"{line}\n" for _, line in ordered), encoding="utf-8")
            tmp.replace(path)
    return outcome


def _to_run(row: dict[str, Any]) -> Run:
    return Run(
        strategy_id=str(row["strategy_id"]),
        sharpe=float(row["sharpe"]),
        total_return=float(row.get("total_return", 0.0)),
        max_drawdown=float(row.get("max_drawdown", 0.0)),
        fills=int(row.get("fills", 0)),
        days=int(row.get("days", 0)),
        tier=str(row.get("tier", "")),
        asset_class=str(row.get("asset_class", "equity")),
        cost_mode=str(row.get("cost_mode", "realistic")),
        window_days=int(row.get("window_days", 0)),
        # A row written before the selector existed ran on the unfiltered
        # panel, which is exactly what "all" means.
        universe=str(row.get("universe") or "all"),
        symbols=int(row.get("symbols", 0)),
        data_version=str(row.get("data_version", "")),
        params=dict(row.get("params") or {}),
        curve=[float(value) for value in (row.get("curve") or [])],
        at=str(row.get("at", "")),
        superseded=int(row.get("superseded", 0) or 0),
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
        # Recomputed, not read back. The stored value is what the definition
        # said on the day the row was written, and rows written under an older
        # definition would otherwise stay split forever — the log is
        # append-only, so a wrong grouping could never be corrected.
        key = _to_run(row).configuration
        previous = latest.get(key)
        if previous is None or str(row.get("at", "")) >= str(previous.get("at", "")):
            latest[key] = row
    return [_to_run(row) for row in latest.values()]


def best(workspace: Workspace, strategy_id: str, runs: list[Run] | None = None) -> Best | None:
    """The highest Sharpe, and how many configurations it beat.

    Returns None when nothing has been run — which the caller must render as
    "not measured" and never as zero.

    `runs` is `distinct(...)` when the caller already has it, so one question
    about a strategy reads its file once and not once per helper.
    """
    if runs is None:
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
        # Stored rows plus the ones they stand in for. A pruned strategy has one
        # row and the same denominator it had before pruning.
        runs=len(tradeable) + sum(r.superseded for r in tradeable),
        unrecorded=sum(1 for r in tradeable if not r.trial_recorded),
    )


def latest(workspace: Workspace, strategy_id: str, runs: list[Run] | None = None) -> Run | None:
    """The most recent run, whatever it scored.

    This is what the library reports, not `best`. "The last thing I ran" is a
    single measurement; "the best thing I ever ran" is a maximum over N draws,
    and a maximum is a biased estimator of any one of them. Showing the latest
    removes that bias rather than pricing it — the honest direction, and the
    less flattering one.

    Zero-fill runs are excluded on the same grounds as in `best`: a run that
    never traded is not a result, and being the most recent does not make it
    one.
    """
    if runs is None:
        runs = distinct(workspace, strategy_id)
    traded = [run for run in runs if run.fills > 0]
    if not traded:
        return None
    return max(traded, key=lambda r: r.at)


def summary(workspace: Workspace, strategy_id: str) -> dict[str, Any]:
    """What the library shows for one strategy.

    The headline is the **most recent** run, not the best. A maximum over
    several configurations is a biased estimate of any one of them; the latest
    run is just a measurement. Reporting it is the less flattering choice and
    the only one that does not need a correction applied before it means
    anything.

    `runs` still travels with it, because how much searching happened is
    context the number needs either way — and when the best beats the latest,
    the caveat says so rather than letting the better figure disappear.
    """
    stored = distinct(workspace, strategy_id)
    recent = latest(workspace, strategy_id, stored)
    if recent is None:
        return {"sharpe": None, "runs": 0, "caveat": ""}

    top = best(workspace, strategy_id, stored)
    runs = top.runs if top else 1
    unrecorded = top.unrecorded if top else 0

    caveat = ""
    if top is not None and runs > 1:
        caveat = (
            f"The most recent of {runs} configurations, not the best of them. "
            f"The best scored {top.run.sharpe:.2f}"
            + (
                " — shown here is the latest, because a maximum over several attempts "
                "is the score of the luckiest draw rather than of the strategy."
                if top.run.sharpe > recent.sharpe
                else ", which is this run."
            )
        )
    if unrecorded:
        # Agree the verb with the count, and do not say "those runs" when
        # nothing before it named any runs (one run, no "most recent of" line).
        if runs == 1:
            missing = (
                "This run is not in the trial ledger, so the noise bar does not know it happened."
            )
        elif unrecorded == runs:
            missing = (
                f"None of the {runs} runs are in the trial ledger, so the noise bar "
                "does not know that search happened."
            )
        else:
            verb = "is" if unrecorded == 1 else "are"
            missing = (
                f"{unrecorded} of those runs {verb} not in the trial ledger, so the noise "
                "bar does not know that search happened."
            )
        caveat = f"{caveat} {missing}".strip()
    return {
        "sharpe": round(recent.sharpe, 4),
        "total_return": round(recent.total_return, 6),
        "max_drawdown": round(recent.max_drawdown, 6),
        "fills": recent.fills,
        "tier": recent.tier,
        "asset_class": recent.asset_class,
        "cost_mode": recent.cost_mode,
        "window_days": recent.window_days,
        "universe": recent.universe,
        "symbols": recent.symbols,
        "curve": recent.curve,
        "runs": runs,
        "unrecorded": unrecorded,
        "best_sharpe": round(top.run.sharpe, 4) if top else None,
        # False by construction now: the headline is a measurement, not a
        # maximum. Kept so a caller that was reading it does not silently start
        # treating a latest-run figure as a selected one.
        "is_a_maximum": False,
        "at": recent.at,
        "configuration": recent.configuration,
        "caveat": caveat.strip(),
    }
