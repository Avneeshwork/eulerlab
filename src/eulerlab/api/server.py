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

from eulerlab import results as result_store
from eulerlab import workspace as workspace_mod
from eulerlab.authoring import translate
from eulerlab.authoring.sandbox import EXAMPLE, UnsafeStrategy
from eulerlab.backtest import event_driven, vector
from eulerlab.backtest.published import BUILDERS as PUBLISHED
from eulerlab.backtest.strategies import BuyAndHold
from eulerlab.backtest.strategy import Strategy
from eulerlab.backtest.vector import build_adjusted_index
from eulerlab.batch import Item as _BatchItem
from eulerlab.batch import data_version as batch_data_version
from eulerlab.batch import runner
from eulerlab.features.library import BY_NAME
from eulerlab.features.panel import PanelRow, read_panel, trading_days
from eulerlab.intraday import scan as tweezer_scan
from eulerlab.intraday.tweezer import Rules
from eulerlab.llm import client
from eulerlab.research.budget import price_search
from eulerlab.strategies import REGISTRY, catalog
from eulerlab.strategies import fleet as strategy_fleet
from eulerlab.validation import montecarlo
from eulerlab.validation.ledger import count as trial_count
from eulerlab.validation.ledger import sharpe_dispersion
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

    universe: str = "nifty50"
    """`nifty50` / `nifty100` / `nifty250`, or empty to use `symbols`.

    These are liquidity-ranked slices of our own turnover history, NOT index
    membership (ADR-008): a published constituent list exists only as it stands
    today, so applying one across history is survivorship bias.
    """

    symbols: list[str] = Field(default_factory=list)
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


@dataclass(frozen=True)
class _EngineRun:
    equity: list[float]
    days: list[date]
    fills: int
    rejects: int
    costs: float


