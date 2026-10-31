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
from datetime import UTC, datetime
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


class ReduceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    on: bool


class LimitsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reduce_at: float | None = Field(default=None, gt=0, lt=1)
    halt_at: float | None = Field(default=None, gt=0, lt=1)


class FlowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["add", "withdraw"]
    amount: float = Field(gt=0, allow_inf_nan=False)


def _rows() -> list[Any]:
    from eulerlab.api.panels import PANEL

    return PANEL.rows(0)


def _summary(deployment: store.Deployment) -> dict[str, Any]:
    from eulerlab.deploy import loss_limits

    state = store.read_state(deployment) or {}
    limits = loss_limits.for_deployment(deployment)
    if "loss_limit" not in state and state.get("curve"):
        # A book not run since loss limits existed has no measurement in its
        # state, and every card read "not measured yet" for a day. The same
        # calculation, made here, with no action attached: only a run acts.
        now, worst = loss_limits.drawdown(state, deployment.capital)
        state = {
            **state,
            "loss_limit": {
                "drawdown": now,
                "worst": worst,
                "reduce_at": limits.reduce_at,
                "halt_at": limits.halt_at,
                "reducing": loss_limits.is_reducing(deployment),
                "action": None,
            },
        }
    return {
        **deployment.model_dump(mode="json"),
        "running": RUNNING.get(deployment.id, ""),
        "state": state,
        "reducing_now": loss_limits.is_reducing(deployment),
        "limits": limits.model_dump(),
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
    from eulerlab.deploy import intraday_book, study_book
    from eulerlab.intraday.paper_scan import ALL_SIGNALS

    if (module := study_book.module_of(request.strategy)) and intraday_book.holdout_end():
        first = intraday_book.first_session(
            datetime.now(UTC).date(), intraday_book.holdout_end() or datetime.now(UTC).date()
        )
        return {
            "ok": False,  # no names to count; the sentence below is the preview
            "error": f"Runs its study ({module}) over each session's minute bars from {first}, "
            "sized to this capital; flat at every close.",
        }
    if request.strategy in ALL_SIGNALS:
        found, end = intraday_book.instrument(request.strategy), intraday_book.holdout_end()
        if found is None or end is None:
            return {"ok": False, "error": intraday_book.blocker(request.strategy)}
        symbol, market = found
        first = intraday_book.first_session(datetime.now(UTC).date(), end)
        return {
            "ok": False,  # no names to count; the sentence below is the preview
            "error": f"Trades {symbol} on minute bars from {first}, one setup a session, "
            f"flat at every close; capital in {intraday_book.MARKETS[market]}.",
        }
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
    from eulerlab.deploy.runner import paper_blocker

    if blocker := paper_blocker(request.strategy):
        return {"ok": False, "error": f"cannot paper-trade: {blocker}"}
    from eulerlab.deploy import intraday_book, study_book
    from eulerlab.intraday.paper_scan import ALL_SIGNALS

    if request.strategy in ALL_SIGNALS or study_book.module_of(request.strategy):
        end = intraday_book.holdout_end()
        assert end is not None  # `paper_blocker` refuses without it
        deployment = store.create(
            request.strategy,
            mode=request.mode,
            capital=request.capital,
            start=intraday_book.first_session(datetime.now(UTC).date(), end),
        )
        _run_in_background(deployment.id)
        return {"ok": True, "deployment": _summary(deployment)}

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


@router.get("/{deployment_id}/report")
def report(deployment_id: str, workspace: str = "") -> dict[str, Any]:
    """The backtest report's analysis of this deployment's own record (`deploy/analysis`)."""
    from eulerlab import workspace as workspace_mod
    from eulerlab.api.risk_routes import _backtest
    from eulerlab.deploy import analysis

    try:
        deployment = store.load(deployment_id)
    except FileNotFoundError:
        return {"ok": False, "error": "no such deployment"}
    tested = _backtest(workspace_mod.resolve(workspace or None), deployment.strategy_id)
    return analysis.build(
        deployment, store.read_state(deployment), store.read_fills(deployment), tested
    )


@router.get("/{deployment_id}/attribution")
def attribution_detail(deployment_id: str, workspace: str = "") -> dict[str, Any]:
    """The detailed attribution of a deployment's own record (research 115)."""
    from eulerlab import attribution_detail as detail_mod
    from eulerlab.deploy import analysis

    try:
        deployment = store.load(deployment_id)
    except FileNotFoundError:
        return {"ok": False, "error": "no such deployment"}
    state = store.read_state(deployment)
    built = analysis.build(deployment, state, store.read_fills(deployment), None)
    if not built["ok"]:
        return built
    key = f"deployment|{deployment_id}|{(state or {}).get('traded_through')}"
    try:
        return {"ok": True, "detail": detail_mod.analyse_detail(built["report"], key=key)}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]}


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


