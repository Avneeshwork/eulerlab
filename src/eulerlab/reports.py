"""The full analysis of one backtest run.

`results.py` keeps a small, readable row per run — the headline figure and its
denominator. This keeps everything else: what each instrument contributed, the
order ledger, and the metrics that do not fit on a library row.

### Why it is a separate file per run

A report holds every fill. One 1,200-day run of `momentum_12_1` on nifty100
produced 1,480 of them. Appending that to the results JSONL would make the file
that answers "what is this strategy's best Sharpe" unreadable and slow to parse,
to carry data almost every read does not want. So reports live at
`reports/{strategy}/{configuration}.json` and are fetched only when opened.

The configuration hash is the same one `results.Run` uses, so a report and the
row that summarises it cannot drift apart or be mismatched.

### Every run is kept, under its own id

`reports/{strategy}/{configuration}.json` is the *latest* run of that
configuration, and it is replaced on a re-run. Before run ids, that replacement
was the only copy, so re-running a configuration destroyed the report it
superseded. Now every save also writes
`reports/{strategy}/runs/{configuration}/{run_id}.json`, which is never
overwritten (the latest file is a hard link to it, not a second copy) — the shape LEAN uses, one result file per backtest id
(`docs/RESEARCH/061-backtest-result-storage.md`). The latest file stays where
it was so every existing reader, and every report written before this, works
unchanged.

Each saved report carries `provenance`: its run id, when it was recorded, the
git commit that produced it (and whether the tree had uncommitted edits), and
the cost-model stamp. A number whose code cannot be named cannot be reproduced.

### Attribution is reconciled, not asserted

Per-instrument contribution is computed from the fills — cash out on a buy,
cash in on a sell, less costs — plus the mark-to-market of whatever was still
held at the end. Summed across instruments that should equal the change in
equity. It is not assumed to: the residual is computed and reported. A
reconciliation that silently does not reconcile is worse than none, because it
invites the reader to trust a decomposition that does not add up.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from functools import lru_cache
from itertools import pairwise
from pathlib import Path
from typing import Any, Protocol

from eulerlab import trades as trade_book
from eulerlab.costs.schedule import Side
from eulerlab.validation.statistics import sharpe_stats
from eulerlab.workspace import Workspace

TRADING_DAYS = 252
RECONCILIATION_TOLERANCE = 1.0
"""Rupees. Below this the decomposition is called exact.

