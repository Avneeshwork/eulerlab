"""`/api/risk/*`: the deployed book's risk, for the Live & Risk screens (ADR-071, ADR-072).

Read-only. It gathers what `risk/report.py` needs: each deployment's stored
book, a year of adjusted closes from the panel the API already holds, the
overnight gaps of the Nifty future, sectors from the company digest, the kill
switch's limits, the operator's watch levels and each strategy's stored
backtest. It runs nothing and changes nothing.

**A deployment is picked up by being there.** Nothing is registered with this
module: every active deployment in `deploy.deployments` is in the figures the
next time the page is read, and a stopped one leaves them and moves to the
"stopped" list with what it made. Its colour is its place in the order the
deployments were created, counting stopped ones, so the rest keep theirs.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from eulerlab import workspace as workspace_mod
from eulerlab.api.panels import PANEL
from eulerlab.deploy import deployments as store
from eulerlab.deploy import overnight
from eulerlab.features import company as company_digest
from eulerlab.oms import killswitch
from eulerlab.research import gap_forecast as gf
from eulerlab.risk import book as rb
from eulerlab.risk import report, watch
from eulerlab.strategies import REGISTRY

router = APIRouter(prefix="/api/risk")

HISTORY = rb.WINDOW + 10
"""Panel days read: the window, and a few spare for a holding that missed a day."""

LOT_LOOKBACK = 10
"""Sessions searched backwards for a lot size when the latest F&O file is missing."""


def _title(strategy_id: str) -> str:
    declared = REGISTRY.get(strategy_id)
    return declared.title if declared else strategy_id


# --- the overnight future ----------------------------------------------------------

_GAPS: dict[str, Any] = {}
"""The futures gaps and signal nights, kept until either source file changes.
Reading them parses 52 MB of index history, which is too slow for every request."""


def _gap_history() -> dict[str, Any]:
    from eulerlab.market_history import INDEX_HISTORY, NIFTY_FUTURES
    from eulerlab.research.gap_forecast_run import load_days
    from eulerlab.research.session_studies import futures_legs

    stamp = tuple(
        Path(p).stat().st_mtime_ns if Path(p).exists() else 0
        for p in (INDEX_HISTORY, NIFTY_FUTURES)
    )
    if _GAPS.get("stamp") == stamp:
        return _GAPS
    days = load_days()
    by_day = {d.day: d for d in days}
    order = [d.day for d in days]
    before = dict(zip(order[1:], order[:-1], strict=True))
    gaps: dict[date, float] = {}
    held: set[date] = set()
    for leg in futures_legs():
        if leg.previous_close <= 0:
            continue
        gaps[leg.day] = leg.open / leg.previous_close - 1.0
        signal = before.get(leg.day)
        if signal is not None and gf.predict(gf.Model.JOINT, by_day[signal]) == gf.UP:
            held.add(leg.day)
    worst = min(gaps.items(), key=lambda item: item[1], default=None)
    _GAPS.clear()
    _GAPS.update(stamp=stamp, gaps=gaps, held=frozenset(held), worst=worst)
    return _GAPS


_LOTS: dict[tuple[date, str], int | None] = {}


def _lot(day: date, expiry: str) -> int | None:
    """The lot size on `day`, remembered: the lookup opens that day's F&O file."""
    key = (day, expiry)
    if key not in _LOTS:
        try:
            _LOTS[key] = overnight.lot_size(day, expiry)
        except Exception:  # a file that cannot be fetched is a missing lot, not a crash
            _LOTS[key] = None
    return _LOTS[key]