def _flow_key(flow: dict[str, Any]) -> tuple[str, str]:
    """A flow's identity: when it was entered and the close it was dated against."""
    return str(flow.get("entered_at", "")), str(flow.get("last_decided", ""))


@router.post("/{deployment_id}/flow")
def cash_flow(deployment_id: str, request: FlowRequest) -> dict[str, Any]:
    """Queue external capital for the first decision after the current close."""
    from eulerlab.ingest.filelock import exclusive

    try:
        # Match the run thread's process and in-process locks so its replay
        # cannot observe half of a deployment update.
        with RUN_LOCK, exclusive("paper_daily"):
            deployment = store.load(deployment_id)
            if deployment.mode == "live":
                return {"ok": False, "error": "cash flows are disabled for live deployments"}
            if deployment.status != "active":
                return {"ok": False, "error": f"deployment is {deployment.status}"}
            if RUNNING.get(deployment_id):
                return {"ok": False, "error": "deployment is running; try again when it finishes"}

            amount = request.amount if request.action == "add" else -request.amount
            state = store.read_state(deployment) or {}
            curve = state.get("curve") or []
            last_decided = str(
                state.get("last_decided")
                or (curve[-2][0] if len(curve) > 1 else deployment.start.isoformat())
            )
            applied = state.get("flows", [])
            applied_keys = {_flow_key(item) for item in applied}
            pending = [flow for flow in deployment.flows if _flow_key(flow) not in applied_keys]
            projected = (
                float(state.get("equity", deployment.capital))
                + sum(float(flow.get("amount", 0.0)) for flow in pending)
                + amount
            )
            if request.action == "withdraw" and projected < MIN_CAPITAL:
                return {
                    "ok": False,
                    "error": f"withdrawal must leave at least ₹{MIN_CAPITAL:,.0f} in the deployment",
                }

            flow = {
                "amount": round(amount, 2),
                "last_decided": last_decided,
                "entered_at": datetime.now(UTC).isoformat(timespec="microseconds"),
            }
            updated = deployment.model_copy(update={"flows": [*deployment.flows, flow]})
            store.save(updated)
            store.write_state(
                updated,
                {
                    **state,
                    "invested": state.get("invested", deployment.capital),
                    "flows": applied,
                    "pending": [*pending, flow],
                },
            )
            return {"ok": True, "flow": flow, "deployment": _summary(updated)}
    except FileNotFoundError:
        return {"ok": False, "error": "no such deployment"}


@router.post("/{deployment_id}/reduce")
def reduce_only(deployment_id: str, request: ReduceRequest) -> dict[str, Any]:
    """Reduce-only on or off (ADR-092). On: buys are refused from the next session.

    Off closes the window at the last traded day, so days already traded
    reduce-only replay exactly as they were traded.
    """
    from datetime import date, timedelta

    from eulerlab.deploy import loss_limits
    from eulerlab.ingest.filelock import exclusive

    try:
        with RUN_LOCK, exclusive("paper_daily"):
            deployment = store.load(deployment_id)
            if deployment.status != "active":
                return {"ok": False, "error": f"deployment is {deployment.status}"}
            state = store.read_state(deployment) or {}
            traded = state.get("traded_through")
            last = (
                date.fromisoformat(str(traded)) if traded else deployment.start - timedelta(days=1)
            )
            if request.on:
                updated = loss_limits.start_reducing(
                    deployment, last, "set by the operator", "operator"
                )
            else:
                updated = loss_limits.stop_reducing(deployment, last, "operator")
            return {"ok": True, "deployment": _summary(updated)}
    except FileNotFoundError:
        return {"ok": False, "error": "no such deployment"}


@router.post("/{deployment_id}/limits")
def set_limits(deployment_id: str, request: LimitsRequest) -> dict[str, Any]:
    """This deployment's own drawdown levels; null falls back to config/loss_limits.yaml."""
    from eulerlab.ingest.filelock import exclusive

    if (
        request.reduce_at is not None
        and request.halt_at is not None
        and request.reduce_at >= request.halt_at
    ):
        return {"ok": False, "error": "the reduce-only level must be below the halt level"}
    try:
        with RUN_LOCK, exclusive("paper_daily"):
            deployment = store.load(deployment_id)
            updated = deployment.model_copy(
                update={"reduce_at": request.reduce_at, "halt_at": request.halt_at}
            )
            store.save(updated)
            return {"ok": True, "deployment": _summary(updated)}
    except FileNotFoundError:
        return {"ok": False, "error": "no such deployment"}
