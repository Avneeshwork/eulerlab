"""The HTTP API behind the web interface.

A thin layer, on purpose. It compiles strategies, starts backtests and reports
results — it does not contain a backtester, a cost model or a notion of what a
good result is. Every number it returns came out of the same engine that
`make backtest` uses, because a second path to a number is a second answer.

Three things it refuses to do, each of which the obvious implementation would:

**It never spends a trial.** `make gate` and `make validate` write to the
hash-chained ledger, and every entry permanently raises the Deflated Sharpe bar
for every future candidate. A web interface makes running things cheap and
fast, which is exactly the property that would let someone burn fifty trials in
an afternoon by clicking. So no endpoint here writes to the ledger, and the
counter is exposed read-only so the interface can *show* the cost.

**It never promotes anything.** There is no route to the gate. Promotion is a
deliberate, operator-owned act performed at a terminal, not a button.

**It never runs unvalidated code.** Source arrives as text and goes through the
sandbox before anything executes. A rejected strategy produces a message
naming the rule it broke.

The panel is loaded once and cached in the process: it is 540 MB of JSONL, and
re-reading it per request would make every backtest feel broken.
"""

from __future__ import annotations

import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import date
from itertools import pairwise
from typing import Any, Literal

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field

from eulerlab.authoring import translate
from eulerlab.authoring.sandbox import EXAMPLE, UnsafeStrategy
from eulerlab.backtest import event_driven, vector
from eulerlab.backtest.strategy import Strategy
from eulerlab.backtest.vector import build_adjusted_index
from eulerlab.features.library import BY_NAME
from eulerlab.features.panel import PanelRow, read_panel, trading_days
from eulerlab.intraday import scan as tweezer_scan
from eulerlab.intraday.tweezer import Rules
from eulerlab.llm import client
from eulerlab.research.budget import price_search
from eulerlab.validation import montecarlo
from eulerlab.validation.ledger import count as trial_count
from eulerlab.validation.statistics import sharpe_stats

app = FastAPI(title="EulerLab", version="0.1.0")

# The UI is served by Next.js on another port in development. Restricted to
# localhost: this API can start real computation and read the research data,
# so it is not something to expose to a browser on any other origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

JOB_TIMEOUT_SECONDS = 900


# --- panel cache ------------------------------------------------------------


