"""Deployments: start a strategy paper-trading forward, see its book, stop it.

`/api/deploy/preflight` (in `server.py`) says whether a strategy may deploy.
These routes do it. Paper only: a live deployment is refused here, with the
reason, until the Kite adapter has been proven against the real API (T-3336)
and the operator has set the live limits.

A run replays the deployment through the engine (`deploy.runner`), which reads
the whole panel, so it happens on a background thread. One run at a time: two
replays of one deployment at once would race on its journal.
"""

from __future__ import annotations

import threading
import traceback
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from eulerlab.deploy import deployments as store

router = APIRouter(prefix="/api/deployments")

RUN_LOCK = threading.Lock()
RUNNING: dict[str, str] = {}
"""Deployment id -> what it is doing, while a run is in progress."""

MIN_CAPITAL = 1_000.0


class DeployRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy: str
    mode: Literal["paper", "live"] = "paper"
    capital: float = Field(gt=0)


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy: str
    capital: float = Field(gt=0)


def _rows() -> list[Any]:
    from eulerlab.api.panels import PANEL

    return PANEL.rows(0)


def _summary(deployment: store.Deployment) -> dict[str, Any]:
    state = store.read_state(deployment) or {}
    return {
        **deployment.model_dump(mode="json"),
        "running": RUNNING.get(deployment.id, ""),
        "state": state,
    }


def _run_in_background(deployment_id: str) -> None:
    from eulerlab.deploy import runner
    from eulerlab.ingest.filelock import exclusive

    def work() -> None:
        # The file lock as well as RUN_LOCK: `make paper-daily` runs in another
        # process and replays the same journals.
        with RUN_LOCK, exclusive("paper_daily"):
            RUNNING[deployment_id] = "running"
            try:
                runner.run(store.load(deployment_id), _rows())
            except Exception:
                deployment = store.load(deployment_id)
                previous = store.read_state(deployment) or {}
                store.write_state(
                    deployment,
                    {**previous, "status": "error", "reason": traceback.format_exc(limit=3)},
                )
            finally:
                RUNNING.pop(deployment_id, None)

    RUNNING[deployment_id] = "queued"
    threading.Thread(target=work, daemon=True).start()


@router.get("")
def list_deployments() -> dict[str, Any]:
    return {"deployments": [_summary(d) for d in store.all_deployments()]}


def _overnight_latest() -> tuple[Any, str, float] | None:
    """The newest stored futures day, with the contract a signal would buy and its close."""
    from datetime import date as date_type

    from eulerlab.deploy import overnight
    from eulerlab.market_history import NIFTY_FUTURES, _stored_days

    days = sorted(_stored_days(NIFTY_FUTURES), key=lambda d: str(d["d"]))
    if not days:
        return None
    last = days[-1]
    chosen = overnight.contract_for(last["contracts"], str(last["d"]))
    if chosen is None:
        return None
    return date_type.fromisoformat(str(last["d"])), chosen[0], chosen[1]


def _overnight_preview(capital: float) -> dict[str, Any]:
    """Whether this much money buys one lot of the future, at the last close."""
    from eulerlab.deploy import overnight

    latest = _overnight_latest()
    if latest is None:
        return {"ok": False, "error": "no Nifty future history. Run `make daily` first."}
    day, expiry, close = latest
    lot = overnight.lot_size(day, expiry)
    if not lot:
        return {"ok": False, "error": f"the lot size is not in the F&O file for {day}"}
    lots = int(capital // (lot * close))
    symbol = overnight.symbol_of(expiry)
    return {
        "ok": True,
        "as_of": day.isoformat(),
        "gross": 1.0,
        "wanted": 1,
        "affordable": 1 if lots else 0,
        "names": [f"{lots} lot(s) of {symbol}"] if lots else [],
        "cut": [] if lots else [symbol],
        "note": (
            f"One lot is {lot} units, ₹{lot * close:,.0f} at the last close. The book holds "
            f"whole lots up to its own equity, with no borrowing, and only on nights after a "
            f"GREEN day with VIX down."
        ),
    }


@router.post("/preview")
def preview(request: PreviewRequest) -> dict[str, Any]:
    """How many of the strategy's names this much money can buy today."""
    from eulerlab.deploy import overnight
    from eulerlab.deploy.runner import GROSS, _intended, _strategy
    from eulerlab.features.panel import trading_days

    if request.strategy in overnight.STRATEGIES:
        return _overnight_preview(request.capital)
    rows = _rows()
    if not rows:
        return {"ok": False, "error": "no panel on disk"}
    try:
        strategy = _strategy(request.strategy)
    except KeyError as exc:
        return {"ok": False, "error": str(exc)}
    day = trading_days(rows)[-1]
    recent = [r for r in rows if (day - r.day).days <= 550]
    intended = _intended(strategy, recent, day, request.capital)
    return {"ok": "error" not in intended, "as_of": day.isoformat(), "gross": GROSS, **intended}


@router.post("")
def deploy(request: DeployRequest) -> dict[str, Any]:
    from eulerlab.deploy.runner import _strategy
    from eulerlab.features.panel import trading_days

    if request.mode == "live":
        return {
            "ok": False,
            "error": (
                "Live trading is not enabled. The Kite adapter has never placed a real "
                "order (T-3336), and the live capital cap and confirmation rule have not "
                "been set. Paper-trade first."
            ),
        }
    if request.capital < MIN_CAPITAL:
        return {"ok": False, "error": f"capital must be at least ₹{MIN_CAPITAL:,.0f}"}
    from eulerlab.deploy import overnight

    if request.strategy in overnight.STRATEGIES:
        latest = _overnight_latest()
        if latest is None:
            return {"ok": False, "error": "no Nifty future history. Run `make daily` first."}
        deployment = store.create(
            request.strategy, mode=request.mode, capital=request.capital, start=latest[0]
        )
        _run_in_background(deployment.id)
        return {"ok": True, "deployment": _summary(deployment)}
    try:
        strategy = _strategy(request.strategy)
    except KeyError as exc:
        return {"ok": False, "error": str(exc)}
    if not hasattr(strategy, "target_weights"):
        return {"ok": False, "error": "only daily target-weight strategies can deploy"}
    rows = _rows()
    if not rows:
        return {"ok": False, "error": "no panel on disk. Run `make daily` first."}
    start = trading_days(rows)[-1]
    deployment = store.create(
        request.strategy, mode=request.mode, capital=request.capital, start=start
    )
    _run_in_background(deployment.id)
    return {"ok": True, "deployment": _summary(deployment)}


@router.get("/{deployment_id}")
def get_deployment(deployment_id: str) -> dict[str, Any]:
    try:
        return {"ok": True, "deployment": _summary(store.load(deployment_id))}
    except FileNotFoundError:
        return {"ok": False, "error": "no such deployment"}


@router.post("/{deployment_id}/run")
def run_now(deployment_id: str) -> dict[str, Any]:
    deployment = store.load(deployment_id)
    if deployment.status != "active":
        return {"ok": False, "error": f"deployment is {deployment.status}"}
    if RUNNING.get(deployment_id):
        return {"ok": False, "error": "already running"}
    _run_in_background(deployment_id)
    return {"ok": True}


@router.post("/{deployment_id}/stop")
def stop(deployment_id: str) -> dict[str, Any]:
    """Stop trading. Positions stay as they are at the paper broker; nothing is sold."""
    deployment = store.set_status(store.load(deployment_id), "stopped", "stopped by the operator")
    return {"ok": True, "deployment": _summary(deployment)}
