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

### Attribution is reconciled, not asserted

Per-instrument contribution is computed from the fills — cash out on a buy,
cash in on a sell, less costs — plus the mark-to-market of whatever was still
held at the end. Summed across instruments that should equal the change in
equity. It is not assumed to: the residual is computed and reported. A
reconciliation that silently does not reconcile is worse than none, because it
invites the reader to trust a decomposition that does not add up.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from itertools import pairwise
from pathlib import Path
from typing import Any, Protocol

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


FLAT_RUN_FRACTION = 0.5
"""Above this share of unchanged days, the run is flagged as mostly idle.

Not a stylistic threshold. A Sharpe is a mean over a standard deviation,
annualised by the square root of 252 — arithmetic that assumes the periods are
comparable observations. A series that is exactly flat three days in four is
not that, and its Sharpe is not comparable to one from a fully-invested run.
"""


def _metrics(equity: list[float], days: list[date], costs: float, traded: float) -> dict[str, Any]:
    returns = [b / a - 1.0 for a, b in pairwise(equity) if a > 0]
    stats = sharpe_stats(returns)
    n = len(returns)
    years = n / TRADING_DAYS if n else 0.0
    start, end = (equity[0], equity[-1]) if equity else (0.0, 0.0)
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
    window_days: int,
    equity: list[float],
    days: list[date],
    fills: Sequence[FillLike],
    rejections: Sequence[tuple[str, str, str]],
    marks: dict[str, float],
    starting_cash: float,
) -> dict[str, Any]:
    """Assemble the full report from one engine run.

    `marks` is the last close per symbol inside the run's window, used to value
    positions still open at the end. A symbol missing from it is marked at zero
    and flagged, rather than silently dropped — a dropped position would make
    the attribution reconcile by losing the thing that broke it.
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
    metrics = _metrics(equity, days, costs, traded)

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

    return {
        "strategy_id": strategy_id,
        "configuration": configuration,
        "universe": universe,
        "instruments": instruments,
        "tier": tier,
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
        "rejections": [{"day": d, "symbol": s, "reason": r} for d, s, r in rejections],
        "equity": {
            "days": [day.isoformat() for day in days],
            "values": [round(value, 2) for value in equity],
        },
    }


def _path(workspace: Workspace, strategy_id: str, configuration: str) -> Path:
    return workspace.root / "reports" / strategy_id / f"{configuration}.json"


def save(workspace: Workspace, payload: dict[str, Any]) -> Path:
    path = _path(workspace, str(payload["strategy_id"]), str(payload["configuration"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".partial")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    # Atomic rename, so a crash mid-write leaves no half-report that would read
    # as a real one — the same reason the crypto landing zone writes .partial.
    tmp.replace(path)
    return path


def load(workspace: Workspace, strategy_id: str, configuration: str) -> dict[str, Any] | None:
    path = _path(workspace, strategy_id, configuration)
    if not path.exists():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return loaded if isinstance(loaded, dict) else None