One rupee across a run that moves millions is float noise in the accumulation,
not a modelling error. Anything larger is reported as a residual rather than
absorbed, because an attribution that quietly does not add up is worse than no
attribution.
"""


class FillLike(Protocol):
    """The shape both engines' fills share.

    Tier A and Tier B have separate fill types — Tier B's carries a client
    order id, Tier A's does not — and neither has a common ancestor. This is
    the intersection the report actually needs.

    Declared as properties rather than attributes because both concrete fill
    types are frozen dataclasses: an attribute in a Protocol demands a
    read-write member, which a frozen instance cannot satisfy.
    """

    @property
    def day(self) -> date: ...

    @property
    def symbol(self) -> str: ...

    @property
    def side(self) -> Side: ...

    @property
    def quantity(self) -> int: ...

    @property
    def price(self) -> float: ...

    @property
    def cost(self) -> float: ...


@dataclass
class Constituent:
    """What one instrument did."""

    symbol: str
    fills: int = 0
    bought_qty: int = 0
    sold_qty: int = 0
    bought_value: float = 0.0
    sold_value: float = 0.0
    costs: float = 0.0
    open_qty: int = 0
    mark: float = 0.0
    first_day: str = ""
    last_day: str = ""

    @property
    def open_value(self) -> float:
        """Mark-to-market of whatever was still held when the run ended."""
        return self.open_qty * self.mark

    @property
    def contribution(self) -> float:
        """Rupees this instrument added to, or took from, the account.

        Cash out on a buy, cash in on a sell, less costs, plus the value of the
        position still open at the end.
        """
        return self.sold_value - self.bought_value - self.costs + self.open_value

    @property
    def traded_value(self) -> float:
        return self.bought_value + self.sold_value

    def to_row(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "fills": self.fills,
            "bought_qty": self.bought_qty,
            "sold_qty": self.sold_qty,
            "bought_value": round(self.bought_value, 2),
            "sold_value": round(self.sold_value, 2),
            "costs": round(self.costs, 2),
            "open_qty": self.open_qty,
            "mark": round(self.mark, 2),
            "open_value": round(self.open_value, 2),
            "contribution": round(self.contribution, 2),
            "traded_value": round(self.traded_value, 2),
            "first_day": self.first_day,
            "last_day": self.last_day,
        }


@dataclass
class Report:
    strategy_id: str
    configuration: str
    payload: dict[str, Any] = field(default_factory=dict)


def _drawdown_detail(equity: list[float], days: list[date]) -> dict[str, Any]:
    """Worst peak-to-trough fall, and when it happened.

    The dates matter more than the number. "Down 30%" is a statistic; "down 30%
    between March 2020 and May 2020" is something a person can reason about.
    """
    if not equity:
        return {"depth": 0.0, "peak_day": None, "trough_day": None, "recovered_day": None}
    peak = equity[0]
    peak_index = 0
    worst = 0.0
    worst_peak = worst_trough = 0
    for index, value in enumerate(equity):
        if value > peak:
            peak, peak_index = value, index
        fall = value / peak - 1.0 if peak > 0 else 0.0
        if fall < worst:
            worst, worst_peak, worst_trough = fall, peak_index, index

    recovered: int | None = None
    if worst < 0:
        target = equity[worst_peak]
        for index in range(worst_trough, len(equity)):
            if equity[index] >= target:
                recovered = index
                break

    def day_at(index: int | None) -> str | None:
        if index is None or index >= len(days):
            return None
        return days[index].isoformat()

    return {
        "depth": round(worst, 6),
        "peak_day": day_at(worst_peak),
        "trough_day": day_at(worst_trough),
        "recovered_day": day_at(recovered),
        "still_underwater": worst < 0 and recovered is None,
    }


CASH_LIKE_VOLATILITY = 0.02
"""Annualised volatility below which a high Sharpe says nothing about skill.

A Sharpe is return over volatility. Divide a modest return by a near-zero
denominator and it goes to the moon without the strategy doing anything: a
momentum rule over Indian mutual funds returned 4.9% a year at 0.73% volatility
for a Sharpe of 6.49, which is a statement that liquid and debt funds have
smooth NAVs, not that the rule works.

2% is where Indian liquid funds sit (roughly 0.5-1%) with room above them, so
anything under it is cash-like by construction rather than by judgement.
"""

HIGH_TURNOVER = 5.0
"""Portfolio turns over its own capital this many times, or more.

Only reported when no cost model covers the asset class: at 27x turnover a
result gross of costs is not a slightly optimistic estimate, it is a different
number.
"""

FLAT_RUN_FRACTION = 0.5
"""Above this share of unchanged days, the run is flagged as mostly idle.

