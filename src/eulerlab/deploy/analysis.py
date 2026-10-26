"""A paper or live deployment's full report, in the backtest report's shape.

The backtest report page (`web/components/terminal/BacktestReport.tsx`) reads
one payload from `reports.build`: the equity curve, every fill, the rejections
and the closing marks. A deployment's stored state holds the same things, so it
is put through the same builder and the page shows paper and live trading with
the same tabs, the same metrics and the same trade book as a backtest.

Two differences, both about money moved in or out:

- **The curve is time-weighted.** A deployment can take deposits and
  withdrawals; a backtest never does. The metrics, the drawdown and the
  calendar are read from equity with those flows taken out (`risk.book.growth`),
  scaled to the starting capital, so ₹1 L added is not a 100% month.
- **Rupees are real.** What the deployment made is its equity less the money put
  in, shown beside the curve, and the reconciliation checks the fills against
  that, not against the time-weighted curve.

Beside it, the strategy's longest stored backtest, so each metric can be read
against what was tested.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from eulerlab import reports
from eulerlab.costs.schedule import Side
from eulerlab.deploy import deployments as store
from eulerlab.deploy import overnight
from eulerlab.risk import book as rb

COMPARED = (
    "total_return",
    "annualised",
    "sharpe",
    "sortino",
    "volatility",
    "hit_rate",
    "best_day",
    "worst_day",
    "cost_drag",
    "turnover_x",
)
"""The metrics shown side by side with the backtest's."""


@dataclass(frozen=True)
class _Fill:
    day: date
    symbol: str
    side: Side
    quantity: int
    price: float
    cost: float


def _fills(rows: list[dict[str, Any]]) -> list[_Fill]:
    return [
        _Fill(
            day=date.fromisoformat(str(row["day"])),
            symbol=str(row["symbol"]),
            side=Side(str(row["side"]).lower()),
            quantity=int(row["quantity"]),
            price=float(row["price"]),
            cost=float(row.get("cost") or 0.0),
        )
        for row in rows
    ]


def build(
    deployment: store.Deployment,
    state: dict[str, Any] | None,
    fills: list[dict[str, Any]] | None,
    backtest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """{"ok": True, "report": ...} or {"ok": False, "error": ...}."""
    if not state or not state.get("curve"):
        reason = (state or {}).get("reason") or "it has not traded a day yet"
        return {"ok": False, "error": f"Nothing to analyse: {reason}"}

    book = rb.book_from_state(
        deployment.id, deployment.strategy_id, "", deployment.capital, deployment.status, state
    )
    days = [day for day, _ in book.curve]
    weighted = [deployment.capital * index for _, index in book.growth()]
    if deployment.start < days[0]:
        # The decision day, at the capital, so the first session's fills, costs
        # and slippage count; otherwise the return starts after them.
        days.insert(0, deployment.start)
        weighted.insert(0, deployment.capital)

    warnings: list[str] = []
    rows = fills
    if rows is None:
        rows = list(state.get("fills") or [])
        total = int(state.get("fills_total") or len(rows))
        if total > len(rows):
            warnings.append(
                f"Only the last {len(rows)} of {total} fills are stored for this run, so "
                "the trades and instruments tabs are incomplete until the next daily run "
                "writes them all."
            )
    marks = {
        str(row["symbol"]): float(row["last_price"])
        for row in state.get("book") or []
        if row.get("symbol") and row.get("last_price") is not None
    }
    futures = deployment.strategy_id in overnight.STRATEGIES
    payload = reports.build(
        strategy_id=deployment.strategy_id,
        configuration=deployment.id,
        universe="Nifty future" if futures else "the strategy's universe",
        instruments=sorted({str(row["symbol"]) for row in rows}),
        tier=deployment.mode,
        # An intraday book names its market: US and crypto are counted in dollars.
        asset_class="index_futures"
        if futures
        else str((state.get("instrument") or {}).get("market") or "equity"),
        window_days=len(days),
        equity=weighted,
        days=days,
        fills=_fills(rows),
        rejections=[
            (str(r.get("day", "")), str(r.get("symbol", "")), str(r.get("reason", "")))
            for r in state.get("rejections") or []
        ],
        marks=marks,
        starting_cash=deployment.capital,
    )

    # The fills explain rupees made, not the time-weighted curve: reconcile
    # against equity less the money put in.
    rec = payload["reconciliation"]
    residual = book.made - float(rec["attributed"])
    rec.update(
        equity_change=round(book.made, 2),
        residual=round(residual, 2),
        exact=abs(residual) < reports.RECONCILIATION_TOLERANCE,
    )
    if futures and any(int(row.get("quantity") or 0) for row in state.get("book") or []):
        warnings.append(
            "A future is open tonight. The instruments tab values it at its notional, "
            "not at its gain since the fill, so the attribution does not add up until "
            "it is sold at the next open."
        )
    if book.flows:
        warnings.append(
            "Money was added or withdrawn, so the curve, returns and drawdown here are "
            "time-weighted: what the starting capital alone would show. Rupees made are "
            "in the money line above."
        )
    payload["warnings"] = warnings + payload["warnings"]
    payload["deployment"] = {
        "id": deployment.id,
        "mode": deployment.mode,
        "status": deployment.status,
        "status_reason": deployment.status_reason,
        "start": deployment.start.isoformat(),
        "starting_capital": deployment.capital,
        "put_in": round(book.deployed, 2),
        "equity": round(book.equity, 2),
        "made": round(book.made, 2),
        "time_weighted_return": round(book.total_return, 6),
        "flows": [
            {"day": day.isoformat(), "amount": round(amount, 2)} for day, amount in book.flows
        ],
        "slippage_bps": deployment.slippage_bps,
        # Rupees, flows included, on the same days as the report's curve.
        "actual_equity": [deployment.capital] * (len(days) - len(book.curve))
        + [round(value, 2) for _, value in book.curve],
    }
    metrics = (backtest or {}).get("metrics") or {}
    payload["backtest"] = (
        {
            "period": backtest.get("period") if backtest else None,
            "metrics": {key: metrics.get(key) for key in COMPARED},
            "max_drawdown": (metrics.get("drawdown") or {}).get("depth"),
        }
        if metrics
        else None
    )
    from eulerlab import attribution

    return {"ok": True, "report": payload, "attribution": attribution.analyse(payload)}