def _gap_rule(equity: float, held_now: float) -> rb.GapRule | None:
    """The overnight rule sized for this much money, from the latest futures close."""
    from eulerlab.market_history import NIFTY_FUTURES, _stored_days

    stored = sorted(_stored_days(NIFTY_FUTURES), key=lambda d: str(d["d"]))
    if not stored:
        return None
    last = stored[-1]
    chosen = overnight.contract_for(last["contracts"], str(last["d"]))
    if chosen is None:
        return None
    expiry, close = chosen
    lot = None
    for row in reversed(stored[-LOT_LOOKBACK:]):
        lot = _lot(date.fromisoformat(str(row["d"])), expiry)
        if lot:
            break
    if not lot:
        return None
    lots = int(equity // (lot * close))
    history = _gap_history()
    return rb.GapRule(
        contract=overnight.symbol_of(expiry),
        lots=lots,
        lot_size=lot,
        notional=float(lots * lot * close),
        gaps=history["gaps"],
        held=history["held"],
        held_now=held_now,
        worst=history["worst"],
    )


# --- books ---------------------------------------------------------------------------


def _book(deployment: store.Deployment) -> rb.Book:
    state = store.read_state(deployment)
    found = rb.book_from_state(
        deployment.id,
        deployment.strategy_id,
        _title(deployment.strategy_id),
        deployment.capital,
        deployment.status,
        state,
    )
    if deployment.strategy_id not in overnight.STRATEGIES or deployment.status != "active":
        return found
    # A future held tonight is in the stored book; its risk is the gap, which
    # the rule carries, so it is not also run through share prices.
    held_now = sum(h.value for h in found.holdings)
    rule = _gap_rule(found.equity, held_now)
    return rb.Book(
        found.id,
        found.strategy_id,
        found.title,
        found.capital,
        found.equity,
        found.cash,
        (),
        found.curve,
        found.status,
        rule=rule,
    )


def _all() -> tuple[list[rb.Book], list[rb.Book], dict[str, int]]:
    """(active, stopped, colour slot by id). Slots follow the order of creation."""
    deployments = sorted(store.all_deployments(), key=lambda d: (d.created_at, d.id))
    slots = {d.id: index for index, d in enumerate(deployments)}
    active = [_book(d) for d in deployments if d.status == "active"]
    stopped = [_book(d) for d in deployments if d.status != "active"]
    return active, stopped, slots


def _prices(symbols: set[str]) -> dict[str, dict[date, float]]:
    """A year of adjusted closes for the names held and the market."""
    rows = PANEL.rows(HISTORY)
    index = PANEL.index(HISTORY, rows)
    return {symbol: index[symbol] for symbol in symbols if symbol in index}


def _backtest(tenant: workspace_mod.Workspace, strategy_id: str) -> dict[str, Any]:
    """The longest stored backtest of a strategy: its equity and worst drawdown."""
    folder = tenant.root / "reports" / strategy_id
    best: dict[str, Any] = {}
    if not folder.is_dir():
        return best
    for path in sorted(folder.glob("*.json")):
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        values = (loaded.get("equity") or {}).get("values") or []
        if len(values) > len(best.get("equity") or []):
            depth = ((loaded.get("metrics") or {}).get("drawdown") or {}).get("depth")
            best = {"equity": values, "worst_drawdown": depth, "period": loaded.get("period")}
    return best


@router.get("/book")
def book(workspace: str = "") -> dict[str, Any]:
    """Roll-up, VaR, stress, exposure and limits for every active deployment."""
    tenant = workspace_mod.resolve(workspace or None)
    try:
        books, stopped, slots = _all()
        if not books:
            return {"ok": True, "empty": True, "reason": "No deployment is active."}
        held = {h.symbol for b in books for h in b.holdings}
        prices = _prices(held | {rb.MARKET})
        limits = killswitch.load_limits()
        levels = watch.load()
    except Exception as exc:  # a malformed config must not blank the screen
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]}
    sectors = {symbol: c.sector for symbol, c in company_digest.load_digest().items()}
    payload = report.build(
        books,
        prices,
        sectors,
        enforced={
            "max_daily_loss": limits.max_daily_loss,
            "max_position_notional": limits.max_position_notional,
        },
        watch=levels,
        backtests={b.strategy_id: _backtest(tenant, b.strategy_id) for b in books},
        slots=slots,
        stopped=stopped,
    )
    return {"ok": True, "empty": False, **payload}


class WhatIfRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy: str
    capital: float = Field(gt=0)


def _candidate(strategy_id: str, capital: float) -> rb.Book | str:
    """What this strategy would hold today with this much money, or why not."""
    from eulerlab.api.deploy_routes import _rows
    from eulerlab.deploy.runner import GROSS, _intended, _strategy
    from eulerlab.features.panel import trading_days

    title = _title(strategy_id)
    if strategy_id in overnight.STRATEGIES:
        rule = _gap_rule(capital, 0.0)
        if rule is None:
            return "no Nifty future history or lot size is held"
        return rb.Book(
            "candidate", strategy_id, title, capital, capital, capital, (), (), rule=rule
        )
    rows = _rows()
    if not rows:
        return "no price panel on disk"
    try:
        strategy = _strategy(strategy_id)
    except KeyError as exc:
        return str(exc)
    day = trading_days(rows)[-1]
    recent = [r for r in rows if (day - r.day).days <= 550]
    intended = _intended(strategy, recent, day, capital)
    names = intended.get("names") or []
    if "error" in intended or not names:
        return str(intended.get("error") or "the strategy would hold nothing today")
    # ASSUMPTION: A-060 — the preview gives names, not sizes; equal weights stand in.
    each = capital * GROSS / len(names)
    holdings = tuple(rb.Holding(name, 0.0, 0.0, each) for name in names)
    return rb.Book(
        "candidate", strategy_id, title, capital, capital, capital - each * len(names), holdings, ()
    )


@router.post("/what-if")
def what_if(request: WhatIfRequest) -> dict[str, Any]:
    """The book's VaR before and after adding this strategy. Deploys nothing."""
    try:
        books, _, _ = _all()
        candidate = _candidate(request.strategy, request.capital)
        if isinstance(candidate, str):
            return {"ok": False, "error": candidate}
        held = {h.symbol for b in [*books, candidate] for h in b.holdings}
        found = report.what_if(books, candidate, _prices(held | {rb.MARKET}))
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]}
    return {"ok": True, "deployments": len(books), **found}