def _engine_run(
    strategy: Strategy,
    rows: list[PanelRow],
    *,
    days_window: int,
    tier: str,
    starting_cash: float,
    rebalance: int,
) -> _EngineRun:
    """The one place this API calls an engine.

    Extracted so a single backtest and a screening batch cannot drift apart —
    the same reasoning as T-2501, which pulled `plan_orders` out so the
    backtest and paper paths shared one implementation. A second path to a
    number is a second answer.
    """
    days = trading_days(rows)
    warmup = min(253, max(20, len(days) // 4))
    index = PANEL.index(days_window, rows)

    if tier == "A":
        run = vector.run(
            rows,
            strategy,
            starting_cash=starting_cash,
            rebalance_every=rebalance,
            warmup=warmup,
            adjusted_index=index,
        )
        return _EngineRun(run.equity, run.days, len(run.fills), 0, run.total_cost)

    run_b = event_driven.run(
        rows,
        strategy,
        starting_cash=starting_cash,
        rebalance_every=rebalance,
        warmup=warmup,
        adjusted_index=index,
    )
    return _EngineRun(
        run_b.equity, run_b.days, len(run_b.fills), len(run_b.rejections), run_b.total_cost
    )


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

        job.message = f"running tier {request.tier}"

        engine = _engine_run(
            strategy,
            rows,
            days_window=request.days,
            tier=request.tier,
            starting_cash=request.starting_cash,
            rebalance=request.rebalance,
        )
        equity, curve_days = engine.equity, engine.days
        fills, rejects, costs = engine.fills, engine.rejects, engine.costs

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
    # The bar is scaled by sigma_SR, which is assumed to be 1.0 and has never
    # been measured (A-021). Reporting the bar without that fact invites it to
    # be read as measured, and at sigma_SR 0.5 the same 19 trials give a bar of
    # 0.94 rather than 1.88 — a difference that spans our best-ever result.
    dispersion = sharpe_dispersion()
    return {
        "ok": True,
        "panel_loaded": PANEL.loaded(),
        "trials_logged": trial_count(),
        "noise_bar": round(price_search(0, available_years=11.4).bar_after, 3),
        "noise_bar_sigma_measured": dispersion.usable,
        "noise_bar_sigma": dispersion.sigma,
        "noise_bar_note": dispersion.reason,
    }


def _best_sharpe(tenant: workspace_mod.Workspace, row: Any) -> float | None:
    """A strategy's best backtest Sharpe, or None if it has never run.

    None, never zero. Zero is a measurement meaning no edge; None means nobody
    looked, and the library renders them differently on purpose.
    """
    top = result_store.best(tenant, row.declaration.id)
    return round(top.run.sharpe, 4) if top else None


def _clears(tenant: workspace_mod.Workspace, row: Any, bar: float) -> bool:
    value = row.sharpe if row.sharpe is not None else _best_sharpe(tenant, row)
    return value is not None and value >= bar


@app.get("/api/fleet")
def fleet(workspace: str = "") -> dict[str, Any]:
    """Every registered strategy, with whatever the ledger knows about it.

    `sharpe` is null for a strategy that has never been evaluated, and the
    console must render that as "not measured" rather than as zero. `bar` is
    returned alongside so every Sharpe can be drawn against it — a bare Sharpe
    in a list invites sorting descending and taking the top, which is exactly
    the selection procedure PBO measures as overfitting.
    """
    bar = price_search(0, available_years=11.4).bar_after
    dispersion = sharpe_dispersion()
    tenant = workspace_mod.resolve(workspace or None)
    return {
        "bar": round(bar, 3),
        "bar_sigma_measured": dispersion.usable,
        "bar_note": dispersion.reason,
        "strategies": [
            {
                "id": row.declaration.id,
                "title": row.declaration.title,
                "summary": row.declaration.summary,
                "kind": row.declaration.kind,
                "shape": row.declaration.shape,
                "asset_class": row.declaration.asset_class.value,
                "timeframe": row.declaration.timeframe.value,
                "emits": row.declaration.emits.value,
                "lookback": row.declaration.lookback,
                "risk_manager": row.declaration.risk_manager,
                "trade_manager": row.declaration.trade_manager,
                "is_strategy_subclass": row.declaration.is_strategy_subclass,
                "stage": row.stage.value,
                # The ledger's Sharpe (a validated result) takes precedence over
                # a screened one: it is the stronger claim and was paid for.
                # `result` carries the backtest figure and, inseparably, how
                # many runs it was the best of.
                "sharpe": row.sharpe if row.sharpe is not None else _best_sharpe(tenant, row),
                "result": result_store.summary(tenant, row.declaration.id),
                "trials": row.trials,
                "clears_bar": _clears(tenant, row, bar),
            }
            for row in strategy_fleet(tenant.ledger)
        ],
    }


@app.get("/api/capabilities")
def capabilities() -> dict[str, Any]:
    """Which (asset class, timeframe) pairs have data behind them.

    Reported so the console can refuse an unsupported combination rather than
    running it and returning nothing. An empty result reads as "no trades
    found"; the truth is "never measured" (ADR-037).
    """
    return {
        "matrix": [
            {
                "asset_class": c.asset_class.value,
                "timeframe": c.timeframe.value,
                "supported": c.supported,
                "detail": c.detail,
            }
            for c in catalog.capabilities()
        ]
    }


@app.get("/api/instruments")
def instruments(q: str = "", batch: str = "", limit: int = 60) -> dict[str, Any]:
    """Search instruments, optionally inside a named batch."""
    try:
        found = catalog.search(q, batch=batch, limit=limit)
    except (ValueError, FileNotFoundError) as exc:
        return {"ok": False, "error": str(exc), "instruments": []}
    return {
        "ok": True,
        "batches": sorted(catalog.UNIVERSE_FILES),
        "batch_caveat": catalog.UNIVERSE_CAVEAT,
        "instruments": [
            {
                "symbol": i.symbol,
                "asset_class": i.asset_class.value,
                "has_daily": i.has_daily,
                "has_minute": i.has_minute,
                "rank": i.rank,
            }
            for i in found
        ],
    }


class PriceRunRequest(BaseModel):
    """What a proposed batch would cost."""

    model_config = ConfigDict(extra="forbid")

    configurations: int = Field(default=1, ge=0)
    cached: int = Field(default=0, ge=0)
    """How many of them have already been evaluated on this data version."""


@app.post("/api/run/price")
def price_run(request: PriceRunRequest) -> dict[str, Any]:
    """What this batch costs, and what it does not.

    **A batch here spends no trial.** Only `make validate` and `make gate`
    write to the ledger, and neither is reachable from this interface (T-3007).
    Saying otherwise on a button would be a false claim in the UI of a project
    whose whole premise is not making false claims in its UI.

    What it reports instead is the thing a friendlier response would leave out:
    screening is still searching. Evaluating twenty configurations here is
    twenty configurations you looked at, and the bar does not move for any of
    them. `would_move_bar_to` is the honest forecast — where the bar *would*
    stand if this search were recorded — shown so the free path cannot quietly
    become the way search gets laundered (ADR-036).
    """
    new = max(request.configurations - request.cached, 0)
    before = price_search(0, available_years=11.4).bar_after
    forecast = price_search(new, available_years=11.4).bar_after
    return {
        "logged": trial_count(),
        "configurations": request.configurations,
        "cached": request.cached,
        "new_evaluations": new,
        "spends_trials": 0,
        "bar_now": round(before, 3),
        "would_move_bar_to": round(forecast, 3),
        "unrecorded_search": new > 0,
        "note": (
            f"{new} configuration(s) would be newly evaluated. This run spends no trial — "
            f"only `make validate` and `make gate` do, and neither is reachable from here. "
            f"But the search is real: recorded, it would move the bar from {before:.2f} to "
            f"{forecast:.2f}. It will not move, and that is the gap."
            if new
            else "Every configuration is cached. Nothing new would be evaluated."
        ),
    }


# Strategies are built by `backtest.published.BUILDERS`, which is also what the
# registry declares — so a strategy cannot appear in the console without
# something able to run it, and the two cannot drift apart.


def _build_registered(strategy_id: str) -> Strategy:
    builder = PUBLISHED.get(strategy_id)
    if builder is None:
        if strategy_id == "buy_and_hold":
            return BuyAndHold(top_n=30)
        msg = f"no builder for {strategy_id!r}"
        raise KeyError(msg)
    return builder()


class BatchRunRequest(BaseModel):
    """A batch of screening runs."""

    model_config = ConfigDict(extra="forbid")

    strategies: list[str] = Field(default_factory=list)
    days: int = Field(default=800, ge=60, le=3000)
    tier: Literal["A", "B"] = "B"
    use_cache: bool = True
    workspace: str = ""
    """Which tenant's results this run belongs to. Empty means the default
    single-operator workspace (ADR-040)."""


def _as_float(payload: dict[str, object], key: str) -> float:
    """Read a number out of an untyped result payload.

    The batch runner carries results as `dict[str, object]` because a compute
    function may return anything. Rather than scatter type-ignores at each read,
    the narrowing happens once — and a non-numeric value becomes 0.0 rather
    than raising, since a malformed field must not lose the whole run.
    """
    value = payload.get(key)
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else 0.0


def _run_batch(job: Job, request: BatchRunRequest) -> None:
    """Screen each selected strategy through the same engine `make backtest` uses."""
    workspace = workspace_mod.resolve(request.workspace or None).ensure()
    try:
        job.status = "running"
        items = [
            _BatchItem(
                strategy_id=name,
                params={"days": request.days, "tier": request.tier},
            )
            for name in request.strategies
        ]

        def compute(item: _BatchItem) -> dict[str, Any]:
            declaration = REGISTRY.get(item.strategy_id)
            if declaration is None:
                msg = f"unknown strategy {item.strategy_id!r}"
                raise KeyError(msg)
            if not declaration.is_strategy_subclass:
                # Tweezer cannot go through the daily engine at all: its data
                # cannot be expressed in a MarketView (ADR-037). Refusing is
                # the honest answer; running it on daily bars would produce a
                # number for something that never happened.
                msg = (
                    f"{item.strategy_id} is not a Strategy — intraday bracket shapes "
                    f"cannot be expressed as target weights (ADR-037). Use the "
                    f"intraday surface."
                )
                raise TypeError(msg)

            rows = PANEL.rows(request.days)
            if not rows:
                msg = "no panel on disk. Run `make build-panel` first."
                raise RuntimeError(msg)

            strategy = _build_registered(item.strategy_id)
            engine = _engine_run(
                strategy,
                rows,
                days_window=request.days,
                tier=request.tier,
                starting_cash=1_000_000.0,
                rebalance=21,
            )
            if not engine.equity:
                msg = f"the {request.days}-day window is too short to produce a run"
                raise RuntimeError(msg)

            if engine.fills == 0:
                # A run that never traded is NOT a result of zero. Reporting
                # Sharpe 0.00 here would read as "no edge" when the truth is
                # "never evaluated" — the same null-versus-zero distinction the
                # fleet list depends on, and just as wrong one layer down.
                #
                # The usual cause is the window being shorter than the
                # strategy's declared lookback: the feature returns None on
                # every symbol, nothing gets ranked, and the strategy holds
                # nothing all the way through.
                needed = declaration.lookback
                msg = (
                    f"held nothing for the whole run — 0 fills. {item.strategy_id} declares a "
                    f"{needed}-period lookback and the window is {request.days} days, so its "
                    f"feature had too little history to rank anything. Widen the window past "
                    f"{needed} days."
                    if needed >= request.days
                    else (
                        "held nothing for the whole run — 0 fills. Not a zero result: the "
                        "strategy never traded, so there is nothing to measure."
                    )
                )
                raise RuntimeError(msg)

            returns = [b / a - 1.0 for a, b in pairwise(engine.equity) if a > 0]
            stats = sharpe_stats(returns)
            outcome = {
                "sharpe": round(stats.sharpe, 4),
                "total_return": round(engine.equity[-1] / 1_000_000.0 - 1.0, 6),
                "max_drawdown": round(_drawdown(engine.equity), 6),
                "fills": engine.fills,
                "costs": round(engine.costs, 2),
            }

            outcome["days"] = len(engine.days)
            return outcome

        def progress(index: int, total: int, item: _BatchItem) -> None:
            job.message = f"screened {index}/{total} — {item.strategy_id}"

        result = runner.run(items, compute, use_cache=request.use_cache, on_progress=progress)

        # Recorded from the OUTCOMES, not from inside `compute`.
        #
        # A cache hit never calls `compute`, so recording there meant a strategy
        # served from cache produced no stored result and the library kept
        # showing "not measured" for something that had demonstrably run. A
        # cached result is still a result — the same numbers, just not
        # recomputed — and the configuration key makes it supersede rather than
        # duplicate.
        for item_outcome in result.outcomes:
            if item_outcome.error or not item_outcome.result:
                continue
            payload = item_outcome.result
            result_store.record(
                workspace,
                result_store.Run(
                    strategy_id=item_outcome.item.strategy_id,
                    sharpe=_as_float(payload, "sharpe"),
                    total_return=_as_float(payload, "total_return"),
                    max_drawdown=_as_float(payload, "max_drawdown"),
                    fills=int(_as_float(payload, "fills")),
                    days=int(_as_float(payload, "days")),
                    tier=request.tier,
                    window_days=request.days,
                    data_version=batch_data_version(),
                    params=dict(item_outcome.item.params),
                    # Screening spends no trial (T-3321). The honest value, and
                    # what lets the library report how much of its own evidence
                    # the noise bar has never seen.
                    trial_recorded=False,
                ),
            )

        job.result = runner.summarise(result)
        job.status = "done"
    except Exception:
        job.status = "failed"
        job.error = traceback.format_exc(limit=3)
    finally:
        job.finished = time.time()


@app.post("/api/run/batch")
def run_batch(request: BatchRunRequest) -> dict[str, Any]:
    """Start a screening batch. Spends no trial, and says so in the result."""
    if not request.strategies:
        return {"ok": False, "error": "select at least one strategy"}
    job = Job(id=uuid.uuid4().hex[:12])
    with JOBS_LOCK:
        JOBS[job.id] = job
    threading.Thread(target=_run_batch, args=(job, request), daemon=True).start()
    return {"ok": True, "job": job.id}


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
        names = (
            tweezer_scan.universe(request.universe)
            if request.universe
            else [s.strip().upper() for s in request.symbols if s.strip()]
        )
        symbols: list[dict[str, Any]] = []
        trades: list[dict[str, Any]] = []
        rejections: dict[str, int] = {}
        candles = sessions = 0

        done = 0

        def note(result: tweezer_scan.ScanResult, index: int, total: int) -> None:
            nonlocal done
            done = index
            job.message = f"scanned {index}/{total} — {result.symbol}"

        for result in tweezer_scan.scan_many(
            names,
            start=start,
            end=end,
            rules=rules,
            equity=request.equity,
            workers=8,
            on_done=note,
        ):
            name = result.symbol
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
            "universe": request.universe or f"{len(names)} named symbols",
            "universe_note": (
                "Liquidity-ranked from our own turnover history, not index membership "
                "(ADR-008). A published constituent list exists only as it stands today, "
                "so using one across history would be survivorship bias."
                if request.universe
                else ""
            ),
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
    if not request.universe and not request.symbols:
        return {"ok": False, "error": "pick a universe or name at least one symbol"}
    if request.universe and request.universe not in tweezer_scan.UNIVERSES:
        return {
            "ok": False,
            "error": f"unknown universe; try {', '.join(sorted(tweezer_scan.UNIVERSES))}",
        }
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