Not a stylistic threshold. A Sharpe is a mean over a standard deviation,
annualised by the square root of 252 — arithmetic that assumes the periods are
comparable observations. A series that is exactly flat three days in four is
not that, and its Sharpe is not comparable to one from a fully-invested run.
"""


def _metrics(
    equity: list[float],
    days: list[date],
    costs: float,
    traded: float,
    *,
    starting_cash: float | None = None,
) -> dict[str, Any]:
    returns = [b / a - 1.0 for a, b in pairwise(equity) if a > 0]
    stats = sharpe_stats(returns)
    n = len(returns)
    years = n / TRADING_DAYS if n else 0.0
    start, end = (equity[0], equity[-1]) if equity else (0.0, 0.0)
    # From the money the run started with, not the first day's close: that
    # close is already net of the first day's costs, so measuring from it read
    # 58.87% beside a rupee gain of 58.77% (T-4345).
    if starting_cash is not None and starting_cash > 0:
        start = starting_cash
    total = end / start - 1.0 if start > 0 else 0.0
    mean = sum(returns) / n if n else 0.0
    variance = sum((r - mean) ** 2 for r in returns) / (n - 1) if n > 2 else 0.0

    # How much of the run was actually invested. A run that held cash cannot be
    # compared to one that did not, and the Sharpe alone will not say so.
    flat = sum(1 for r in returns if r == 0.0)
    invested = 1.0 - (flat / n) if n else 0.0
    first_move: str | None = None
    for index, value in enumerate(equity):
        if index and value != equity[index - 1] and index < len(days):
            first_move = days[index].isoformat()
            break

    gains = [r for r in returns if r > 0]
    losses = [r for r in returns if r < 0]
    downside = [r for r in returns if r < 0]
    downside_var = sum(r * r for r in downside) / len(downside) if downside else 0.0

    return {
        "sharpe": round(stats.sharpe, 4),
        # Sortino punishes only downside deviation. Reported beside Sharpe
        # because a strategy that is volatile upward is not the same risk as one
        # that is volatile downward, and Sharpe cannot tell them apart.
        "sortino": round(mean * TRADING_DAYS / ((downside_var * TRADING_DAYS) ** 0.5), 4)
        if downside_var > 0
        else None,
        "total_return": round(total, 6),
        "annualised": round((end / start) ** (1 / years) - 1.0, 6)
        if years > 0 and start > 0 and end > 0
        else None,
        "volatility": round((variance * TRADING_DAYS) ** 0.5, 6),
        "trading_days": n,
        "years": round(years, 2),
        "flat_days": flat,
        "invested_fraction": round(invested, 4),
        "first_move_day": first_move,
        # Over the days it was actually invested. The plain hit rate counts
        # flat days as misses, which flatters nothing but explains nothing:
        # 13.9% reads as a broken strategy when the truth is that it held cash.
        "hit_rate": round(len(gains) / n, 4) if n else None,
        "hit_rate_invested": round(len(gains) / (n - flat), 4) if n - flat > 0 else None,
        "best_day": round(max(returns), 6) if returns else None,
        "worst_day": round(min(returns), 6) if returns else None,
        "average_gain": round(sum(gains) / len(gains), 6) if gains else None,
        "average_loss": round(sum(losses) / len(losses), 6) if losses else None,
        "skew": round(stats.skew, 4),
        "kurtosis": round(stats.kurtosis, 4),
        "costs": round(costs, 2),
        "traded_value": round(traded, 2),
        # What the costs ate. A strategy whose gross return is good and whose
        # net return is not has a turnover problem, and the two numbers side by
        # side are the only way to see that.
        "cost_drag": round(costs / start, 6) if start > 0 else None,
        "turnover_x": round(traded / start, 2) if start > 0 else None,
        "drawdown": _drawdown_detail(equity, days),
    }


def build(
    *,
    strategy_id: str,
    configuration: str,
    universe: str,
    instruments: list[str],
    tier: str,
    asset_class: str = "equity",
    cost_mode: str = "realistic",
    window_days: int,
    benchmark: dict[str, Any] | None = None,
    data_window: list[str] | None = None,
    sessions_seen: int = 0,
    requested_days: int = 0,
    equity: list[float],
    days: list[date],
    fills: Sequence[FillLike],
    rejections: Sequence[tuple[str, str, str]],
    marks: dict[str, float],
    starting_cash: float,
    closes: Mapping[str, Mapping[date, float]] | None = None,
    params: dict[str, Any] | None = None,
    data_version: str = "",
) -> dict[str, Any]:
    """Assemble the full report from one engine run.

    `marks` is the last close per symbol inside the run's window, used to value
    positions still open at the end. A symbol missing from it is marked at zero
    and flagged, rather than silently dropped — a dropped position would make
    the attribution reconcile by losing the thing that broke it.

    `closes` is the price series the engine marked at, per symbol. Given, each
    closed trade carries its MAE and MFE; absent, those are None.
    """
    per_symbol: dict[str, Constituent] = defaultdict(lambda: Constituent(symbol=""))
    unmarked: list[str] = []

    for fill in fills:
        entry = per_symbol[fill.symbol]
        entry.symbol = fill.symbol
        entry.fills += 1
        entry.costs += fill.cost
        value = fill.price * fill.quantity
        if fill.side is Side.BUY:
            entry.bought_qty += fill.quantity
            entry.bought_value += value
            entry.open_qty += fill.quantity
        else:
            entry.sold_qty += fill.quantity
            entry.sold_value += value
            entry.open_qty -= fill.quantity
        stamp = fill.day.isoformat()
        entry.first_day = min(entry.first_day, stamp) if entry.first_day else stamp
        entry.last_day = max(entry.last_day, stamp)

    for entry in per_symbol.values():
        if entry.open_qty == 0:
            continue
        if entry.symbol in marks:
            entry.mark = marks[entry.symbol]
        else:
            unmarked.append(entry.symbol)

    constituents = sorted(per_symbol.values(), key=lambda c: c.contribution, reverse=True)
    attributed = sum(c.contribution for c in constituents)
    equity_change = (equity[-1] - starting_cash) if equity else 0.0
    residual = equity_change - attributed

    traded = sum(c.traded_value for c in constituents)
    costs = sum(c.costs for c in constituents)
    metrics = _metrics(equity, days, costs, traded, starting_cash=starting_cash)

    warnings: list[str] = []
    invested = float(metrics["invested_fraction"] or 0.0)
    if invested < FLAT_RUN_FRACTION:
        warnings.append(
            f"The account was unchanged on {metrics['flat_days']} of "
            f"{metrics['trading_days']} days — it held nothing for most of this run, "
            f"first moving on {metrics['first_move_day']}. A Sharpe over a mostly-flat "
            f"series is not comparable to one from a fully-invested run. The usual cause "
            f"is the strategy's min_names threshold being at or above the size of the "
            f"universe, so a single instrument short of history blocks every trade."
        )
    if not constituents:
        warnings.append("No instrument traded. There is nothing to attribute.")

    volatility = float(metrics["volatility"] or 0.0)
    sharpe = float(metrics["sharpe"] or 0.0)
    if 0.0 < volatility < CASH_LIKE_VOLATILITY and sharpe > 1.0:
        warnings.append(
            f"Volatility is {volatility * 100:.2f}% a year — cash-like. A Sharpe of "
            f"{sharpe:.2f} on an annualised return of "
            f"{float(metrics['annualised'] or 0.0) * 100:.1f}% is arithmetic about a "
            f"near-zero denominator, not evidence of skill. Compare this against other "
            f"cash-like instruments, never against an equity strategy."
        )

    turnover = float(metrics["turnover_x"] or 0.0)
    if cost_mode != "realistic":
        note = (
            f"No cost model covers {asset_class}, so this run paid nothing to trade and "
            f"the result is an upper bound rather than a net figure."
        )
        if turnover >= HIGH_TURNOVER:
            note += (
                f" It turned over its capital {turnover:.0f} times; at that rate the "
                f"omitted costs are not a rounding error."
            )
        warnings.append(note)

    book = trade_book.round_trips(fills, closes)
    return {
        "strategy_id": strategy_id,
        "configuration": configuration,
        # What the scan *saw*, beside what it traded. A run that fetched more
        # leading history is a different measurement even when the traded window
        # and the fill count match exactly.
        # Holding the instrument over the same sessions. None where the run
        # touched more than one name — a basket is a different and larger claim
        # than "holding this one thing".
        "benchmark": benchmark,
        "data_window": data_window or [],
        "sessions_seen": sessions_seen,
        "requested_days": requested_days,
        "universe": universe,
        "instruments": instruments,
        "tier": tier,
        "asset_class": asset_class,
        "cost_mode": cost_mode,
        "window_days": window_days,
        "period": [days[0].isoformat(), days[-1].isoformat()] if days else [None, None],
        "starting_cash": starting_cash,
        "final_equity": round(equity[-1], 2) if equity else starting_cash,
        "metrics": metrics,
        "warnings": warnings,
        "constituents": [c.to_row() for c in constituents],
        "reconciliation": {
            "equity_change": round(equity_change, 2),
            "attributed": round(attributed, 2),
            "residual": round(residual, 2),
            # Stated rather than assumed. If this is False the decomposition
            # below does not add up to the result above it, and the reader needs
            # to know that before drawing any conclusion from it.
            "exact": abs(residual) < RECONCILIATION_TOLERANCE,
            "unmarked_symbols": sorted(set(unmarked)),
        },
        "orders": [
            {
                "day": fill.day.isoformat(),
                "symbol": fill.symbol,
                "side": str(fill.side),
                "quantity": fill.quantity,
                "price": round(fill.price, 2),
                "notional": round(fill.price * fill.quantity, 2),
                "cost": round(fill.cost, 2),
                "client_order_id": getattr(fill, "client_order_id", ""),
            }
            for fill in fills
        ],
        "trades": book,
        "trade_summary": trade_book.summary(book),
        "params": params or {},
        "data_version": data_version,
        "rejections": [{"day": d, "symbol": s, "reason": r} for d, s, r in rejections],
        "equity": {
            "days": [day.isoformat() for day in days],
            "values": [round(value, 2) for value in equity],
        },
    }


def _path(workspace: Workspace, strategy_id: str, configuration: str) -> Path:
    return workspace.root / "reports" / strategy_id / f"{configuration}.json"


def _run_path(workspace: Workspace, strategy_id: str, configuration: str, run_id: str) -> Path:
    return workspace.root / "reports" / strategy_id / "runs" / configuration / f"{run_id}.json"


REPO_ROOT = Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def code_version() -> dict[str, Any]:
    """The commit this process is running, and whether the tree was edited.

    Cached per process: `make workbench` runs the API with `--reload`, which
    restarts it on any source change, so a stale answer cannot outlive the
    code it describes. Uncommitted paths are listed, capped, because "dirty"
    alone does not say whether the edit could have moved the number.
    """

    def git(*args: str) -> str:
        # Trailing newline only: porcelain lines start with a status column
        # that may be a space, and stripping it would eat a path's first letter.
        return subprocess.run(
            ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, timeout=5, check=True
        ).stdout.rstrip("\n")

    try:
        commit = git("rev-parse", "HEAD")
        dirty = git("status", "--porcelain", "--untracked-files=no").splitlines()
    except (OSError, subprocess.SubprocessError):
        return {"commit": "unknown", "dirty": None, "dirty_paths": []}
    return {
        "commit": commit,
        "dirty": bool(dirty),
        "dirty_paths": [line[3:] for line in dirty[:20]],
    }


def _provenance(payload: dict[str, Any]) -> dict[str, Any]:
    from eulerlab.batch import cost_model_version

    now = datetime.now(UTC)
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:8]
    return {
        # Time first so ids sort in the order the runs happened; the digest
        # separates two saves inside the same microsecond.
        "run_id": f"{now.strftime('%Y%m%dT%H%M%S%fZ')}-{digest}",
        "recorded_at": now.isoformat(),
        "code": code_version(),
        "cost_model": cost_model_version(),
    }


def _write(path: Path, payload: dict[str, Any], *, exclusive: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if exclusive and path.exists():
        raise FileExistsError(f"{path} already exists; a stored run is never overwritten")
    tmp = path.with_suffix(".partial")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    # Atomic rename, so a crash mid-write leaves no half-report that would read
    # as a real one — the same reason the crypto landing zone writes .partial.
    tmp.replace(path)


def save(workspace: Workspace, payload: dict[str, Any]) -> Path:
    """Store one run: its own permanent file, then the configuration's latest.

    Returns the permanent file. The run is written first, so a crash between
    the two writes leaves a run on record and the previous latest in place,
    never a latest that points at nothing.
    """
    strategy_id = str(payload["strategy_id"])
    configuration = str(payload["configuration"])
    if "provenance" not in payload:
        payload = {**payload, "provenance": _provenance(payload)}
    run_id = str(payload["provenance"]["run_id"])
    permanent = _run_path(workspace, strategy_id, configuration, run_id)
    _write(permanent, payload, exclusive=True)
    _link_latest(permanent, _path(workspace, strategy_id, configuration), payload)
    return permanent


def _link_latest(permanent: Path, latest: Path, payload: dict[str, Any]) -> None:
    """Point the latest file at the run just written, without a second copy.

    A hard link, swapped in by atomic rename: the latest name now shares the
    run's bytes, and a later re-run replaces the *name*, never the bytes, so the
    stored run is untouched. Writing a full copy here doubled the reports
    folder (342 MB of 986 MB on 2026-11-09, ADR-161). Where a link cannot be
    made (another filesystem), it falls back to the copy.
    """
    tmp = latest.with_suffix(".partial")
    tmp.unlink(missing_ok=True)
    try:
        os.link(permanent, tmp)
    except OSError:
        _write(latest, payload)
        return
    tmp.replace(latest)


def load(
    workspace: Workspace, strategy_id: str, configuration: str, run_id: str = ""
) -> dict[str, Any] | None:
    """The latest run of a configuration, or one named run of it.

    The names arrive from a query string and become a path, so anything that
    could step outside the reports folder is refused rather than resolved.
    """
    if not all(_safe_name(name) for name in (strategy_id, configuration, run_id or "x")):
        return None
    path = (
        _run_path(workspace, strategy_id, configuration, run_id)
        if run_id
        else _path(workspace, strategy_id, configuration)
    )
    if not path.exists():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return loaded if isinstance(loaded, dict) else None


def _safe_name(name: str) -> bool:
    return bool(name) and not name.startswith(".") and "/" not in name and "\\" not in name


def history(workspace: Workspace, strategy_id: str, configuration: str) -> list[dict[str, Any]]:
    """Every stored run of one configuration, oldest first.

    Read from the provenance in each file, not the file name, so what is listed
    is what the run says about itself. A report written before run ids has no
    entry here; it exists only as the latest file.
    """
    if not (_safe_name(strategy_id) and _safe_name(configuration)):
        return []
    folder = workspace.root / "reports" / strategy_id / "runs" / configuration
    if not folder.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(folder.glob("*.json")):
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        provenance = loaded.get("provenance") if isinstance(loaded, dict) else None
        if not isinstance(provenance, dict):
            continue
        metrics = loaded.get("metrics") or {}
        out.append(
            {
                "run_id": provenance.get("run_id", path.stem),
                "recorded_at": provenance.get("recorded_at"),
                "commit": (provenance.get("code") or {}).get("commit"),
                "dirty": (provenance.get("code") or {}).get("dirty"),
                "sharpe": metrics.get("sharpe"),
                "final_equity": loaded.get("final_equity"),
            }
        )
    return out


_HEADLINE_CACHE: dict[tuple[str, int], dict[str, Any]] = {}


def headline(workspace: Workspace, strategy_id: str, configuration: str) -> dict[str, Any]:
    """The few report figures a list of strategies shows: trades, win rate,
    the period traded and the annual return. Cached by the file's modification time, because a
    report can be 600 KB and the list reads one per strategy on every load."""
    if not all(_safe_name(name) for name in (strategy_id, configuration)):
        return {}
    path = _path(workspace, strategy_id, configuration)
    if not path.exists():
        return {}
    key = (str(path), path.stat().st_mtime_ns)
    if key not in _HEADLINE_CACHE:
        payload = load(workspace, strategy_id, configuration) or {}
        summary = payload.get("trade_summary") or {}
        _HEADLINE_CACHE[key] = {
            "trades": summary.get("closed"),
            "win_rate": summary.get("win_rate"),
            "period": payload.get("period") or [None, None],
            # The report's own CAGR, so the Strategies list and the report
            # show one annual return, not two (T-4345).
            "annualised": (payload.get("metrics") or {}).get("annualised"),
        }
    return _HEADLINE_CACHE[key]