class _Panel:
    """One copy of the panel and its adjusted index, shared by every request.

    Guarded by a lock because two requests arriving together would otherwise
    both start a 540 MB read. The index is keyed by the day-window so the
    common case — the same last-N-days repeatedly — is computed once.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rows: list[PanelRow] | None = None
        self._indices: dict[int, dict[str, dict[date, float]]] = {}

    def rows(self, days: int = 0) -> list[PanelRow]:
        with self._lock:
            if self._rows is None:
                self._rows = read_panel()
        if not days:
            return self._rows
        all_days = sorted({r.day for r in self._rows})
        if days >= len(all_days):
            return self._rows
        cutoff = all_days[-days]
        return [r for r in self._rows if r.day >= cutoff]

    def index(self, days: int, rows: list[PanelRow]) -> dict[str, dict[date, float]]:
        with self._lock:
            if days not in self._indices:
                self._indices[days] = build_adjusted_index(rows)
            return self._indices[days]

    def loaded(self) -> bool:
        return self._rows is not None


PANEL = _Panel()


# --- jobs -------------------------------------------------------------------


@dataclass
class Job:
    id: str
    status: Literal["queued", "running", "done", "failed"] = "queued"
    message: str = ""
    started: float = field(default_factory=time.time)
    finished: float = 0.0
    result: dict[str, Any] = field(default_factory=dict)
    error: str = ""

    def payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "message": self.message,
            "elapsed": round((self.finished or time.time()) - self.started, 1),
            "result": self.result,
            "error": self.error,
        }


JOBS: dict[str, Job] = {}
JOBS_LOCK = threading.Lock()


# --- request models ---------------------------------------------------------


class TweezerRequest(BaseModel):
    """An intraday Tweezer Bottom scan.

    Separate from `BacktestRequest` on purpose. Tweezer is not a `Strategy` and
    does not go through the daily engine — it has a conditional stop-entry, a
    bracket exit and risk-based sizing, none of which a target weight can hold.
    Sharing a request model would imply they are interchangeable.
    """

    model_config = ConfigDict(extra="forbid")

    symbols: list[str] = Field(default_factory=lambda: ["RELIANCE", "TCS", "INFY"])
    start: str = "2024-01-01"
    end: str = "2024-06-30"
    equity: float = Field(default=1_000_000.0, gt=0)


class DraftRequest(BaseModel):
    description: str = Field(min_length=3, max_length=4000)
    mode: Literal["composed", "code"] = "composed"
    provider: str | None = None


class ValidateRequest(BaseModel):
    mode: Literal["composed", "code"]
    source: str = ""
    feature: str = ""
    top_n: int = 30
    rebalance: int = 21
    min_turnover: float = 0.0


class BacktestRequest(ValidateRequest):
    days: int = Field(default=800, ge=60, le=3000)
    starting_cash: float = Field(default=1_000_000.0, gt=0)
    tier: Literal["A", "B"] = "B"
    """Tier A is the fast vectorised screen; Tier B is the event-driven engine
    with the real order lifecycle. ADR-021: Tier A is a screen, not a backtest,
    and the UI labels it that way."""


# --- helpers ----------------------------------------------------------------


def _build(request: ValidateRequest) -> tuple[Strategy, translate.Draft]:
    if request.mode == "code":
        draft = translate.from_code(request.source)
    else:
        draft = translate.from_spec(
            request.feature or "momentum_12_1",
            top_n=request.top_n,
            rebalance=request.rebalance,
            min_turnover=request.min_turnover,
        )
    return draft.build(), draft


def _drawdown(equity: list[float]) -> float:
    peak, worst = equity[0] if equity else 0.0, 0.0
    for value in equity:
        peak = max(peak, value)
        if peak > 0:
            worst = min(worst, value / peak - 1.0)
    return worst


def _run_backtest(job: Job, request: BacktestRequest) -> None:
    try:
        job.status, job.message = "running", "loading the panel"
        strategy, draft = _build(request)
        rows = PANEL.rows(request.days)
        if not rows:
            raise RuntimeError("no panel on disk. Run `make build-panel` first.")

        days = trading_days(rows)
        job.message = f"{len(rows):,} rows, {len(days):,} trading days"
        warmup = min(253, max(20, len(days) // 4))

        index = PANEL.index(request.days, rows)
        job.message = f"running tier {request.tier}"

        rebalance = request.rebalance
        if request.tier == "A":
            run = vector.run(
                rows,
                strategy,
                starting_cash=request.starting_cash,
                rebalance_every=rebalance,
                warmup=warmup,
                adjusted_index=index,
            )
            equity, curve_days = run.equity, run.days
            fills, rejects, costs = len(run.fills), 0, run.total_cost
        else:
            run_b = event_driven.run(
                rows,
                strategy,
                starting_cash=request.starting_cash,
                rebalance_every=rebalance,
                warmup=warmup,
                adjusted_index=index,
            )
            equity, curve_days = run_b.equity, run_b.days
            fills, rejects = len(run_b.fills), len(run_b.rejections)
            costs = run_b.total_cost

        if not equity:
            raise RuntimeError(
                f"the run produced no days. The window ({len(days)} trading days) is "
                f"too short for a {warmup}-day warmup plus a rebalance."
            )

        returns = [b / a - 1.0 for a, b in pairwise(equity) if a > 0]
        stats = sharpe_stats(returns)
        total = equity[-1] / request.starting_cash - 1.0
        years = len(equity) / 252.0

        resampled = None
        if len(returns) >= 30:
            # Costs nothing: this is arithmetic on a result already computed,
            # so it spends no trial and adds no backtest.
            simulated = montecarlo.run(returns, simulations=400)
            resampled = {
                "drawdown_p05": simulated.drawdown.p05,
                "drawdown_p50": simulated.drawdown.p50,
                "sharpe_p05": simulated.sharpe.p05,
                "sharpe_p95": simulated.sharpe.p95,
                "drawdown_is_understated": simulated.drawdown_is_understated,
                "sharpe_could_be_zero": simulated.sharpe_could_be_zero,
            }

        job.result = {
            "resampled": resampled,
            "label": draft.label(),
            "mode": request.mode,
            "tier": request.tier,
            "strategy": strategy.describe(),
            "days": [d.isoformat() for d in curve_days],
            "equity": [round(v, 2) for v in equity],
            "starting_cash": request.starting_cash,
            "final_equity": round(equity[-1], 2),
            "total_return": total,
            "annualised": (equity[-1] / request.starting_cash) ** (1 / years) - 1.0
            if years > 0.5
            else total,
            "sharpe": stats.sharpe,
            "max_drawdown": _drawdown(equity),
            "fills": fills,
            "rejections": rejects,
            "costs": round(costs, 2),
            "period": [curve_days[0].isoformat(), curve_days[-1].isoformat()],
            "warmup": warmup,
            "noise_bar": round(price_search(0, available_years=11.4).bar_after, 3),
            "caveats": _caveats(request, stats.sharpe),
        }
        job.status, job.message = "done", "complete"
    except (UnsafeStrategy, RuntimeError, ValueError, KeyError) as exc:
        job.status, job.error = "failed", str(exc)
    except Exception as exc:
        job.status = "failed"
        job.error = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()[-1500:]}"
    finally:
        job.finished = time.time()


def _caveats(request: BacktestRequest, sharpe: float) -> list[str]:
    """What this number does not mean. Returned with every result, always.

    Attached to the payload rather than written into the UI, so the warning
    travels with the number instead of being a paragraph someone can style
    away. A backtest shown without its caveats is the most misleading artefact
    this project can produce.
    """
    trials = trial_count()
    bar = price_search(0, available_years=11.4).bar_after
    out = [
        f"This is one backtest, not evidence. {trials} trials are already logged, so a "
        f"candidate needs to beat Sharpe {bar:.2f} from noise alone before it means anything.",
        "Running this did NOT spend a trial. Only `make validate` and `make gate` do, "
        "and both are deliberately absent from this interface.",
        "Market impact is not modelled at all (T-907). Any result involving thin names "
        "is optimistic.",
        "Every transaction-cost rate comes from a secondary source and has never been "
        "checked against a real contract note (T-906, A-016).",
    ]
    if request.tier == "A":
        out.insert(
            1,
            "Tier A is a SCREEN, not a backtest (ADR-021). It collapses decide/trade/own "
            "into one step and cannot model a rejection or a partial fill. Re-run on "
            "Tier B before believing anything.",
        )
    if sharpe > bar:
        out.insert(
            0,
            f"Sharpe {sharpe:.2f} is above the {bar:.2f} noise bar. That is necessary, "
            f"not sufficient — the gate also requires PBO, stress and regime tests.",
        )
    if request.days < 500:
        out.append(
            f"{request.days} days is a short window. Minimum-backtest-length arithmetic "
            f"needs years, not months, before a Sharpe is distinguishable from luck."
        )
    return out


# --- routes -----------------------------------------------------------------


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "panel_loaded": PANEL.loaded(),
        "trials_logged": trial_count(),
        "noise_bar": round(price_search(0, available_years=11.4).bar_after, 3),
    }


@app.get("/api/library")
def library() -> dict[str, Any]:
    return {
        "features": [{"name": f.name, "description": f.description} for f in BY_NAME.values()],
        "example_code": EXAMPLE,
        "sandbox_rules": [
            "No imports, no `while`, no classes, no `try`, no `with`.",
            "Builtins are limited to arithmetic and containers. There is no `open` or `eval`.",
            "Attributes are allowlisted — a strategy sees the market view and nothing else.",
            "The view contains no rows after the decision date, so lookahead is impossible.",
        ],
    }


@app.get("/api/providers")
def providers() -> dict[str, Any]:
    try:
        return {"providers": client.health(), "ok": True}
    except client.LLMUnavailable as exc:
        return {"providers": [], "ok": False, "error": str(exc)}


@app.post("/api/draft")
def make_draft(request: DraftRequest) -> dict[str, Any]:
    """Ask a model for a strategy. Returns it unrun, for the operator to read."""
    try:
        drafted = translate.draft(
            request.description, mode=request.mode, provider_name=request.provider
        )
    except (client.LLMUnavailable, UnsafeStrategy, ValueError) as exc:
        return {"ok": False, "error": str(exc)}
    return {
        "ok": True,
        "mode": drafted.mode,
        "spec": drafted.spec,
        "source": drafted.source,
        "explanation": drafted.explanation,
        "warnings": drafted.warnings,
        "provider": drafted.provider,
        "model": drafted.model,
    }


@app.post("/api/validate")
def validate(request: ValidateRequest) -> dict[str, Any]:
    """Compile without running. What the editor calls as you type."""
    try:
        _, drafted = _build(request)
    except (UnsafeStrategy, ValueError, KeyError) as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "label": drafted.label()}


@app.post("/api/backtest")
def backtest(request: BacktestRequest) -> dict[str, Any]:
    """Start a run. Returns immediately with a job id."""
    try:
        _build(request)
    except (UnsafeStrategy, ValueError, KeyError) as exc:
        return {"ok": False, "error": str(exc)}

    job = Job(id=uuid.uuid4().hex[:12])
    with JOBS_LOCK:
        JOBS[job.id] = job
    thread = threading.Thread(target=_run_backtest, args=(job, request), daemon=True)
    thread.start()
    return {"ok": True, "job": job.id}


def _run_tweezer(job: Job, request: TweezerRequest) -> None:
    try:
        job.status = "running"
        start, end = date.fromisoformat(request.start), date.fromisoformat(request.end)
        rules = Rules()
        symbols: list[dict[str, Any]] = []
        trades: list[dict[str, Any]] = []
        rejections: dict[str, int] = {}
        candles = sessions = 0

        for name in request.symbols[:10]:
            job.message = f"scanning {name}"
            result = tweezer_scan.scan_symbol(
                name, start=start, end=end, rules=rules, equity=request.equity
            )
            candles += result.candles
            sessions += result.sessions
            for reason, count in result.rejections.items():
                rejections[reason] = rejections.get(reason, 0) + count
            symbols.append(
                {
                    "symbol": name,
                    "sessions": result.sessions,
                    "candles": result.candles,
                    "setups": result.plans,
                    "filled": len(result.filled),
                    "net_pnl": round(result.net_pnl(), 2),
                    "costs": round(result.costs(), 2),
                }
            )
            for trade in result.filled:
                trades.append(
                    {
                        "symbol": name,
                        "entry_ts": trade.entry_ts.isoformat() if trade.entry_ts else None,
                        "entry": round(trade.entry_price, 2),
                        "stop": round(trade.plan.stop, 2),
                        "target_1": round(trade.plan.target_1, 2),
                        "target_2": round(trade.plan.target_2, 2),
                        "risk_pct": round(trade.plan.risk_pct, 2),
                        "shares": trade.plan.shares,
                        "net_pnl": round(trade.net_pnl(), 2),
                        "r_multiple": round(trade.r_multiple(), 2),
                        "exits": [
                            {"reason": e.reason, "price": round(e.price, 2), "shares": e.shares}
                            for e in trade.exits
                        ],
                    }
                )

        filled = sum(s["filled"] for s in symbols)
        wins = sum(1 for t in trades if t["net_pnl"] > 0)
        job.result = {
            "symbols": symbols,
            "trades": trades,
            "rejections": sorted(rejections.items(), key=lambda kv: -kv[1])[:10],
            "candles": candles,
            "sessions": sessions,
            "setups": sum(s["setups"] for s in symbols),
            "filled": filled,
            "wins": wins,
            "net_pnl": round(sum(t["net_pnl"] for t in trades), 2),
            "period": [request.start, request.end],
            "caveats": _tweezer_caveats(filled, candles),
        }
        job.status = "done"
        job.message = "complete"
    except Exception as exc:
        job.status = "failed"
        job.error = f"{type(exc).__name__}: {exc}"
    finally:
        job.finished = time.time()


def _tweezer_caveats(filled: int, candles: int) -> list[str]:
    """What the number on screen does not mean.

    Returned with the result rather than written into the page, so the warning
    travels with the figure instead of being a paragraph someone can style away.
    """
    out = [
        "This is one hand-picked symbol set over one hand-picked window. "
        "It is not a validated result and spent no trial.",
        "Where a single minute's range contains both the stop and a target, the "
        "engine takes the STOP. It cannot know which came first.",
        "Fills assume the whole order goes through at one price. Real intraday "
        "liquidity is not modelled, and market impact is not modelled anywhere (T-907).",
    ]
    if filled == 0:
        out.insert(0, "No orders filled. Every number below is zero because nothing traded.")
    elif filled < 20:
        out.insert(
            0,
            f"Only {filled} trade(s) filled in {candles:,} candles. A win rate over "
            f"so few trades is noise — it would take dozens before it meant anything.",
        )
    return out


@app.post("/api/tweezer")
def tweezer(request: TweezerRequest) -> dict[str, Any]:
    """Start an intraday scan. Returns immediately with a job id."""
    if not request.symbols:
        return {"ok": False, "error": "pick at least one symbol"}
    job = Job(id=uuid.uuid4().hex[:12])
    with JOBS_LOCK:
        JOBS[job.id] = job
    threading.Thread(target=_run_tweezer, args=(job, request), daemon=True).start()
    return {"ok": True, "job": job.id}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str) -> dict[str, Any]:
    job = JOBS.get(job_id)
    if job is None:
        return {"ok": False, "error": "no such job"}
    if job.status == "running" and time.time() - job.started > JOB_TIMEOUT_SECONDS:
        # Reported, not killed. CPython cannot safely interrupt a thread mid
        # computation, so saying "this has overrun" is the honest option — see
        # S-021. The thread is a daemon and dies with the process.
        job.status = "failed"
        job.error = (
            f"the run passed {JOB_TIMEOUT_SECONDS}s and was abandoned. The thread may "
            f"still be consuming CPU until the server restarts."
        )
        job.finished = time.time()
    return {"ok": True, **job.payload()}
