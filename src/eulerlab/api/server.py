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

import contextlib
import hashlib
import os
import statistics
import threading
import time
import traceback
import uuid
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from itertools import pairwise
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field

from eulerlab import attribution, cloud_results, last_seen, reports, strategy_results, walk_run
from eulerlab import results as result_store
from eulerlab import workspace as workspace_mod
from eulerlab.api import (
    assistant_routes,
    builder_routes,
    company_routes,
    deploy_routes,
    kite_routes,
    research_routes,
    risk_routes,
)
from eulerlab.authoring import translate
from eulerlab.authoring.sandbox import EXAMPLE, UnsafeStrategy
from eulerlab.backtest import event_driven, vector
from eulerlab.backtest.published import BUILDERS as PUBLISHED
from eulerlab.backtest.strategies import BuyAndHold
from eulerlab.backtest.strategy import Strategy
from eulerlab.batch import Item as _BatchItem
from eulerlab.batch import data_version as batch_data_version
from eulerlab.batch import runner
from eulerlab.builder import store as builder_store
from eulerlab.builder.compile import compile_spec
from eulerlab.builder.spec import is_builder_id, summarise
from eulerlab.features import company as company_digest
from eulerlab.features.library import BY_NAME
from eulerlab.features.panel import PanelRow, trading_days
from eulerlab.ingest.cloud import load_storage_config
from eulerlab.intraday import adopted as adopted_mod
from eulerlab.intraday import scan as tweezer_scan
from eulerlab.intraday.paper_scan import ALL_SIGNALS as PAPER_SIGNALS
from eulerlab.intraday.tweezer import Rules
from eulerlab.llm import client
from eulerlab.market_history import INDEX_UNIVERSE, index_panel_rows
from eulerlab.research.budget import price_search, searches_run
from eulerlab.strategies import REGISTRY, AssetClass, Timeframe, catalog, paper_url
from eulerlab.strategies import archive as strategy_archive
from eulerlab.strategies import fleet as strategy_fleet
from eulerlab.strategies import studies as strategy_studies
from eulerlab.validation import montecarlo
from eulerlab.validation.ledger import count as trial_count
from eulerlab.validation.ledger import sharpe_dispersion
from eulerlab.validation.statistics import sharpe_stats

INTRADAY_RUNNABLE = frozenset({*PAPER_SIGNALS, "tweezer_bottom"})

STUDY_RUNNABLE = frozenset({"nifty_calm_rise_overnight"})
"""Strategies that run as a calculation outside both engines (research 072):
an overnight hold in a future, which neither the daily engines nor the
minute-bar scanner can express. Runnable all the same."""
"""Strategies that are not target weights but run through the minute-bar
scanners: the paper signals, and Tweezer Bottom through its own scanner."""


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Start the auto-updater with the server and stop it on shutdown.

    The price panel and the paper books follow the data by themselves
    (deploy/autoupdate.py). `EULERLAB_AUTOUPDATE=0` switches it off.
    """
    from eulerlab.deploy import autoupdate

    stop = threading.Event()
    if autoupdate.enabled():
        threading.Thread(
            target=autoupdate.watch, args=(stop,), daemon=True, name="autoupdate"
        ).start()
    from eulerlab import telegram_bot

    # The words the operator can send the bot (`telegram_bot.COMMANDS`), all
    # read-only. `EULERLAB_TELEGRAM_BOT=0` switches the listener off.
    if telegram_bot.enabled():
        threading.Thread(
            target=telegram_bot.listen, args=(stop,), daemon=True, name="telegram-bot"
        ).start()
    # Read the price panel now, in the background, not on the first request.
    # The read takes about 19 seconds; left to the first request, the first
    # screen opened after a restart waited for all of it (29 s measured
    # 2026-10-12). `EULERLAB_PRELOAD=0` switches this off.
    if os.environ.get("EULERLAB_PRELOAD", "1") != "0":
        threading.Thread(target=_preload, daemon=True, name="panel-preload").start()
    try:
        yield
    finally:
        stop.set()


def _preload() -> None:
    try:
        PANEL.rows()
        # The market's line on the Strategies table scans the panel file for
        # one symbol, 3.3 s, and the first Strategies screen waited for it.
        from eulerlab import benchmark

        benchmark._nifty_closes()
    except Exception:  # a missing or broken panel is reported by the routes that need it
        pass
    # The bucket listings the Options and Instruments screens need. The first
    # listing of a tree cannot be skipped (8 s each, measured), so it is done
    # here and not by whoever opens those screens first.
    for warm in (options_days, instruments):
        with contextlib.suppress(Exception):
            warm()


app = FastAPI(title="EulerLab", version="0.1.0", lifespan=_lifespan)
app.include_router(builder_routes.router)
app.include_router(research_routes.router)
app.include_router(deploy_routes.router)
app.include_router(assistant_routes.router)
app.include_router(company_routes.router)
app.include_router(kite_routes.router)
app.include_router(risk_routes.router)

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


# Panels moved to `api/panels`: 145 lines of data access inside an HTTP module,
# in the same file as cost routing, report building and job management.
from eulerlab.api.panels import (  # noqa: E402
    PANEL,
    _no_panel_message,
    _rows_for,
    cost_mode_for,
)

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

    timeframe: int = Field(default=15, ge=1, le=60)
    """Candle minutes. The operator's report scans 15, 30 and 60."""

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
    symbols: int = 0
    """Distinct instruments that actually traded, counted from the fills."""

    fill_rows: Sequence[reports.FillLike] = ()
    """The fills themselves, for the report's order ledger and attribution.

    A Sequence rather than a list because Tier A and Tier B have separate fill
    types with no common ancestor; `list` is invariant, so only a covariant
    container accepts either against the protocol.
    """

    rejection_rows: tuple[tuple[str, str, str], ...] = ()

    closes: Mapping[str, Mapping[date, float]] = field(default_factory=dict)
    """The back-adjusted closes the engine marked at, per symbol.

    The report measures each trade's MAE and MFE against these, so a trade's
    worst point is read from the same prices that moved the equity curve.
    """

    marks: dict[str, float] = field(default_factory=dict)
    """The prices the engine valued open positions at on the last day.

    Taken from the engine rather than rebuilt. Reconstructing them went wrong
    twice — raw `PanelRow.close` instead of the adjusted price, then an index
    whose symbol set did not match the engine's — and each time the report's
    attribution missed the result it was decomposing. Asking the engine what it
    used removes the class of error rather than the instance.
    """


def _engine_run(
    strategy: Strategy,
    rows: list[PanelRow],
    *,
    days_window: int,
    tier: str,
    starting_cash: float,
    rebalance: int,
    universe: str = "all",
    cost_mode: str = "realistic",
    asset_class: str,
    span: tuple[date, date] | None = None,
) -> _EngineRun:
    """The one place this API calls an engine.

    Extracted so a single backtest and a screening batch cannot drift apart —
    the same reasoning as T-2501, which pulled `plan_orders` out so the
    backtest and paper paths shared one implementation. A second path to a
    number is a second answer.
    """
    days = trading_days(rows)
    warmup = warmup_for(len(days))
    index = PANEL.index(days_window, rows, universe, span=span)

    if tier == "A":
        run = vector.run(
            rows,
            strategy,
            starting_cash=starting_cash,
            asset_class=asset_class,
            rebalance_every=rebalance,
            warmup=warmup,
            adjusted_index=index,
            cost_mode=cost_mode,
        )
        return _EngineRun(
            run.equity,
            run.days,
            len(run.fills),
            0,
            run.total_cost,
            len({fill.symbol for fill in run.fills}),
            run.fills,
            marks=dict(run.final_marks),
            closes=index,
        )

    run_b = event_driven.run(
        rows,
        strategy,
        asset_class=asset_class,
        starting_cash=starting_cash,
        rebalance_every=rebalance,
        warmup=warmup,
        adjusted_index=index,
        cost_mode=cost_mode,
    )
    return _EngineRun(
        run_b.equity,
        run_b.days,
        len(run_b.fills),
        len(run_b.rejections),
        run_b.total_cost,
        len({fill.symbol for fill in run_b.fills}),
        run_b.fills,
        tuple(
            (reject.day.isoformat(), reject.symbol, reject.reason) for reject in run_b.rejections
        ),
        marks=dict(run_b.final_marks),
        closes=index,
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
        warmup = warmup_for(len(days))

        job.message = f"running tier {request.tier}"

        engine = _engine_run(
            strategy,
            rows,
            # This endpoint has no asset-class field: it is the single-backtest
            # path and has only ever run the NSE panel. Stated rather than
            # inherited, so adding a class to the request is a visible change
            # here rather than a silent one.
            asset_class="equity",
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


def _latest_sharpe(tenant: workspace_mod.Workspace, row: Any) -> float | None:
    """A strategy's most recent backtest Sharpe, or None if it has never run.

    The latest rather than the best: a maximum over configurations is a biased
    estimate of any one of them, and the most recent run is simply a
    measurement. None, never zero — zero is a measurement meaning no edge,
    None means nobody looked, and the library renders them differently.
    """
    recent = result_store.latest(tenant, row.declaration.id)
    return round(recent.sharpe, 4) if recent else None


def _clears(
    tenant: workspace_mod.Workspace,
    row: Any,
    bar: float,
    adopted_results: dict[str, dict[str, Any]] | None = None,
) -> bool:
    """Whether the strategy's headline Sharpe clears the noise bar.

    Judged on the **same** number the row displays. It previously read the
    stored Sharpe while the row showed the adopted one, so `orb_breakout` could
    display 3.54 against a bar of 1.88 and be flagged as not clearing, while
    `gap_continuation` showed 3.44 and was flagged as clearing. Two strategies,
    the same rule, opposite verdicts — because the verdict and the number came
    from different runs.
    """
    value = _headline_sharpe(tenant, row, adopted_results or {})
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
    # Read once for the whole payload rather than per strategy: it is one small
    # file and thirty-two reads of it would be thirty-two parses.
    # Both kinds from the one file that holds them. Two files with an identical
    # schema meant the comparison below was encoded as a directory listing.
    adopted_results = strategy_results.by_kind(strategy_results.HOME)
    us_all_results = strategy_results.by_kind(strategy_results.US_CROSS)
    # Walk-forward and PBO, where one has been run. The only evidence here that
    # is out of sample, so it belongs beside the Sharpe rather than behind a
    # separate screen.
    walks = walk_run.read()
    payload = _fleet_payload(tenant, bar, dispersion, adopted_results, us_all_results, walks)
    put_away = strategy_archive.read(tenant)
    for item in payload["strategies"]:
        item["table"] = _table_figures(tenant, item, bar)
        # Hidden from the library's default view and nothing else (ADR-069).
        item["archived"] = item["id"] in put_away
    payload["market"] = _market_line()
    return payload


class ArchiveRequest(BaseModel):
    ids: list[str]
    archived: bool = True
    workspace: str = ""


@app.post("/api/strategies/archive")
def archive_strategies(request: ArchiveRequest) -> dict[str, Any]:
    """Put strategies away, or bring them back. Results and trials are untouched."""
    tenant = workspace_mod.resolve(request.workspace or None)
    try:
        held = strategy_archive.change(tenant, request.ids, archived=request.archived)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "archived": sorted(held)}


def _fleet_payload(
    tenant: workspace_mod.Workspace,
    bar: float,
    dispersion: Any,
    adopted_results: dict[str, dict[str, Any]],
    us_all_results: dict[str, dict[str, Any]],
    walks: dict[str, Any],
) -> dict[str, Any]:
    from eulerlab.deploy.runner import paper_blocker

    measured: dict[str, list[strategy_results.Row]] = {}
    for result in strategy_results.load():
        measured.setdefault(result.strategy_id, []).append(result)
    return {
        "bar": round(bar, 3),
        # The denominator the bar was actually computed from. The console used
        # to sum each strategy's own trial count and present that total as the
        # bar's basis — 20 against a bar derived from 211 — which stated a
        # relationship between two numbers that did not hold.
        "bar_trials": searches_run(),
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
                # Whether the interface can actually run it. Not the same as
                # satisfying the Strategy interface: the intraday signals
                # cannot be expressed as target weights (ADR-037) and still run
                # perfectly well through the minute-bar scanner. Conflating the
                # two left eleven coded strategies greyed out.
                "runnable": (
                    row.declaration.is_strategy_subclass
                    or row.declaration.id in INTRADAY_RUNNABLE
                    or row.declaration.id in STUDY_RUNNABLE
                ),
                "engine": (
                    "intraday"
                    if row.declaration.id in INTRADAY_RUNNABLE
                    else "overnight"
                    if row.declaration.id in STUDY_RUNNABLE
                    # A paper run by its own make target; the library shows
                    # its stored results and cannot run it (`studies.py`).
                    else "study"
                    if row.declaration.id in strategy_studies.IDS
                    else "daily"
                ),
                # Read by the Deploy button on each row: the same rule the
                # deploy route enforces (`deploy.runner.paper_blocker`).
                "deploy_blocker": paper_blocker(row.declaration.id),
                "source": row.declaration.source,
                "published": row.declaration.published,
                "logic": list(row.declaration.logic),
                "stage": row.stage.value,
                # The ledger's Sharpe (a validated result) takes precedence over
                # a screened one: it is the stronger claim and was paid for.
                # `result` carries the backtest figure and, inseparably, how
                # many runs it was the best of.
                "sharpe": _headline_sharpe(tenant, row, adopted_results),
                "result": result_store.summary(tenant, row.declaration.id),
                # The run on the parameters the strategy actually uses, on the
                # market its paper tested. For a swept strategy this is the
                # result — the `result` field above is the daily engine's, which
                # for an intraday signal is a stale run on the wrong market.
                "adopted": adopted_results.get(row.declaration.id),
                # The same strategy on QQQ, whatever market its paper used.
                # Null when it has no intraday form. For a strategy whose home
                # market *is* US this repeats the run above on QQQ specifically,
                # which is not redundant: `orb_in_play` is measured on SPY at
                # home and returns a very different number on QQQ.
                "on_us": us_all_results.get(row.declaration.id),
                "walk": walks.get(row.declaration.id),
                # Which market this signal does best on, derived at read time
                # from the runs already stored. Not a stored verdict: the
                # comparison is two numbers and a `max`, and freezing it would
                # create a third thing to keep in sync with the two it came
                # from.
                "best_asset": _best_asset(
                    row.declaration.id, adopted_results, us_all_results, measured
                ),
                "trials": row.trials,
                "clears_bar": _clears(tenant, row, bar, adopted_results),
            }
            for row in strategy_fleet(tenant.ledger)
        ]
        + [_builder_row(tenant, spec, bar) for spec in builder_store.all_specs(tenant)],
    }


def _table_figures(
    tenant: workspace_mod.Workspace, item: dict[str, Any], bar: float
) -> dict[str, Any]:
    """What one row of the Strategies table shows, in plain terms.

    The verdict is the bar's judgement put in words, not a new rule: "beats the
    bar" is exactly `clears_bar`; "positive, not proven" is a positive Sharpe
    and return that luck could explain; "loses money" is a negative return.
    Annual return and the Nifty comparison are over the period the report says
    the strategy actually traded, so a strategy that needed five years of
    warm-up is not compared with ten years of the index.
    """
    from datetime import date as _date

    from eulerlab import benchmark

    result = item.get("result") or {}
    sharpe = item.get("sharpe")
    total = result.get("total_return")
    figures: dict[str, Any] = {
        "annual_return": None,
        "trades": None,
        "win_rate": None,
        "period": [None, None],
        "nifty_return": None,
    }
    configuration = result.get("configuration")
    if configuration:
        figures.update(reports.headline(tenant, str(item["id"]), str(configuration)))
    start, end = figures["period"]
    if start and end and total is not None:
        years = (_date.fromisoformat(end) - _date.fromisoformat(start)).days / 365.25
        if years > 0.25 and total > -1:
            figures["annual_return"] = round((1 + float(total)) ** (1 / years) - 1, 4)
        adopted = item.get("adopted") or {}
        ran_on = adopted.get("market") or result.get("asset_class") or item.get("asset_class")
        if ran_on == "equity":
            nifty = benchmark.nifty_return(_date.fromisoformat(start), _date.fromisoformat(end))
            figures["nifty_return"] = round(nifty, 4) if nifty is not None else None
    if sharpe is None:
        verdict = "not_run"
    elif item.get("clears_bar"):
        verdict = "beats_bar"
    elif (total is None or total > 0) and sharpe > 0:
        verdict = "positive"
    else:
        verdict = "loses"
    figures["verdict"] = verdict
    return figures


def _market_line() -> dict[str, Any]:
    """The index over the whole panel, for the page's one-line headline."""
    from datetime import date as _date

    from eulerlab import benchmark

    start, end = _date(2016, 1, 1), datetime.now(UTC).date()
    value = benchmark.nifty_return(start, end)
    return {"symbol": "NIFTYBEES", "since": start.isoformat(), "total_return": value}


def _builder_row(tenant: workspace_mod.Workspace, spec: Any, bar: float) -> dict[str, Any]:
    """A saved builder strategy, in the shape the Strategies page lists.

    Judged on its latest stored run like any other strategy, against the same
    bar. It has no paper, no adopted sweep and no ledger trials of its own.
    """
    result = result_store.summary(tenant, spec.id)
    sharpe = result.get("sharpe")
    return {
        "id": spec.id,
        "title": spec.name,
        "summary": spec.description or " ".join(summarise(spec)[1:3]),
        "kind": "builder",
        "shape": "rules",
        "asset_class": spec.universe.asset_class,
        "timeframe": "daily",
        "emits": "weights",
        "lookback": spec.warmup(),
        "risk_manager": "",
        "trade_manager": "",
        "is_strategy_subclass": True,
        "runnable": True,
        "engine": "daily",
        "source": "",
        "published": "",
        "logic": summarise(spec)[1:],
        "stage": "backtested" if sharpe is not None else "registered",
        "sharpe": sharpe,
        "result": result,
        "adopted": None,
        "on_us": None,
        "walk": None,
        "best_asset": None,
        "trials": 0,
        "clears_bar": sharpe is not None and float(sharpe) >= bar,
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
def instruments(
    q: str = "", batch: str = "", limit: int = 60, asset_class: str = ""
) -> dict[str, Any]:
    """Search instruments across every asset class that has data on disk."""
    try:
        found = catalog.search(q, batch=batch, limit=limit, asset_class=asset_class)
    except (ValueError, FileNotFoundError) as exc:
        return {"ok": False, "error": str(exc), "instruments": []}
    return {
        "ok": True,
        "batches": sorted(catalog.UNIVERSE_FILES),
        "batch_caveat": catalog.UNIVERSE_CAVEAT,
        # One entry per class, not per (class, timeframe) — the matrix has three
        # equity rows and two crypto rows, and a picker wants classes.
        "asset_classes": list(
            dict.fromkeys(c.asset_class.value for c in catalog.capabilities() if c.supported)
        ),
        "instruments": [
            {
                "symbol": i.symbol,
                "asset_class": i.asset_class.value,
                "has_daily": i.has_daily,
                "has_minute": i.has_minute,
                "rank": i.rank,
                "name": i.name,
                "detail": i.detail,
            }
            for i in found
        ],
    }


IST = ZoneInfo("Asia/Kolkata")
"""Market time. The intraday window is defined in the market's day, not the
server's."""

ALL_INSTRUMENTS = "all"
"""Every symbol in the panel.

Not one of `catalog.UNIVERSE_FILES` — those are liquidity-ranked lists, and the
panel is wider than any of them. Named explicitly because it is what every run
did before the selector existed, and leaving it unnamed would make those
results look as though nobody knew what they ran on.
"""


CUSTOM_UNIVERSE = "custom"
"""A hand-picked instrument list rather than a named batch.

Recorded under its own name so a custom run is never confused with a named one.
The instruments themselves go into the configuration hash, so two different
hand-picked lists are two different results rather than both being "custom".
"""


def _universe_rows(
    rows: list[PanelRow],
    universe: str,
    instruments: Sequence[str] = (),
    *,
    whole_panel: bool = False,
) -> tuple[list[PanelRow], int, list[str]]:
    """Restrict the panel to a universe or an explicit instrument list.

    Returns the rows, the size of what was asked for, and the resolved symbol
    list. The third value matters for a custom run: it is what the report shows
    when the universe name alone says nothing.
    """
    if universe == INDEX_UNIVERSE:
        # Index levels, not stocks: read from the index history, over the same
        # window as the panel rows the request asked for.
        kept = index_panel_rows(instruments, since=rows[0].day if rows else None)
        if not kept:
            msg = "no index history on disk. Run `make market-history` first."
            raise RuntimeError(msg)
        return kept, len(instruments), sorted({row.symbol for row in kept})
    if instruments:
        wanted = sorted({symbol.strip().upper() for symbol in instruments if symbol.strip()})
        kept = [row for row in rows if row.symbol in set(wanted)]
        if not kept:
            missing = ", ".join(wanted[:5])
            msg = (
                f"none of the {len(wanted)} chosen instruments are in the panel "
                f"(checked {missing}...). Nothing to run."
            )
            raise RuntimeError(msg)
        found = sorted({row.symbol for row in kept})
        return kept, len(wanted), found
    if whole_panel or universe == ALL_INSTRUMENTS:
        return rows, len({row.symbol for row in rows}), []
    symbols = set(catalog.universe(universe))
    kept = [row for row in rows if row.symbol in symbols]
    if not kept:
        msg = (
            f"no panel rows for any of the {len(symbols)} symbols in {universe!r}. "
            f"The universe and the panel do not overlap, so there is nothing to run."
        )
        raise RuntimeError(msg)
    return kept, len(symbols), []


@app.get("/api/universes")
def universes() -> dict[str, Any]:
    """Every universe a backtest can be pointed at, with its size.

    `all` is listed first and is the default because it is what every existing
    result ran on. It is also the widest and least liquid, which is stated
    rather than left for the reader to discover — the cost model is calibrated
    on traded names, so a universe full of rarely-traded ones understates costs.
    """
    out: list[dict[str, Any]] = [
        {
            "name": ALL_INSTRUMENTS,
            "symbols": PANEL.coverage()["symbols"],
            "recommended": False,
            "note": (
                "Every symbol in the panel. What every result so far ran on, and the "
                "widest — it includes rarely-traded names whose real costs the model "
                "understates."
            ),
        }
    ]
    for name in sorted(catalog.UNIVERSE_FILES):
        try:
            symbols = catalog.universe(name)
        except (ValueError, FileNotFoundError, OSError) as exc:
            out.append({"name": name, "symbols": 0, "recommended": False, "note": str(exc)})
            continue
        out.append(
            {
                "name": name,
                "symbols": len(symbols),
                "recommended": name == "nifty100",
                "note": (
                    "Liquid enough that the cost model is defensible, wide enough to rank "
                    "across. The recommended starting point."
                    if name == "nifty100"
                    else ""
                ),
            }
        )
    return {"universes": out, "default": ALL_INSTRUMENTS, "caveat": catalog.UNIVERSE_CAVEAT}


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


from eulerlab.api.requests import (  # noqa: E402
    BatchRunRequest,
    FeedRequest,
    PruneRequest,
    window_of,
)

WINDOW_WARMUP = 253
"""Trading days kept before an explicit window's start: the engine's largest
warmup (`warmup_for`), so trading begins at the start, not a year after it."""


def windowed(rows: list[PanelRow], start: date, end: date) -> list[PanelRow]:
    """Rows from `WINDOW_WARMUP` trading days before `start` through `end`.

    Until 2026-10-18 the daily batch read only `days` and ran every request
    over the panel's whole span, so `--from`/`--to` were silently ignored
    (research 113's event strategies ran 2016-2026, not 2021-2024).
    """
    days = sorted({r.day for r in rows if r.day <= end})
    first = next((i for i, d in enumerate(days) if d >= start), len(days))
    begin = days[max(0, first - WINDOW_WARMUP)] if days else start
    return [r for r in rows if begin <= r.day <= end]


ILLUSTRATION = ("ALPHA", "BETA", "GAMMA", "DELTA", "EPSILON")
ILLUSTRATION_SCORES = (0.42, 0.28, 0.11, -0.06, -0.19)
ILLUSTRATION_HELD = 2
"""A five-name universe for showing the mechanic.

Deliberately fake names and round scores, and labelled as an illustration
wherever it is rendered. The alternative — using five real tickers — would be
read as a result, and this is a diagram of a rule, not evidence of anything.

Held is 2 of 5 rather than the strategy's real `top_n`, because "hold the top
30 of 5" shows nothing. The real figure is stated beside it.
"""


def _worked_example(declaration: Any) -> dict[str, Any] | None:
    """The rule, run once on five made-up names.

    Built from the strategy's own `top_n` and feature so the prose beside the
    table cannot drift from what the code does. Returns None for shapes this
    illustration does not fit, rather than forcing one that misleads.
    """
    if declaration.shape != "cross-section":
        return None
    try:
        built = _build_registered(declaration.id)
    except (KeyError, TypeError, ValueError):
        return None
    top_n = getattr(built, "top_n", None)
    if not isinstance(top_n, int):
        return None

    weight = round(100 / ILLUSTRATION_HELD)
    return {
        "headline": (
            f"Say the universe were just five names, and on rebalance day their "
            f"{declaration.id} scores came out like this."
        ),
        "rows": [
            {"symbol": name, "score": score, "held": index < ILLUSTRATION_HELD}
            for index, (name, score) in enumerate(
                zip(ILLUSTRATION, ILLUSTRATION_SCORES, strict=True)
            )
        ],
        "held_count": ILLUSTRATION_HELD,
        "weight_pct": weight,
        "footer": (
            f"It sorts by score, keeps the top {ILLUSTRATION_HELD}, and puts {weight}% of "
            f"the account in each. Everything below the line is sold or never bought. "
            f"{BATCH_REBALANCE_DAYS} trading days later it scores again — if GAMMA has "
            f"overtaken BETA, BETA is sold and GAMMA bought, and that trade pays costs."
        ),
        "real_note": (
            f"The real rule holds the top {top_n}, not the top {ILLUSTRATION_HELD}, and "
            f"ranks the whole universe rather than five names. The scores above are made "
            f"up to show the mechanic."
        ),
    }


def _how_it_decides(declaration: Any) -> str:
    """A plain description of the rule, built from the strategy's own numbers.

    Constructed from the built strategy — `top_n`, `min_names`, the feature —
    rather than from prose kept beside it, because prose beside a number drifts
    from it and then explains a strategy the code does not implement.
    """
    try:
        built = _build_registered(declaration.id)
    except (KeyError, TypeError, ValueError):
        built = None

    top_n = getattr(built, "top_n", None)
    floor = getattr(built, "min_names", None)
    lookback = declaration.lookback

    if declaration.shape == "cross-section" and isinstance(top_n, int):
        parts = [
            f"Every {BATCH_REBALANCE_DAYS} trading days it scores each instrument in the "
            f"universe, ranks them, and holds the top {top_n} in equal weight, selling "
            f"whatever has dropped out of that list."
        ]
        if isinstance(floor, int) and floor > 0:
            parts.append(
                f"It will not trade at all unless at least {floor} instruments can be "
                f"scored on that day — so a universe near or below {floor} names leaves it "
                f"holding cash, and a single instrument short of history blocks every trade."
            )
        parts.append(
            f"Scoring needs {lookback} trading days of history per instrument, so the "
            f"first {lookback} days of any window produce no position."
        )
        return " ".join(parts)

    return (
        f"It emits {declaration.emits.value} directly rather than ranking a cross-section, "
        f"and needs {lookback} trading days of history before it can decide anything."
    )


def index_key(universe: str, resolved: Sequence[str], asset_class: str = "equity") -> str:
    """What the adjusted-price index is cached under.

    Three things have to be in it, and each was learned by breaking:

    - the **universe name**, because a nifty50 run at 800 days would otherwise
      hand its index to the next 800-day run over every symbol;
    - the **contents** of a hand-picked list rather than the word "custom",
      because every custom run at one window would otherwise share a single
      entry — a four-name run poisoned a sixty-name run with
      `KeyError: 'ULTRACEMCO'`;
    - the **asset class**, because equity, crypto and fund panels all called
      their universe "all". A crypto run built the entry and the next mutual
      fund run was handed it, failing with `KeyError: '139389'` — a scheme code
      looked up in an index of Binance pairs.

    The third is the one that would have been dangerous if the symbol spaces
    overlapped: it fails loudly only because a scheme code is not a ticker.
    """
    base = universe
    if resolved:
        digest = hashlib.sha256("\u0000".join(sorted(resolved)).encode()).hexdigest()[:16]
        base = f"{CUSTOM_UNIVERSE}:{digest}"
    return base if asset_class == AssetClass.EQUITY.value else f"{asset_class}:{base}"


def warmup_for(day_count: int) -> int:
    """Leading days discarded so features have history to compute from.

    One definition, used by the engine and by the window preview. Two copies of
    this arithmetic would let the interface promise a period the run does not
    actually cover.
    """
    return min(253, max(20, day_count // 4))


INTRADAY_SYMBOL_CAP = 12
"""How many symbols an intraday run scans.

Minute bars are ~370 per symbol per session, so a six-month scan of one symbol
reads roughly 45,000 candles. The daily engine reads a prebuilt panel; this
fetches and replays. Twelve symbols keeps a run inside a couple of minutes,
and the cap is stated in the result rather than hidden, because a signal that
fired twice across twelve names is a different claim from one that fired twice
across four hundred.
"""

INTRADAY_SESSIONS_PER_YEAR = 250


# Intraday running moved to `api/intraday_runs`: ~190 lines of engine work in
# the module that parses HTTP requests. Nothing in it knows about HTTP, which is
# why it could move and why keeping it here was arbitrary.
from eulerlab.api.intraday_runs import (  # noqa: E402
    _run_intraday,
)


def _run_params(request: BatchRunRequest) -> dict[str, object]:
    """What makes this a distinct configuration.

    `instruments` and `asset_class` are present only when they are not the
    default. An always-present key would change the configuration hash of every
    run already recorded, so re-running an unchanged equity backtest would count
    as a new configuration and inflate the denominator that prices selection
    bias — for no reason but a new dict key.
    """
    params: dict[str, object] = {
        "days": request.days,
        "tier": request.tier,
        "universe": _universe_label(request),
    }
    if request.instruments:
        params["instruments"] = sorted(request.instruments)
    if request.asset_class != AssetClass.EQUITY.value:
        params["asset_class"] = request.asset_class
    return params


def _universe_label(request: BatchRunRequest) -> str:
    """What to record as the universe. `custom` when instruments were picked."""
    return CUSTOM_UNIVERSE if request.instruments else request.universe


def _spec_params(workspace: workspace_mod.Workspace, strategy_id: str) -> dict[str, object]:
    """A builder strategy's rules, by digest, so an edit is never served from cache.

    In params rather than in the configuration hash: params feed the batch
    cache key and are stored with every run and report, so an edited strategy
    recomputes and every result names the exact rules behind it.
    """
    if not is_builder_id(strategy_id):
        return {}
    spec = builder_store.load(workspace, strategy_id)
    return {"spec": spec.digest()} if spec is not None else {}


def _as_float(payload: dict[str, object], key: str) -> float:
    """Read a number out of an untyped result payload.

    The batch runner carries results as `dict[str, object]` because a compute
    function may return anything. Rather than scatter type-ignores at each read,
    the narrowing happens once — and a non-numeric value becomes 0.0 rather
    than raising, since a malformed field must not lose the whole run.
    """
    value = payload.get(key)
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else 0.0


def _as_curve(payload: dict[str, object]) -> list[float]:
    """Read the equity curve out of an untyped result payload."""
    value = payload.get("curve")
    if not isinstance(value, list):
        return []
    return [
        float(point)
        for point in value
        if isinstance(point, int | float) and not isinstance(point, bool)
    ]


def _run_batch(job: Job, request: BatchRunRequest) -> None:
    """Screen each selected strategy through the same engine `make backtest` uses."""
    workspace = workspace_mod.resolve(request.workspace or None).ensure()
    try:
        job.status = "running"
        items = [
            _BatchItem(
                strategy_id=name,
                # `universe` belongs in params because params feed the cache
                # key. Without it a nifty50 run and a whole-panel run of the
                # same strategy share a key, and the second is served the
                # first's numbers.
                # `instruments` is present only when something was hand-picked.
                # Adding an always-present key would change the configuration
                # hash of every existing run, so re-running an unchanged
                # whole-panel backtest would count as a new configuration and
                # inflate the denominator that prices selection bias — for no
                # reason but a new dict key.
                params=_run_params(request) | _spec_params(workspace, name),
            )
            for name in request.strategies
        ]

        # Items whose result this batch has already written to the store.
        # `compute` stores, and so did the pass at the end meant for cache
        # hits: every computed result was written two or three times (T-4050).
        stored: set[int] = set()

        def compute(item: _BatchItem) -> dict[str, Any]:
            # A builder strategy is a saved spec in this workspace, not a
            # registry entry; it runs through everything below unchanged.
            custom = (
                builder_store.load(workspace, item.strategy_id)
                if is_builder_id(item.strategy_id)
                else None
            )
            declaration = REGISTRY.get(item.strategy_id)
            if declaration is None and custom is None:
                msg = f"unknown strategy {item.strategy_id!r}"
                raise KeyError(msg)
            if declaration is not None and not declaration.is_strategy_subclass:
                # Intraday signals run through the minute-bar scanner instead of
                # refusing. They still cannot satisfy the `Strategy` interface —
                # a conditional entry with a bracket is not a target weight
                # (ADR-037) — but "cannot be expressed as weights" is not the
                # same as "cannot be evaluated", and treating it as such left
                # eleven coded strategies unrunnable from the interface.
                if item.strategy_id in INTRADAY_RUNNABLE:
                    intraday = _run_intraday(item.strategy_id, request)
                    intraday["tier"] = "intraday"
                    store_one(item, intraday)
                    return intraday
                if item.strategy_id in STUDY_RUNNABLE:
                    from eulerlab.research.gap_forecast import calm_rise_run

                    # The window is the request's trailing days; the universe
                    # and asset class are the strategy's own (one future), not
                    # the request's, and the payload says so.
                    overnight = calm_rise_run(last_days=request.days)
                    overnight["curve"] = result_store.downsample(overnight["curve"])
                    return overnight
                msg = (
                    f"{item.strategy_id} is not a Strategy and has no intraday "
                    f"implementation — intraday bracket shapes cannot be expressed as "
                    f"target weights (ADR-037)."
                )
                raise TypeError(msg)

            rows = _rows_for(request.asset_class, request.days)
            if not rows:
                msg = _no_panel_message(request.asset_class)
                raise RuntimeError(msg)
            window_start, window_end = window_of(request)
            span = (window_start, window_end) if window_start and window_end else None
            if span:
                rows = windowed(rows, *span)
            rows, universe_size, resolved = _universe_rows(
                rows,
                request.universe,
                request.instruments,
                # A named equity batch means nothing to a crypto or fund panel;
                # for those the whole panel is the universe unless instruments
                # were picked.
                whole_panel=request.asset_class != AssetClass.EQUITY.value,
            )

            strategy = (
                compile_spec(custom) if custom is not None else _build_registered(item.strategy_id)
            )
            engine = _engine_run(
                strategy,
                rows,
                asset_class=request.asset_class,
                days_window=request.days,
                tier=request.tier,
                starting_cash=request.starting_cash,
                # Monthly unless the strategy decides more often: a builder
                # rule can fire on any close.
                rebalance=int(getattr(strategy, "rebalance_every", 21)),
                universe=index_key(_universe_label(request), resolved, request.asset_class),
                cost_mode=cost_mode_for(request.asset_class),
                span=span,
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
                needed = (
                    declaration.lookback
                    if declaration is not None
                    else custom.warmup()
                    if custom is not None
                    else 0
                )
                # Name the cause rather than guessing at it. There are two, and
                # they are not the same fix: a window shorter than the lookback,
                # or a universe smaller than the strategy's min_names — one
                # instrument short of history then blocks every trade. The
                # second was invisible until custom instrument lists made it
                # easy to hit, and it is what makes momentum_12_1 on nifty50
                # hold cash for three years while still reporting a Sharpe.
                floor = getattr(strategy, "min_names", 0)
                if isinstance(floor, int) and 0 < universe_size <= floor:
                    msg = (
                        f"held nothing for the whole run — 0 fills. {item.strategy_id} needs at "
                        f"least {floor} instruments it can score before it will trade, and this "
                        f"universe has {universe_size}. A single instrument short of history "
                        f"then blocks every trade. Widen the universe past {floor} names."
                    )
                elif needed >= request.days:
                    msg = (
                        f"held nothing for the whole run — 0 fills. {item.strategy_id} declares a "
                        f"{needed}-period lookback and the window is {request.days} days, so its "
                        f"feature had too little history to rank anything. Widen the window past "
                        f"{needed} days."
                    )
                elif rows and not any(row.turnover > 0 for row in rows[:2000]):
                    # Checked after min_names because that cause is specific and
                    # verifiable, and this one is broad enough to shadow it: on
                    # FX both are true at once, and the universe size is the
                    # answer that tells you what to change.
                    #
                    # Fabricating a turnover to make these run would invent the
                    # very number the ranking is supposed to read.
                    msg = (
                        f"held nothing for the whole run — 0 fills. {request.asset_class} has "
                        f"no turnover: spot FX has no consolidated volume and a mutual fund "
                        f"has no traded volume at all. Any strategy that screens on liquidity "
                        f"selects nothing here — use one that ranks on price alone."
                    )
                else:
                    msg = (
                        "held nothing for the whole run — 0 fills. Not a zero result: the "
                        "strategy never traded, so there is nothing to measure."
                    )
                raise RuntimeError(msg)

            returns = [b / a - 1.0 for a, b in pairwise(engine.equity) if a > 0]
            stats = sharpe_stats(returns)
            outcome: dict[str, Any] = {
                "sharpe": round(stats.sharpe, 4),
                "total_return": round(engine.equity[-1] / request.starting_cash - 1.0, 6),
                "max_drawdown": round(_drawdown(engine.equity), 6),
                "fills": engine.fills,
                "costs": round(engine.costs, 2),
                # What the run could choose from, and what it actually touched.
                # The second is the answer to "which instruments was this run
                # on", which the universe name alone does not give.
                "universe": _universe_label(request),
                "universe_size": universe_size,
                "symbols": engine.symbols,
                "asset_class": request.asset_class,
                "cost_mode": cost_mode_for(request.asset_class),
            }

            # The full analysis, written beside the row that summarises it and
            # keyed by the same configuration hash so the two cannot drift.
            saved = result_store.Run(
                strategy_id=item.strategy_id,
                sharpe=0.0,
                total_return=0.0,
                max_drawdown=0.0,
                fills=0,
                days=0,
                tier=request.tier,
                window_days=request.days,
                data_version=batch_data_version(),
                universe=_universe_label(request),
                asset_class=request.asset_class,
                cost_mode=cost_mode_for(request.asset_class),
                params=dict(item.params),
            )
            reports.save(
                workspace,
                reports.build(
                    strategy_id=item.strategy_id,
                    configuration=saved.configuration,
                    universe=_universe_label(request),
                    instruments=resolved,
                    tier=request.tier,
                    asset_class=request.asset_class,
                    cost_mode=cost_mode_for(request.asset_class),
                    window_days=request.days,
                    equity=engine.equity,
                    days=engine.days,
                    fills=list(engine.fill_rows),
                    rejections=list(engine.rejection_rows),
                    marks=engine.marks,
                    starting_cash=request.starting_cash,
                    closes=engine.closes,
                    params=dict(item.params),
                    data_version=saved.data_version,
                ),
            )

            outcome["days"] = len(engine.days)
            # Carried so the library can draw the run rather than describe it.
            # Downsampled here rather than in the UI so the cache stores the
            # small version and a cache hit yields the same curve.
            outcome["curve"] = result_store.downsample(engine.equity)
            store_one(item, outcome)
            return outcome

        def store_one(item: _BatchItem, payload: dict[str, Any]) -> None:
            """Make one strategy's result durable, immediately.

            Called as each item finishes rather than after the whole batch,
            because a batch that is abandoned at the job timeout used to throw
            away everything it had already computed. Ten intraday signals take
            longer than 900s together; seven of them completed, none were kept,
            and the library showed "not measured" for work that had demonstrably
            run.
            """
            run = result_store.Run(
                strategy_id=item.strategy_id,
                sharpe=_as_float(payload, "sharpe"),
                total_return=_as_float(payload, "total_return"),
                max_drawdown=_as_float(payload, "max_drawdown"),
                fills=int(_as_float(payload, "fills")),
                days=int(_as_float(payload, "days")),
                tier=str(payload.get("tier") or request.tier),
                window_days=request.days,
                universe=str(payload.get("universe") or _universe_label(request)),
                # A calculated strategy trades its own instrument whatever the
                # request named; recording the request's would file a futures
                # result as equity.
                asset_class=str(payload.get("asset_class") or request.asset_class),
                cost_mode=str(payload.get("cost_mode") or cost_mode_for(request.asset_class)),
                symbols=int(_as_float(payload, "symbols")),
                data_version=batch_data_version(),
                params=dict(item.params),
                curve=_as_curve(payload),
                # Screening spends no trial (T-3321). The honest value, and
                # what lets the library report how much of its own evidence
                # the noise bar has never seen.
                trial_recorded=False,
            )
            # Once per item per batch. A report rebuild below calls `compute`
            # again for an item already recorded; it needs the report, not a
            # second line in the log.
            if id(item) not in stored:
                result_store.record(workspace, run)
                stored.add(id(item))

            # The intraday report, filed under the hash this `Run` just
            # produced. Saved here rather than in `_run_intraday` because the
            # configuration is a property of the recorded run, and deriving it
            # anywhere else means deriving it differently.
            material = payload.get("_report")
            if isinstance(material, dict):
                reports.save(
                    workspace,
                    reports.build(
                        configuration=run.configuration,
                        params=dict(run.params),
                        data_version=run.data_version,
                        **material,
                    ),
                )

        def progress(index: int, total: int, item: _BatchItem) -> None:
            job.message = f"screened {index}/{total} — {item.strategy_id}"

        result = runner.run(items, compute, use_cache=request.use_cache, on_progress=progress)

        # A cache hit never calls `compute`, and the full report is written
        # inside it — so a cached run left the "Full analysis" button pointing
        # at nothing. The stored result was fine; only the report was missing,
        # which made the two disagree about whether the run had happened.
        #
        # The report cannot be cached alongside the outcome: it holds every
        # fill, and one is 86 KB against a few hundred bytes for the numbers.
        # So a missing report forces a recompute of that item alone —
        # self-healing, and it costs exactly what a cache miss would have.
        for item_outcome in result.outcomes:
            if item_outcome.error or not item_outcome.result:
                continue
            # Only a cache hit can be missing a report it should have. An item
            # computed in this batch has just had its chance to write one, and
            # a study has none to write; recomputing either was the whole run
            # done twice (49 s for the gap study, measured 2026-10-12).
            if not item_outcome.cached or item_outcome.item.strategy_id in STUDY_RUNNABLE:
                continue
            expected = result_store.Run(
                strategy_id=item_outcome.item.strategy_id,
                sharpe=0.0,
                total_return=0.0,
                max_drawdown=0.0,
                fills=0,
                days=0,
                tier=request.tier,
                window_days=request.days,
                data_version=batch_data_version(),
                universe=_universe_label(request),
                asset_class=request.asset_class,
                params=dict(item_outcome.item.params),
            ).configuration
            if reports.load(workspace, item_outcome.item.strategy_id, expected) is None:
                job.message = f"rebuilding report — {item_outcome.item.strategy_id}"
                compute(item_outcome.item)

        # A second pass, for cache hits only.
        #
        # `compute` stores its own result, but a cache hit never calls it — and
        # a cached result is still a result, the same numbers just not
        # recomputed. An item `compute` already stored is skipped.
        for item_outcome in result.outcomes:
            if item_outcome.error or not item_outcome.result:
                continue
            if id(item_outcome.item) in stored:
                continue
            store_one(item_outcome.item, item_outcome.result)

        summary = runner.summarise(result)
        # Every result also goes to the bucket the market data lives in.
        #
        # After the local record, never instead of it. A cloud outage must not
        # turn a completed backtest into a failed one — but it must not be
        # silent either, so the outcome travels back in the job result and the
        # interface can say the mirror is behind.
        mirrored = _mirror(workspace)
        summary["cloud"] = {
            "ok": mirrored.ok,
            "pushed": mirrored.pushed,
            "pulled": mirrored.pulled,
            "failed": mirrored.failed,
        }
        job.result = summary
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
        rules = Rules(timeframe_minutes=request.timeframe)
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


# --- deployment -------------------------------------------------------------


class PreflightRequest(BaseModel):
    """Ask whether a strategy could be deployed, and if not, exactly why not."""

    model_config = ConfigDict(extra="forbid")

    strategy: str
    workspace: str = ""
    mode: Literal["paper", "live"] = "paper"


def _credentials_present() -> tuple[bool, str]:
    """Whether broker credentials are configured — presence only.

    The values are never read into a response. Reporting that a key is set is
    useful; reporting any part of the key itself would put a secret into an
    HTTP body that the browser will cache.
    """
    required = ("ZERODHA_API_KEY", "ZERODHA_API_SECRET", "ZERODHA_ACCESS_TOKEN")
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        return False, f"not set: {', '.join(missing)}"
    return True, "all three Zerodha variables are set"


@app.post("/api/deploy/preflight")
def deploy_preflight(request: PreflightRequest) -> dict[str, Any]:
    """Every condition that must hold before a strategy can trade, checked.

    This endpoint exists because the alternative — a Deploy button that either
    works or throws — hides which of six different things was wrong. Each check
    is a real read of the registry, the ledger, the result store, the
    filesystem or the environment. None of them is assumed.

    Nothing can pass the evidence check today, and that is not a bug in the
    check. `strategies/__init__.py` derives stage from the ledger and there is
    no mechanism that promotes a strategy to `forward_testing`, because the
    forward-test stage is not built (T-3311). A strategy that has only been
    screened has no business sending orders, so the honest answer is to name
    the missing stage rather than to let it through.
    """
    tenant = workspace_mod.resolve(request.workspace or None)
    checks: list[dict[str, Any]] = []

    def check(name: str, passed: bool, detail: str, *, blocking: bool = True) -> None:
        checks.append({"name": name, "passed": passed, "detail": detail, "blocking": blocking})

    declaration = REGISTRY.get(request.strategy)
    check(
        "Strategy is registered",
        declaration is not None,
        f"{request.strategy} is in the registry"
        if declaration
        else f"no strategy named {request.strategy!r}",
    )
    if declaration is None:
        return {"ok": False, "mode": request.mode, "checks": checks, "blockers": 1}

    from eulerlab.deploy import overnight
    from eulerlab.deploy.runner import paper_blocker

    has_runner = request.strategy in overnight.STRATEGIES
    blocker = paper_blocker(request.strategy)
    check(
        "Paper trading can run it",
        not blocker,
        blocker
        or (
            "trades through its own overnight book (ADR-066)"
            if has_runner
            else "emits daily target weights, which the paper runner rebalances to"
        ),
    )

    supported = [
        c
        for c in catalog.capabilities()
        if c.asset_class == declaration.asset_class and c.timeframe == declaration.timeframe
    ]
    has_data = bool(supported) and supported[0].supported
    data_detail = supported[0].detail if supported else "no capability entry for this pair"
    if has_runner:
        # The capability table describes what the engines can read. This book
        # reads the Nifty future and index histories itself, so that is what
        # is checked: whether they hold a day a signal could trade.
        from eulerlab.api.deploy_routes import _overnight_latest

        latest = _overnight_latest()
        has_data = latest is not None
        data_detail = (
            f"Nifty future history through {latest[0]}, nearest contract {latest[1]}"
            if latest
            else "no Nifty future history. Run `make daily` first"
        )
    check("Data exists for this asset class and timeframe", has_data, data_detail)

    row = next(
        (r for r in strategy_fleet(tenant.ledger) if r.declaration.id == request.strategy), None
    )
    stage = row.stage.value if row else "unknown"
    # Paper moves no money and is how a strategy earns forward evidence, so
    # for paper the evidence checks are shown but do not block (operator,
    # 2026-10-07). For live they still block.
    evidence_blocks = request.mode == "live"
    check(
        "Cleared the gate and is forward-testing",
        stage in {"forward_testing", "live"},
        f"stage is {stage!r}. The forward-test stage is not built (T-3311), so nothing "
        f"can reach it yet — mandate.yaml holds that a strategy is dead until it clears "
        f"the gate, and a screened-only strategy has no evidence behind it"
        if stage not in {"forward_testing", "live"}
        else f"stage is {stage!r}",
        blocking=evidence_blocks,
    )

    bar = price_search(0, available_years=11.4).bar_after
    top = result_store.best(tenant, request.strategy)
    beats = top is not None and top.run.sharpe >= bar
    check(
        "Best backtest clears the noise bar",
        beats,
        f"{top.run.sharpe:.2f} against a bar of {bar:.2f}"
        + (
            f", but it is the best of {top.runs} configurations and "
            f"{top.unrecorded} of them are not in the trial ledger"
            if top.is_a_maximum
            else ""
        )
        if top
        else "never backtested in this workspace",
        blocking=evidence_blocks,
    )

    stop = workspace_mod.halted(tenant)
    check("Not halted", not stop, stop or "no kill switch is set")

    if request.mode == "live":
        present, detail = _credentials_present()
        check("Broker credentials configured", present, detail)
        check(
            "Broker adapter proven against the live API",
            False,
            "KiteBroker has never been run against the real Kite API (T-3336). Its order "
            "path is covered by tests against a fake client only, so the first live order "
            "would also be the first real exercise of that code",
        )

    blockers = sum(1 for c in checks if c["blocking"] and not c["passed"])
    return {
        "ok": blockers == 0,
        "mode": request.mode,
        "strategy": request.strategy,
        "checks": checks,
        "blockers": blockers,
    }


# --- data ---------------------------------------------------------------------


def _landing_source(name: str) -> dict[str, Any]:
    """Count what is actually on disk under one landing source."""
    root = Path("data/landing") / name
    if not root.exists():
        return {"name": name, "present": False, "files": 0, "newest": None}
    files = [p for p in root.rglob("*") if p.is_file()]
    newest = max((p.stat().st_mtime for p in files), default=0.0)
    return {
        "name": name,
        "present": True,
        "files": len(files),
        "bytes": sum(p.stat().st_size for p in files),
        "newest": datetime.fromtimestamp(newest, tz=UTC).date().isoformat() if newest else None,
    }


def _run_sync(job: Job) -> None:
    """Mirror the landing zone to B2, then recount it.

    The manifest is rebuilt at the end for the same reason `make daily` does
    it there: the counts describe what the bucket holds, so recounting before
    the upload would describe the state we just left.
    """
    import io
    from contextlib import redirect_stdout

    try:
        from eulerlab.ingest import manifest
        from eulerlab.ingest.filelock import exclusive
        from eulerlab.ingest.sync_cloud import main as sync_main

        job.status = "running"
        job.message = "mirroring the landing zone to B2"
        captured = io.StringIO()
        # Under the feed lock: a mirror during an update would upload half a
        # run and report counts that describe neither state.
        with (
            exclusive("feed", wait=False, what="Instruments → Mirror to cloud"),
            redirect_stdout(captured),
        ):
            code = sync_main([])

        uploaded = sum(
            int(line.split(":")[1].strip())
            for line in captured.getvalue().splitlines()
            if line.strip().startswith("uploaded")
        )

        job.message = "recounting the landing zone"
        saved = manifest.save(manifest.build())

        job.status = "done" if code == 0 else "failed"
        job.result = {
            "uploaded": uploaded,
            "manifest": str(saved),
            "trees": {
                name: census.files
                for name, census in sorted((manifest.load() or manifest.Manifest()).trees.items())
            },
            "log": captured.getvalue()[-4000:],
        }
        if code != 0:
            job.error = "sync reported a non-zero exit; see the log"
    except Exception as exc:
        # Broad on purpose: whatever the sync raises, the operator should read
        # it on the page rather than have the job vanish with a bare "failed".
        job.status = "failed"
        job.error = f"{type(exc).__name__}: {exc}"
    finally:
        job.finished = time.time()


def _run_feed(job: Job, only: list[str] | None = None, mirror: bool = True) -> None:
    """Fetch every source, then mirror. Individual failures do not stop the run.

    Reported per source rather than as one verdict: "the feed updated" and "the
    feed updated except for the two sources you care about" are different
    sentences, and a Makefile that swallows both says the first.
    """
    from eulerlab.ingest import daily_feed

    try:
        job.status = "running"

        def progress(index: int, total: int, name: str) -> None:
            job.message = f"{index}/{total} — {name}"

        run = daily_feed.refresh(only=only or (), on_step=progress, sync=mirror)
        _forget_derived()
        job.result = {
            "kind": "feed",
            "only": only or [],
            "mirrored": mirror,
            "summary": run.summary,
            "uploaded": run.synced,
            "sync_error": run.sync_error,
            "steps": [
                {
                    "name": step.name,
                    "ok": step.ok,
                    "detail": step.detail,
                    "seconds": round(step.seconds, 1),
                }
                for step in run.steps
            ],
        }
        job.message = run.summary
        # Failed sources are not a failed job. The run did what it could and the
        # per-step detail says what it could not — marking the whole thing
        # failed would hide the sources that did update.
        job.status = "done"
    except Exception as exc:
        job.status = "failed"
        job.message = f"{type(exc).__name__}: {exc}"[:200]
        job.error = job.message
    finally:
        job.finished = time.time()


def _forget_derived() -> None:
    """Drop the API's copies of data a feed run just rewrote.

    The equity and alt panels re-read on their own when their files change;
    the US band is a five-minute cache and would show the old session until it
    expired.
    """
    _US_CACHE.clear()


@app.get("/api/data/feed/plan")
def data_feed_plan() -> dict[str, Any]:
    """Which sources a refresh touches, from the list that actually runs.

    Served rather than written into the interface, because a hand-written
    sentence naming sources drifts from the code that fetches them — this one
    already claimed FX while the step list did not include it, which is the
    same failure as the three copies of the asset-class list.
    """
    from eulerlab.ingest.daily_feed import STEPS, TERMINAL_ONLY
    from eulerlab.ingest.filelock import holder

    return {
        "ok": True,
        "sources": [name for name, _work in STEPS],
        "excluded": [f"{name} — {why}" for name, why in TERMINAL_ONLY.items()],
        "keeps_local": True,
        "busy": holder("feed"),
    }


@app.get("/api/data/coverage")
def data_coverage() -> dict[str, Any]:
    """Every dataset: last day held, the day it should reach, and the fix.

    Read from local files only (manifests, derived tables' last lines, the
    landing census, paper states), so it answers in well under a second.
    """
    from dataclasses import asdict

    from eulerlab.ingest import coverage
    from eulerlab.ingest.filelock import holder

    rows = coverage.table()
    return {
        "ok": True,
        "rows": [asdict(r) for r in rows],
        "summary": coverage.summary(rows),
        "busy": holder("feed"),
        "checked_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }


@app.post("/api/data/feed")
def data_feed(request: FeedRequest | None = None) -> dict[str, Any]:
    """Fetch today's data from every source, then mirror it to B2.

    Different from `/api/data/sync`, which uploads whatever is already on disk.
    That button could mirror a stale landing zone to the cloud and report
    success; this one fetches first.

    Deliberately does **not** prune local files or rebuild the panels. Pruning
    is correct for an unattended disk-constrained run and surprising as the
    side effect of clicking refresh; panels are derived products and rebuilding
    them is a separate decision from fetching what they derive from.
    """
    with JOBS_LOCK:
        running = [
            j
            for j in JOBS.values()
            if j.status in ("queued", "running") and j.result.get("kind") in {"feed", "sync"}
        ]
        if running:
            return {
                "ok": False,
                "error": "a data job is already running",
                "job": running[0].id,
            }

    from eulerlab.ingest.filelock import holder

    busy = holder("feed")
    if busy:
        return {
            "ok": False,
            "error": f"another data run is going ({busy.get('what')}, since {busy.get('since')})",
        }

    request = request or FeedRequest()
    from eulerlab.ingest.daily_feed import STEPS

    known = {name for name, _work in STEPS}
    unknown = [name for name in request.only if name not in known]
    if unknown:
        return {"ok": False, "error": f"no such step: {', '.join(unknown)}"}

    job = Job(id=uuid.uuid4().hex[:12])
    job.result = {"kind": "feed", "only": request.only}
    with JOBS_LOCK:
        JOBS[job.id] = job
    threading.Thread(
        target=_run_feed, args=(job, request.only, request.mirror), daemon=True
    ).start()
    return {"ok": True, "job": job.id}


@app.post("/api/data/sync")
def data_sync() -> dict[str, Any]:
    """Start a cloud sync. Returns a job id immediately.

    A job rather than a blocking call because a full mirror takes minutes and
    an HTTP request that long is one the proxy will cut before the work
    finishes — which is how a sync ends up reported as failed while it is
    still running.

    Refuses to start a second one. Two concurrent mirrors of the same tree do
    not corrupt anything, but they double the upload and make the reported
    counts meaningless.
    """
    with JOBS_LOCK:
        running = [
            j
            for j in JOBS.values()
            if j.status in ("queued", "running") and j.result.get("kind") == "sync"
        ]
        if running:
            return {"ok": False, "error": "a sync is already running", "job": running[0].id}

        from eulerlab.ingest.filelock import holder

        busy = holder("feed")
        if busy:
            return {
                "ok": False,
                "error": f"another data run is going ({busy.get('what')}, since {busy.get('since')})",
            }

        job = Job(id=uuid.uuid4().hex[:12])
        job.result = {"kind": "sync"}
        JOBS[job.id] = job

    threading.Thread(target=_run_sync, args=(job,), daemon=True).start()
    return {"ok": True, "job": job.id}


def _run_prune(job: Job, dry_run: bool) -> None:
    """Delete (or count) local landing files that B2 holds at the same size.

    The same rule as `make prune-local`: a file goes only when the bucket
    listing shows its key at its exact size. Files not yet uploaded, or held at
    a different size, are kept and counted.
    """
    try:
        from eulerlab.ingest.cloud import S3ObjectStore, load_storage_config
        from eulerlab.ingest.filelock import exclusive
        from eulerlab.ingest.prune_local import DEFAULT_ROOT, plan_and_prune

        job.status = "running"
        job.message = "listing the bucket" if dry_run else "deleting confirmed local copies"
        with exclusive("feed", wait=False, what="Instruments → Delete local copies"):
            config = load_storage_config(Path("config/storage.yaml"))
            result = plan_and_prune(
                DEFAULT_ROOT, S3ObjectStore(config), prefix=config.prefix, dry_run=dry_run
            )
        job.result = {
            "kind": "prune",
            "dry_run": dry_run,
            "files": len(result.deleted),
            "gb": round(result.bytes_freed / 1e9, 3),
            "kept_not_uploaded": result.kept_not_uploaded,
            "kept_size_mismatch": len(result.kept_size_mismatch),
        }
        verb = "would delete" if dry_run else "deleted"
        job.message = (
            f"{verb} {len(result.deleted):,} files ({result.bytes_freed / 1e9:.2f} GB); "
            f"kept {result.kept_not_uploaded:,} not yet in B2"
        )
        if result.kept_size_mismatch:
            job.message += f", {len(result.kept_size_mismatch)} with a size mismatch"
        job.status = "done"
    except Exception as exc:
        job.status = "failed"
        job.error = f"{type(exc).__name__}: {exc}"[:200]
        job.message = job.error
    finally:
        job.finished = time.time()


@app.post("/api/data/prune")
def data_prune(request: PruneRequest) -> dict[str, Any]:
    """Count, or delete, local copies B2 already holds. Returns a job id.

    Two calls from the button: a dry run that says how many files and how much
    disk, then the confirmed delete. The manifests are never touched, so every
    deleted file is still listed as landed and is read back from B2 on demand.
    """
    from eulerlab.ingest.filelock import holder

    busy = holder("feed")
    if busy:
        return {
            "ok": False,
            "error": f"another data run is going ({busy.get('what')}, since {busy.get('since')})",
        }
    with JOBS_LOCK:
        running = [
            j
            for j in JOBS.values()
            if j.status in ("queued", "running")
            and j.result.get("kind") in {"feed", "sync", "prune"}
        ]
        if running:
            return {"ok": False, "error": "a data job is already running", "job": running[0].id}
        job = Job(id=uuid.uuid4().hex[:12])
        job.result = {"kind": "prune"}
        JOBS[job.id] = job
    threading.Thread(target=_run_prune, args=(job, request.dry_run), daemon=True).start()
    return {"ok": True, "job": job.id}


@app.get("/api/history")
def history(symbol: str, asset_class: str = "equity", days: int = 400) -> dict[str, Any]:
    """OHLC bars for one instrument, **from data this platform holds**.

    The TradingView embed refuses a great deal of what is charted here: index
    data is licensed separately from equity data, so `NSE:NIFTY` errors, and
    the ETF proxies substituted for it are close but not the same instrument.
    That is a poor foundation for a chart on a platform whose panel already
    contains the real thing.

    So this serves our own bars. Equities come from the price panel — the same
    rows a backtest reads, so a chart and a result cannot disagree — and crypto
    and FX from their landed archives. There is no licensing question because
    there is no third party.

    What it cannot serve is anything not landed: US listings, sovereign yields,
    the dollar index. Those stay on the embed, which is honest about being a
    different source.
    """
    wanted = symbol.strip().upper()
    if not wanted:
        return {"ok": False, "error": "no symbol"}

    try:
        if asset_class == "equity":
            rows = [r for r in PANEL.rows(days=days) if r.symbol == wanted]
            bars = [
                {
                    "time": row.day.isoformat(),
                    "open": row.open or row.close,
                    "high": row.high or row.close,
                    "low": row.low or row.close,
                    "close": row.close,
                    "volume": row.volume,
                }
                for row in sorted(rows, key=lambda r: r.day)
            ]
        elif asset_class in ("crypto", "fx"):
            from datetime import timedelta

            from eulerlab.features import alt_panel

            # UTC, not the machine's zone: this asks a question about landed
            # bars, and the archive is stamped in UTC.
            start = (datetime.now(UTC) - timedelta(days=days)).date()
            # Called separately rather than through one variable. The two
            # readers take different parameter names — `symbols` for crypto,
            # `pairs` for FX — and sharing a call site only hid that until the
            # type checker found it.
            if asset_class == "crypto":
                landed = alt_panel.crypto_daily(symbols=[wanted], start=start)
            else:
                landed = alt_panel.fx_daily(pairs=[wanted], start=start)
            bars = [
                {
                    "time": row.day.isoformat(),
                    "open": row.open or row.close,
                    "high": row.high or row.close,
                    "low": row.low or row.close,
                    "close": row.close,
                    "volume": row.volume,
                }
                for row in sorted((r for r in landed if r.symbol == wanted), key=lambda r: r.day)
            ]
        else:
            return {"ok": False, "error": f"no landed history for {asset_class}"}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    if not bars:
        # Named, not empty. "We hold nothing for this symbol" and "the request
        # failed" are different answers and the chart should say which.
        return {
            "ok": False,
            "error": f"no landed bars for {wanted} in the last {days} days",
            "bars": [],
        }

    return {
        "ok": True,
        "symbol": wanted,
        "asset_class": asset_class,
        "bars": bars,
        "source": "price panel" if asset_class == "equity" else f"{asset_class} archive",
        "first": bars[0]["time"],
        "last": bars[-1]["time"],
    }


@app.get("/api/paper/{strategy_id}")
def paper(strategy_id: str) -> Any:
    """The source PDF for one strategy, when it has been fetched.

    404 when the file is absent, which is the normal state: the PDFs are
    deliberately uncommitted — arXiv is a permanent archive and a 1.1 MB binary
    in git buys nothing one request does not — so
    `docs/RESEARCH/papers/fetch.sh` populates them and a fresh checkout has
    none. The message says which, so a reader is not left wondering whether
    the paper exists or the link is broken.
    """
    from fastapi.responses import FileResponse, JSONResponse

    from eulerlab.strategies import REGISTRY

    declaration = REGISTRY.get(strategy_id)
    if declaration is None or not declaration.paper_pdf:
        return JSONResponse(
            {"ok": False, "error": f"no paper recorded for {strategy_id}"}, status_code=404
        )
    path = Path(declaration.paper_pdf)
    if not path.exists():
        return JSONResponse(
            {
                "ok": False,
                "error": (
                    f"{path.name} is not fetched. Run "
                    "`docs/RESEARCH/papers/fetch.sh` to download it."
                ),
            },
            status_code=404,
        )
    return FileResponse(path, media_type="application/pdf", filename=path.name)


@app.get("/api/data")
def data_status() -> dict[str, Any]:
    """What data is on disk, counted rather than claimed.

    The panel figures come from the panel itself; the landing figures come from
    walking the directories. Nothing here is a configured expectation — if a
    source is missing, it reports missing rather than reporting its intended
    size.
    """
    panel: dict[str, Any] = {}
    try:
        # `loaded` is read AFTER the rows, not before: reading it first reports
        # the state this request walked in on, which is False on the very
        # request that loads the panel and reads as a contradiction next to
        # five million rows.
        panel |= PANEL.coverage()
        panel["loaded"] = PANEL.loaded()
    except (FileNotFoundError, OSError) as exc:
        panel |= {"error": str(exc), "rows": 0, "loaded": False}

    universes: list[dict[str, Any]] = []
    for name in sorted(catalog.UNIVERSE_FILES):
        try:
            symbols = catalog.universe(name)
        except (ValueError, FileNotFoundError, OSError) as exc:
            universes.append({"name": name, "symbols": 0, "error": str(exc)})
            continue
        universes.append({"name": name, "symbols": len(symbols)})

    return {
        "panel": panel,
        "universes": universes,
        "universe_caveat": catalog.UNIVERSE_CAVEAT,
        "sources": [
            _landing_source(name) for name in ("nse", "crypto", "mf", "fundamentals", "kite_minute")
        ],
    }


# --- cloud --------------------------------------------------------------------


class MirrorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace: str = ""


CLOUD_LISTING_TTL = 60.0
"""Seconds a bucket listing is shown before it is taken again. Another machine
or `make daily` can push meanwhile; a mirror from this server drops it at once."""

_CLOUD_LISTINGS: dict[str, tuple[float, list[str]]] = {}
"""(when listed, the file names) by bucket prefix."""


@app.get("/api/cloud/status")
def cloud_status(workspace: str = "", refresh: bool = False) -> dict[str, Any]:
    """Whether results are being mirrored, and how far behind the bucket is.

    `local` is counted from disk. `remote` is a LIST against the bucket, so
    this is a real comparison rather than a record of what the last push
    believed it did. The listing (1.3 s) is kept for `CLOUD_LISTING_TTL` and
    dropped the moment this server mirrors; `listed_at` says how old it is and
    `refresh=true` lists again (ADR-077).
    """
    tenant = workspace_mod.resolve(workspace or None)
    ready, reason = cloud_results.configured()
    local = (
        sorted(p.name for p in tenant.results.glob("*.jsonl")) if tenant.results.exists() else []
    )
    payload: dict[str, Any] = {
        "configured": ready,
        "reason": reason,
        "workspace": tenant.id,
        "bucket": "",
        "prefix": f"{cloud_results.RESULTS_PREFIX}{tenant.id}/",
        "local_files": local,
        "remote_files": [],
        "reachable": False,
    }
    if not ready:
        return payload
    try:
        config = load_storage_config(cloud_results.STORAGE_CONFIG)
        payload["bucket"] = config.bucket
        prefix = str(payload["prefix"])
        held = _CLOUD_LISTINGS.get(prefix)
        if refresh or held is None or time.time() - held[0] > CLOUD_LISTING_TTL:
            remote = cloud_results.open_store().list_sizes(prefix)
            held = (time.time(), sorted(key[len(prefix) :] for key in remote))
            _CLOUD_LISTINGS[prefix] = held
        payload["remote_files"] = list(held[1])
        payload["listed_at"] = datetime.fromtimestamp(held[0], UTC).isoformat()
        payload["reachable"] = True
    except Exception as exc:
        payload["reason"] = f"{type(exc).__name__}: {exc}"
    return payload


def _mirror(workspace: workspace_mod.Workspace) -> cloud_results.Mirror:
    """Mirror, then forget the bucket listing: it no longer says what is there."""
    try:
        return cloud_results.mirror_quietly(workspace)
    finally:
        _CLOUD_LISTINGS.clear()


@app.post("/api/cloud/mirror")
def cloud_mirror(request: MirrorRequest) -> dict[str, Any]:
    """Pull the bucket's results, merge, then push. Both copies end up equal."""
    tenant = workspace_mod.resolve(request.workspace or None).ensure()
    outcome = _mirror(tenant)
    return {
        "ok": outcome.ok,
        "pushed": outcome.pushed,
        "pulled": outcome.pulled,
        "merged_rows": outcome.merged_rows,
        "failed": outcome.failed,
    }


# --- the full report ----------------------------------------------------------


@app.get("/api/report")
def report(
    strategy: str, workspace: str = "", configuration: str = "", run: str = ""
) -> dict[str, Any]:
    """The full analysis of one run.

    Defaults to the configuration behind the strategy's best stored result, so
    the report opens on the run the library is showing. Passing `configuration`
    explicitly opens any other run of the same strategy, and `run` opens one
    earlier stored run of that configuration rather than its latest.
    """
    tenant = workspace_mod.resolve(workspace or None)
    runs = result_store.distinct(tenant, strategy)
    if not runs:
        return {"ok": False, "error": f"{strategy} has never been run in this workspace"}

    target = configuration
    if not target:
        # The latest, matching what the library shows. Opening a report on a
        # different run from the one on the row it was clicked from would be a
        # quiet mismatch.
        recent = result_store.latest(tenant, strategy)
        if recent is None:
            return {"ok": False, "error": f"{strategy} has no tradeable run to report on"}
        target = recent.configuration

    payload = reports.load(tenant, strategy, target, run)
    if payload is None:
        return {
            "ok": False,
            "error": (
                "no report stored for that run. Reports are written when a backtest runs, "
                "so a result recorded before reports existed has none — re-run it to get one."
            ),
            "runs": [_run_choice(choice) for choice in runs],
        }
    return {
        "ok": True,
        "report": payload,
        # Where the return came from: holdings, sectors, years, market (`attribution`).
        "attribution": attribution.analyse(payload),
        "runs": [_run_choice(choice) for choice in runs],
        "history": reports.history(tenant, strategy, target),
    }


@app.get("/api/report/attribution")
def report_attribution(
    strategy: str, workspace: str = "", configuration: str = "", run: str = ""
) -> dict[str, Any]:
    """The detailed attribution of one stored run (research 115).

    Rebuilds the daily book from the fills, so the first call for a run takes
    about a minute (the monthly base is built once for every run); later calls
    for the same run are cached.
    """
    from eulerlab import attribution_detail

    tenant = workspace_mod.resolve(workspace or None)
    target = configuration
    if not target:
        recent = result_store.latest(tenant, strategy)
        if recent is None:
            return {"ok": False, "error": f"{strategy} has no run to attribute"}
        target = recent.configuration
    payload = reports.load(tenant, strategy, target, run)
    if payload is None:
        return {"ok": False, "error": "no report stored for that run"}
    key = f"{strategy}|{target}|{run}|{payload.get('final_equity')}|{len(payload.get('orders') or [])}"
    try:
        detail = attribution_detail.analyse_detail(payload, key=key)
    except Exception as exc:  # one view failing must say so, not take the page down
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]}
    return {"ok": True, "detail": detail}


def _run_choice(run: result_store.Run) -> dict[str, Any]:
    """One selectable run, for the report's run switcher."""
    return {
        "configuration": run.configuration,
        "sharpe": round(run.sharpe, 4),
        "tier": run.tier,
        "window_days": run.window_days,
        "universe": run.universe,
        "symbols": run.symbols,
        "at": run.at,
    }


# --- what any of this means ---------------------------------------------------

# Starting cash and rebalance cadence are the batch runner's, read from one
# place so this endpoint cannot describe a run the engine does not perform.
BATCH_STARTING_CASH = 1_000_000.0
BATCH_REBALANCE_DAYS = 21


@app.get("/api/tuning")
def tuning_result(strategy: str) -> dict[str, Any]:
    """A recorded parameter sweep for one strategy, chosen on in-sample years
    and tested once on a holdout. Read-only; research 067."""
    from eulerlab.tuning_view import tuning

    found = tuning(strategy)
    return {"ran": False, "strategy": strategy} if found is None else {"ran": True, **found}


@app.get("/api/optimize")
def optimize_results() -> dict[str, Any]:
    """The last parameter sweep, as it was recorded.

    Read-only, and there is deliberately no endpoint that starts a sweep. Every
    candidate a sweep evaluates spends a permanent trial against the
    deflated-Sharpe denominator, which raises the bar for every result this
    platform holds; that is not a thing to put behind a button in a web page.
    Sweeps are started from `make optimize` by an operator who meant to.

    Each row carries its median beside its best, because the maximum of N draws
    from noise rises with N and a sweep reporting only its winner has found the
    right tail of a sample.
    """
    from eulerlab import optimize_store
    from eulerlab.strategies import REGISTRY, paper_pdf, paper_url

    latest = optimize_store.latest()
    if latest is None:
        return {
            "ran": False,
            "note": "no sweep recorded yet — run `make optimize`",
            "rows": [],
        }

    rows: list[dict[str, Any]] = []
    for row in latest.get("rows", []):
        strategy_id = str(row.get("strategy_id", ""))
        declaration = REGISTRY.get(strategy_id)
        median = float(row.get("median_pnl") or 0.0)
        best = float(row.get("best_pnl") or 0.0)
        rows.append(
            {
                **row,
                "title": declaration.title if declaration else strategy_id,
                "source": declaration.source if declaration else "",
                "tested_on": declaration.tested_on if declaration else "",
                # Keyed on the citation text, not the id. Passing the id
                # returns empty for everything, which is how this shipped once.
                "paper_url": paper_url(declaration.source) if declaration else "",
                "paper_pdf": (
                    f"/api/paper/{strategy_id}"
                    if declaration and paper_pdf(declaration.source)
                    else ""
                ),
                # Reported only when the median is positive. A ratio taken
                # against a losing median is arithmetic without meaning, and it
                # is exactly the direction that would flatter: -100 over -110
                # reads as a tidy 0.9 for a strategy that lost on every leg.
                "spread_ratio": (best / median) if median > 0 else None,
                "profitable": best > 0,
                "beats_its_median_by": best - median,
            }
        )

    return {
        "ran": True,
        "at": latest.get("at", ""),
        "start": latest.get("start", ""),
        "end": latest.get("end", ""),
        "dry_run": bool(latest.get("dry_run", False)),
        # False while a sweep is still running. Partial results are real and
        # worth showing, but a reader has to know they are looking at nine
        # strategies of twenty rather than a library where eleven were skipped.
        "complete": bool(latest.get("complete", True)),
        "trials_before": latest.get("trials_before", 0),
        "trials_after": latest.get("trials_after", 0),
        "required_t": latest.get("required_t", 0.0),
        "skipped": latest.get("skipped", []),
        "rows": rows,
    }


def _best_asset(
    strategy_id: str,
    adopted_results: dict[str, dict[str, Any]],
    us_all_results: dict[str, dict[str, Any]],
    measured: dict[str, list[strategy_results.Row]] | None = None,
) -> dict[str, Any] | None:
    """The market this signal performs best on, of the ones it has been run on.

    `measured` is every result grouped by strategy, read once by the caller.
    Without it the results file was read again for each of 69 strategies.

    Compares the home-market run against the US cross-test and returns the
    better, with a flag for whether that is the market its paper used.

    Derived rather than stored. It is a `max` over two numbers that already
    exist; writing it down would make a third artefact to keep in step with the
    two it is computed from, and the failure mode of a stale verdict here is a
    strategy tagged for a market it no longer wins on.

    `session_momentum` is why this is worth showing at all: its paper is crypto,
    it loses badly on BTCUSDT, and it makes money on QQQ. Nothing in the row
    said so — the reader had to open the drawer and compare two panels.
    """
    # Every measurement of this strategy, whatever question it answered. Asking
    # the store rather than naming two dicts means a third kind — the same
    # signal on a third market — needs no change here.
    rows = (
        strategy_results.for_strategy(strategy_id)
        if measured is None
        else measured.get(strategy_id, [])
    )
    candidates = [row.data for row in rows if row.sharpe is not None]
    if not candidates:
        return None

    best = max(candidates, key=lambda r: float(r["sharpe"]))
    home = adopted_results.get(strategy_id)
    return {
        "market": best.get("market", ""),
        "symbol": best.get("symbol", ""),
        "sharpe": float(best["sharpe"]),
        "net_pnl": float(best.get("net_pnl") or 0.0),
        # True when the best market is not the one its paper tested, which is
        # the case worth surfacing rather than the case worth assuming.
        "is_away": bool(home and best.get("symbol") != home.get("symbol")),
        "beats": len(candidates),
    }


def _headline_sharpe(
    tenant: Any, row: Any, adopted_results: dict[str, dict[str, Any]]
) -> float | None:
    """The Sharpe a strategy should be judged on.

    For a swept intraday signal that is the run on its adopted parameters, on
    the market its paper tested. It takes precedence over the stored figure
    because the stored one predates both: `gap_continuation` showed 1.89 from a
    run on NSE bars with the published parameters, while the strategy as it now
    exists runs on QQQ with a tuned stop. Showing the old number beside the new
    description is how a page lies without containing a false sentence.

    **But a run the operator just executed wins.** This preferred the adopted
    result unconditionally, so backtesting a strategy over a longer window
    stored the run, wrote its report, and changed nothing on screen — the row
    kept showing the adopted figure and the work looked like it had not
    happened. Recency decides between the two: the adopted result is what a
    strategy shows until someone asks it a newer question.

    Everything else keeps the previous order: the ledger's validated Sharpe
    first, since it is the stronger claim and was paid for, then the most
    recent screened one.
    """
    adopted_row = adopted_results.get(row.declaration.id)
    adopted_sharpe = adopted_row.get("sharpe") if adopted_row else None

    latest = result_store.latest(tenant, row.declaration.id)
    # A stored run counts as newer only if it is genuinely later *and* is not
    # the adopted run itself — `adopted_run` records one, so comparing without
    # this would have the adopted result perpetually superseding itself.
    newer_run = (
        latest is not None
        and latest.universe != "adopted"
        and adopted_row is not None
        and str(latest.at) > str(adopted_row.get("at", ""))
    )
    if newer_run and latest is not None:
        return latest.sharpe
    if adopted_sharpe is not None:
        return float(adopted_sharpe)
    return row.sharpe if row.sharpe is not None else _latest_sharpe(tenant, row)


def _tuning(strategy_id: str) -> dict[str, Any] | None:
    """The parameters a recorded sweep adopted for this strategy, and its evidence.

    Returns None when no recorded sweep has covered it, which is different from
    a sweep that found nothing — that case returns a record with `adopted`
    false and the reason. "Never looked" and "looked and found nothing" are
    different facts and the page says which one applies.
    """
    from eulerlab.intraday import tuned

    adoption = tuned.for_strategy(strategy_id)
    if adoption is None:
        return None

    return {
        "adopted": adoption.adopted,
        "reason": adoption.reason,
        "symbol": adoption.symbol,
        "market": adoption.market,
        "swept_at": adoption.swept_at,
        "candidates": adoption.candidates,
        "fills": adoption.fills,
        "sessions": adoption.sessions,
        "best_pnl": adoption.best_pnl,
        "median_pnl": adoption.median_pnl,
        "tail_share": adoption.tail_share,
        # Only the fields the sweep actually moved. A grid often lands on the
        # paper's value for one of its two parameters, and listing that as a
        # change would overstate what was found.
        "changed": [
            {"name": name, "paper": paper, "adopted": value}
            for name, (paper, value) in sorted(adoption.changed.items())
        ],
        "params": adoption.params,
        "paper_params": adoption.paper_params,
        # Stated on the page rather than left to be inferred. None of these
        # clears the platform's own bar, and several rest on fewer than twenty
        # fills; a tuned parameter is the better guess of the ones tried, not
        # a result.
        "caveat": (
            f"Chosen as the best of {adoption.candidates} settings over "
            f"{adoption.sessions} sessions on {adoption.symbol}, with "
            f"{adoption.fills} fills. The maximum of {adoption.candidates} draws "
            "rises with the count whether or not anything real is there, which is "
            "why the median is shown beside the best. This does not clear the "
            "platform's bar of t > 3.0 and is not a validated result."
        ),
    }


@app.get("/api/explain")
def explain(strategy: str = "") -> dict[str, Any]:
    """What a backtest here actually does, and what this strategy is.

    Every number in the procedure section is the value the engine uses, not a
    description of what it might use. A page that explains a run the code does
    not perform is worse than no explanation.
    """
    # Which engine ran matters more than any other fact on this page. An
    # intraday signal never produces target weights and never rebalances — ADR-037
    # is explicit that a bracket trade cannot be expressed as one — so describing
    # the daily engine to someone reading an intraday result explains a run the
    # code did not perform. This module's own docstring calls that worse than no
    # explanation, and it was doing it for all twenty swept signals.
    intraday = bool(strategy) and strategy in INTRADAY_RUNNABLE
    overnight = bool(strategy) and strategy in STUDY_RUNNABLE

    procedure: list[dict[str, str]]
    if overnight:
        procedure = [
            {
                "title": "What a backtest here is",
                "body": (
                    "This strategy holds one instrument, the near-month Nifty future, "
                    "from a signal day's close to the next morning's open. Neither "
                    "engine can do that: both fill a decision at the next close. So it "
                    "is a calculation over the daily history, not an engine run "
                    "(research 072). There is no rebalance and there are no weights."
                ),
            },
            {
                "title": "Where the prices come from",
                "body": (
                    "The signal reads the Nifty 50 index and India VIX. The trade is "
                    "priced on the future's own close and next open, from the F&O "
                    "bhavcopy, using the nearest contract still alive the next morning "
                    "so that no night spans a roll. The index is not used for the trade: "
                    "its open is built from first prints and its close from a 30-minute "
                    "average, which makes its gaps look larger than anything tradable."
                ),
            },
            {
                "title": "What the costs are",
                "body": (
                    "One futures round trip for every night held, from the dated cost "
                    "schedule: brokerage, STT on the sale (0.0125%, 0.02% from October "
                    "2024, 0.05% from April 2026), exchange and SEBI charges, stamp duty "
                    "and GST. The position is fully paid for, so a 1% move is a 1% return."
                ),
            },
            {
                "title": "What it assumes",
                "body": (
                    "That the day's Nifty and VIX closes are known when the order is "
                    "placed at the close. In practice the order goes in a few minutes "
                    "before, on values that are almost final (A-046)."
                ),
            },
        ]
    elif intraday:
        from eulerlab.intraday.paper_scan import WARMUP_BARS

        procedure = [
            {
                "title": "What a backtest here is",
                "body": (
                    "This is an intraday signal, so there is no rebalance and there are "
                    "no target weights. Every bar of every session is offered to the "
                    "signal, which either declines with a reason or returns one fully "
                    "specified bracket — an entry, a stop and a target, sized so the "
                    "distance to the stop is a fixed fraction of the account. The "
                    "bracket is then walked forward bar by bar until the stop, the "
                    "target, or the close takes it out. Nothing is held overnight."
                ),
            },
            {
                "title": "Why the rejections are counted",
                "body": (
                    "A signal that declines 12,000 times and fires twice is a different "
                    "object than one that fires constantly, and the two can report the "
                    "same P&L. Each refusal is tallied by reason, so 'no setup' and "
                    "'not enough history' are never confused with each other."
                ),
            },
            {
                "title": "Warmup",
                "body": (
                    f"The first {WARMUP_BARS} bars of the range are skipped so indicators "
                    "have history. A signal needing more says so itself by returning a "
                    "warmup rejection, which is counted rather than hidden."
                ),
            },
            {
                "title": "What the costs are",
                "body": (
                    "Charged on the venue the trade would actually happen on, not a "
                    "single default. NSE pays STT, SEBI turnover, stamp duty and GST; "
                    "Delta Exchange pays 0.05% taker plus 18% GST, which is 0.118% a "
                    "round trip; US equity pays no commission and the two sell-side "
                    "regulatory fees, about 0.002%. That fifty-fold gap decides more "
                    "results here than any parameter does. Spread and slippage are "
                    "modelled on none of them, so every net figure is better than a "
                    "real fill would be."
                ),
            },
            {
                "title": "What a sweep costs",
                "body": (
                    "Every parameter setting evaluated is written to the trial ledger, "
                    "permanently. The deflated-Sharpe probability and the t-statistic "
                    "both take the total count as their denominator, so each sweep "
                    "raises the bar for every result this platform has produced or ever "
                    "will. That is why sweeps run from `make optimize` and never from a "
                    "button in this interface."
                ),
            },
        ]
    else:
        procedure = [
            {
                "title": "What a backtest here is",
                "body": (
                    "The strategy is asked, on each rebalance day, for the weights it wants "
                    "across the instruments it can see. Those weights become orders, the "
                    "orders are filled at the next available price, and costs are deducted. "
                    "The account starts at "
                    f"₹{BATCH_STARTING_CASH:,.0f} and rebalances every "
                    f"{BATCH_REBALANCE_DAYS} trading days."
                ),
            },
        ]

    procedure += [
        {
            "title": "What it cannot see",
            "body": (
                "The strategy is only ever handed data whose knowledge_time is at or "
                "before the decision date. That is enforced at the data layer rather "
                "than by the strategy behaving well, so a lookahead bug is a structural "
                "impossibility rather than a thing to be careful about."
            ),
        },
        {
            "title": "What the Sharpe is measured against",
            "body": (
                "Not zero. Against the noise bar: the Sharpe the luckiest worthless "
                "strategy would be expected to reach given how many configurations have "
                "been tried. Screening in this interface writes nothing to the trial "
                "ledger, so the bar does not rise as you search — which means it is "
                "lower than the work actually done justifies."
            ),
        },
    ]

    if not intraday:
        procedure += [
            {
                "title": "Warmup",
                "body": (
                    "The first stretch of every run is discarded so features have history "
                    "to compute from — a quarter of the window, capped at 253 days and "
                    "floored at 20. A strategy whose lookback is longer than the window "
                    "will hold nothing and the run refuses rather than reporting a Sharpe "
                    "of zero."
                ),
            },
            {
                "title": "Tier A and Tier B",
                "body": (
                    "Tier A is a vectorised screen: fast, and it assumes it can transact "
                    "at the price it saw. Tier B is the event-driven engine that the paper "
                    "and live paths also use — it places orders, they can be rejected, and "
                    "cash has to be there. A Tier A number read as a Tier B number is "
                    "worse than no number."
                ),
            },
        ]

    asset_classes = [
        {
            "name": capability.asset_class.value,
            "timeframe": capability.timeframe.value,
            "supported": capability.supported,
            "detail": capability.detail,
        }
        for capability in catalog.capabilities()
    ]

    about: dict[str, Any] | None = None
    declaration = REGISTRY.get(strategy) if strategy else None
    if declaration is not None:
        tenant = workspace_mod.resolve(None)
        top = result_store.best(tenant, declaration.id)
        recent = result_store.latest(tenant, declaration.id)
        runs = result_store.distinct(tenant, declaration.id)
        bar = price_search(0, available_years=11.4).bar_after
        about = {
            "id": declaration.id,
            "title": declaration.title,
            "summary": declaration.summary,
            "kind": declaration.kind,
            "shape": declaration.shape,
            "asset_class": declaration.asset_class.value,
            "timeframe": declaration.timeframe.value,
            "emits": declaration.emits.value,
            "lookback": declaration.lookback,
            "is_strategy_subclass": declaration.is_strategy_subclass,
            "risk_manager": declaration.risk_manager,
            "trade_manager": declaration.trade_manager,
            # How it decides, read off the strategy object rather than
            # written into the page: top_n, min_names and the feature are the
            # numbers that actually govern its behaviour, and a description
            # that drifted from them would be confidently wrong.
            "how_it_decides": _how_it_decides(declaration),
            "source": declaration.source,
            "published": declaration.published,
            "tested_on": declaration.tested_on,
            "recommended_class": declaration.recommended_class,
            # Resolved from the citation rather than read off the field: the
            # field is populated where a declaration is built, and a signal
            # built on a branch that forgot shows no source while having one.
            # What the sweep changed, if anything. Carried beside the paper's
            # own values rather than replacing them: a reader has to be able to
            # see that a parameter was moved, from what, and on what evidence.
            "tuning": _tuning(declaration.id),
            "paper_url": paper_url(declaration.source) or declaration.paper_url,
            # Served rather than linked as a file path: the browser cannot open
            # a repo-relative path, and a link that does nothing is worse than
            # none because it looks like provenance was provided.
            "paper_pdf": (f"/api/paper/{declaration.id}" if declaration.paper_pdf else ""),
            "logic": list(declaration.logic),
            "example": _worked_example(declaration),
            "runs_here": len(runs),
            "latest_sharpe": round(recent.sharpe, 4) if recent else None,
            "best_sharpe": round(top.run.sharpe, 4) if top else None,
            "best_window_days": recent.window_days if recent else None,
            "best_universe": recent.universe if recent else "",
            "best_period_note": (
                f"Most recent run: {recent.window_days} trading days on "
                f"{recent.universe or 'the whole panel'}, tier {recent.tier}, "
                f"across {recent.symbols} instruments."
            )
            if recent
            else "Never run in this workspace.",
            "bar": round(bar, 3),
            "clears_bar": bool(recent and recent.sharpe >= bar),
        }

    return {
        "procedure": procedure,
        "asset_classes": asset_classes,
        "strategy": about,
        "starting_cash": BATCH_STARTING_CASH,
        "rebalance_days": BATCH_REBALANCE_DAYS,
    }


@app.get("/api/window")
def window(
    days: int = 800,
    universe: str = ALL_INSTRUMENTS,
    asset_class: str = AssetClass.EQUITY.value,
) -> dict[str, Any]:
    """What a window of N trading days actually covers.

    A number of days is not a period a person can reason about, and the two
    differ in a way that matters: the leading stretch is warmup and is never
    traded. Showing "1200 days" while the strategy trades 964 of them invites
    reading a result as covering a period it does not.
    """
    try:
        if asset_class == AssetClass.EQUITY.value:
            all_days, picked = PANEL.days(), PANEL.days(days)
        else:
            all_days = trading_days(_rows_for(asset_class, 0))
            picked = trading_days(_rows_for(asset_class, days))
    except (FileNotFoundError, OSError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}
    if not picked:
        return {"ok": False, "error": _no_panel_message(asset_class)}

    warmup = warmup_for(len(picked))
    traded = picked[warmup:] if warmup < len(picked) else []

    return {
        "ok": True,
        "requested_days": days,
        "available_days": len(all_days),
        "window_days": len(picked),
        "truncated": days > len(all_days),
        "panel_first": all_days[0].isoformat() if all_days else None,
        "panel_last": all_days[-1].isoformat() if all_days else None,
        "window_first": picked[0].isoformat() if picked else None,
        "window_last": picked[-1].isoformat() if picked else None,
        "warmup_days": warmup,
        "traded_first": traded[0].isoformat() if traded else None,
        "traded_last": traded[-1].isoformat() if traded else None,
        "traded_days": len(traded),
        "universe": universe,
        "asset_class": asset_class,
        # Stated because it changes what the result means. No cost model covers
        # crypto or funds, so those runs are gross of costs — an upper bound,
        # not a net result.
        "cost_mode": cost_mode_for(asset_class),
    }


# --- the trader snapshot ------------------------------------------------------


SNAPSHOT_MOVERS = 12
BREADTH_UNCHANGED_PCT = 0.05
"""Below this move, a name counts as unchanged rather than as an advancer.

Without a dead band, breadth is decided by rounding: a stock that closed a
paisa higher is not an advancer in any sense a reader means, and counting it as
one makes the ratio look decisive on a flat day.
"""


def _by_day(rows: list[PanelRow]) -> dict[date, dict[str, PanelRow]]:
    """The panel indexed once, by day and then by symbol.

    Built once rather than re-derived per day. The first version scanned the
    whole row list inside a loop over days — 400 days against 1.1M rows is
    roughly 880 million comparisons, which returned in minutes to curl and
    timed out through the browser's proxy. Same numbers, two orders of
    magnitude fewer operations.
    """
    index: dict[date, dict[str, PanelRow]] = {}
    for row in rows:
        index.setdefault(row.day, {})[row.symbol] = row
    return index


def _daily_moves(index: dict[date, dict[str, PanelRow]], days: list[date]) -> list[float]:
    """Equal-weighted average return per day, across everything that traded."""
    out: list[float] = []
    for position in range(1, len(days)):
        prior = index.get(days[position - 1], {})
        current = index.get(days[position], {})
        moves = [
            row.close / prior[symbol].close - 1.0
            for symbol, row in current.items()
            if symbol in prior and prior[symbol].close > 0 and row.close > 0
        ]
        if moves:
            out.append(statistics.fmean(moves))
    return out


CALENDAR_WINDOW_DAYS = 7

WORLD_DEADLINE = 25.0
"""Seconds the snapshot waits for index levels before rendering without them."""

LIVE_MAP_DEADLINE = 20.0
"""Seconds to wait for live quotes before drawing the map from the settled
close instead. Measured at 3.3s for 2,458 symbols, so this is generous."""

QUOTES_DEADLINE = 15.0
"""Seconds the snapshot waits for a live quote before rendering without one."""

LIVE_UNIVERSE_TTL = 15.0
"""Seconds a complete live answer for the map is reused. Kite allows one quote
request a second (research 074), so the five calls cannot be made in parallel;
reopening the dashboard inside this window asks nobody. Each quote keeps the
time it was taken, so the screen's "live at" stays true."""

_LIVE_UNIVERSE: dict[tuple[str, ...], tuple[float, dict[str, Any]]] = {}


def _bounded[T](work: Callable[..., T], *args: Any, timeout: float) -> T:
    """`work(*args)` on a thread, given up on after `timeout` seconds.

    Not a `with` block, for the reason `daily_feed._run_step` gives: the
    context manager exits through `shutdown(wait=True)` and so waits out the
    very call the deadline abandoned. Both snapshot deadlines were inert that
    way: a broker that hung for a minute held the page for a minute.
    """
    pool = ThreadPoolExecutor(1)
    try:
        return pool.submit(work, *args).result(timeout=timeout)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def _universe_quotes(symbols: list[str]) -> tuple[dict[str, Any], str]:
    """Live quotes for the map: a complete answer from the last 15 s, or Kite's."""
    from eulerlab import quotes as quote_feed

    key = tuple(symbols)
    held = _LIVE_UNIVERSE.get(key)
    if held is not None and time.monotonic() - held[0] < LIVE_UNIVERSE_TTL:
        return held[1], ""
    fetched, error = _bounded(quote_feed.nse_universe, symbols, timeout=LIVE_MAP_DEADLINE)
    if fetched and not error:
        _LIVE_UNIVERSE.clear()
        _LIVE_UNIVERSE[key] = (time.monotonic(), fetched)
    return fetched, error


CALENDAR_EVENTS = 20
"""Calendar rows kept. Was 14; the operator asked for 20."""

NEWS_TAPE = 50
"""Tape headlines kept. Was 25; the operator asked for 50.

Both bands scroll inside their own panel, so a longer list lengthens the band
rather than the page — which is what made a short cap necessary before.
"""


def _instrument_count(asset_class: str) -> int:
    """How many instruments a class holds, from the local census.

    Was `len(catalog.search(asset_class=..., limit=500))`, which built the full
    instrument list — enumerating 34,773 fx keys, 14,280 mutual funds and 1,200
    crypto — to display a single number. Measured at **62 seconds**, on a band
    that shows three counts.

    Falls back to the live search when the manifest has not been built, so a
    fresh checkout still renders; it just renders slowly, and `make manifest`
    fixes that.
    """
    from eulerlab.ingest import manifest

    # Which number *is* the instrument count differs per tree, so it is stated
    # rather than inferred. `groups or files` looked general and was wrong: mf
    # files live at `mf/history/<scheme>.jsonl.gz`, so the second level is the
    # literal directory `history` and the census records exactly one group —
    # which rendered as "1 mutual fund" against 14,280 landed schemes.
    tree, field = {
        "crypto": ("crypto", "groups"),  # symbols
        "fx": ("fx", "groups"),  # pairs
        "mutual_fund": ("mf", "files"),  # one file per scheme
    }.get(asset_class, ("", ""))

    loaded = manifest.load()
    if tree and loaded is not None:
        census = loaded.census(tree)
        if census is not None:
            return int(getattr(census, field))
    return len(catalog.search(asset_class=asset_class, limit=500))


_WORLD_TTL = 600.0
"""Seconds an index/mover sweep is reused.

Ten minutes. The free FMP budget is 250 calls a day and one sweep costs ten —
seven indices plus three mover feeds — so an uncached band would spend the
whole day's allowance in under half an hour of page reloads.
"""

_WORLD: dict[str, tuple[float, dict[str, Any]]] = {}


_US_TTL = 300.0
_US_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def _us_band() -> dict[str, Any]:
    """Breadth, movers and a sector map for the US, from our own bars.

    The US tab has shown a quote ribbon and a sector-average strip since it
    existed, because there was no US price panel to compute anything from.
    There is now — 502 symbols of Alpaca daily bars — so this is the same
    shape the India view has: a count of advancers and decliners, the biggest
    moves, and a map grouped by sector.

    Reads the derived panel, never the landing zone. 36,446 monthly files live
    in B2 and touching them per request is the mistake this platform has made
    twice already.
    """
    cached = _US_CACHE.get("band")
    if cached is not None and time.monotonic() - cached[0] < _US_TTL:
        return cached[1]

    from eulerlab.features import us_panel

    rows = us_panel.read()
    if not rows:
        return {
            "available": False,
            "reason": "no US panel built — run `make build-us-panel`",
            "movers": {"gainers": [], "losers": []},
            "tiles": [],
        }

    days = sorted({r.day for r in rows})
    if len(days) < 2:
        return {
            "available": False,
            "reason": f"only {len(days)} day(s) in the US panel",
            "movers": {"gainers": [], "losers": []},
            "tiles": [],
        }

    today, prior = days[-1], days[-2]
    by_day: dict[date, dict[str, Any]] = {}
    for row in rows:
        if row.day in (today, prior):
            by_day.setdefault(row.day, {})[row.symbol] = row

    current, previous = by_day.get(today, {}), by_day.get(prior, {})
    sector_of = us_panel.sectors()

    tiles: list[dict[str, Any]] = []
    for symbol, row in current.items():
        was = previous.get(symbol)
        if was is None or was.close <= 0:
            continue
        tiles.append(
            {
                "symbol": symbol,
                "return": row.close / was.close - 1.0,
                "close": round(row.close, 2),
                "turnover": row.turnover,
                "sector": sector_of.get(symbol, ""),
                "relative_volume": None,
            }
        )

    up = sum(1 for t in tiles if t["return"] > 0)
    down = sum(1 for t in tiles if t["return"] < 0)
    ranked = sorted(tiles, key=lambda t: -float(t["return"]))

    band = {
        "available": True,
        "as_of": today.isoformat(),
        "previous": prior.isoformat(),
        "advancers": up,
        "decliners": down,
        "unchanged": len(tiles) - up - down,
        # Equal-weighted, and said so. There is no index in this panel either,
        # so this is the average S&P constituent rather than the cap-weighted
        # benchmark — a different number, and the more honest one for breadth.
        "proxy_return": (sum(float(t["return"]) for t in tiles) / len(tiles) if tiles else 0.0),
        "movers": {
            "gainers": ranked[:SNAPSHOT_MOVERS],
            "losers": ranked[-SNAPSHOT_MOVERS:][::-1],
        },
        "tiles": ranked,
        "symbols": len(tiles),
        "sectors_known": sum(1 for t in tiles if t["sector"]),
        "source": "alpaca daily bars",
    }
    _US_CACHE["band"] = (time.monotonic(), band)
    return band


def _world_band() -> dict[str, Any]:
    """Index levels, movers and sectors — read from the landed sweep.

    Not fetched here. A full sweep is 29 FMP calls against a 250-a-day free
    budget, so rendering it live would spend the allowance before lunch and
    then show nothing for the rest of the day. `make world` takes it once and
    this opens the file, which is the same division the news band already
    makes and for the same reason.

    Carries `taken_at` so the page can say how old the levels are rather than
    implying they are live.
    """
    from eulerlab import indices

    payload = indices.load()
    if payload is None:
        return {
            "available": False,
            "india": [],
            "world": [],
            "crypto": [],
            "fx": [],
            "movers": [],
            "sectors": [],
            "commodities": [],
            "macro": [],
            "curve": None,
            "macro_2s10s": None,
            "errors": {"all": "no sweep landed — run `make world`"},
        }

    lists = {
        key: payload.get(key) if isinstance(payload.get(key), list) else []
        for key in ("india", "world", "crypto", "fx", "movers", "sectors", "commodities", "macro")
    }
    errors = payload.get("errors")
    return {
        "available": any(bool(v) for v in lists.values()),
        **lists,
        "curve": payload.get("curve") if isinstance(payload.get("curve"), dict) else None,
        "macro_2s10s": payload.get("macro_2s10s"),
        "taken_at": str(payload.get("taken_at", "")),
        "errors": errors if isinstance(errors, dict) else {},
    }


def _quotes_band(symbols: list[str], held: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Live prices for the movers, broker first.

    `held` is the map's live answer from this same request: Kite, the same
    venue, with each quote's own time. A mover it priced is taken from it, and
    only the rest are asked for. Asking again for prices fetched a moment ago
    was about 1 s of every live snapshot (measured 2026-10-16).

    Zerodha is primary because it is the venue this platform trades through, so
    its quote is the price an order would actually meet. Yahoo is the fallback
    for whatever the broker did not cover — and is currently answering 429 to
    every request, which is reported rather than shown as an empty column.

    The band exists to end a specific dishonesty: every other number on this
    screen is end-of-day, and a page that does not say so invites the reader to
    treat a settled close as a current price. So each row carries its source,
    and the band names the source it used.
    """
    symbols = list(dict.fromkeys(symbols))[: SNAPSHOT_MOVERS * 2]
    try:
        from eulerlab import quotes

        # Bounded, because this is the one third-party call left in the render
        # path, and an unbounded one already cost this page a 576-second hang
        # through the news feed. A broker that has not answered in fifteen
        # seconds will not answer usefully, and a snapshot without live prices
        # is a far smaller loss than a snapshot that never arrives.
        result = quotes.QuoteResult()
        for symbol in symbols:
            if held and symbol in held:
                result.quotes[symbol] = held[symbol]
                result.sources[held[symbol].source] = result.sources.get(held[symbol].source, 0) + 1
        remainder = [symbol for symbol in symbols if symbol not in result.quotes]
        if remainder and held:
            # Kite was asked for these in this request and did not price them
            # (a rights entitlement, a renamed name): only the fallback is left.
            found, error = _bounded(quotes.from_yahoo, remainder, timeout=QUOTES_DEADLINE)
            result.quotes.update(found)
            if found:
                result.sources["yahoo"] = result.sources.get("yahoo", 0) + len(found)
            if error:
                result.errors["yahoo"] = error
        elif remainder:
            asked = _bounded(quotes.live, remainder, timeout=QUOTES_DEADLINE)
            result.quotes.update(asked.quotes)
            for source, count in asked.sources.items():
                result.sources[source] = result.sources.get(source, 0) + count
            result.errors.update(asked.errors)
    except FuturesTimeout:
        return {
            "available": False,
            "reason": f"no quote source answered within {QUOTES_DEADLINE:.0f}s",
            "quotes": {},
            "note": "No live source answered in time — everything here is end-of-day.",
        }
    except Exception as exc:
        return {"available": False, "reason": f"{type(exc).__name__}: {exc}", "quotes": {}}

    return {
        "available": result.live,
        "source": result.primary_source,
        "sources": result.sources,
        "errors": result.errors,
        "asked": len(symbols),
        "quotes": {
            symbol: {
                "last": round(q.last, 2),
                "previous_close": round(q.previous_close, 2),
                "change_pct": round(q.change_pct, 2),
                "source": q.source,
                "at": q.at,
            }
            for symbol, q in result.quotes.items()
        },
        "note": (
            f"{len(result.quotes)} of {len(symbols)} movers quoted live via "
            f"{result.primary_source or 'no source'}. Every other number on this "
            "screen is end-of-day."
            if result.live
            else "No live source answered — everything here is end-of-day."
        ),
    }


def _news_band(symbols: list[str]) -> dict[str, Any]:
    """Fresh stock-specific news, attached to the movers that need explaining.

    This is the band the snapshot was built without, and said so: every mover
    was "a price without a reason". It now has one — but only where one really
    exists, which is the whole difficulty.

    Two rules make the difference between information and decoration:

    - **Windowed to a day.** An unconstrained Google News search is
      relevance-ranked, and measured over the landed corpus only **0.8% of
      3,525 stories were from that day** while 63% were one to twelve months
      old. Showing that beside today's move would be worse than showing
      nothing, because it would look current.
    - **Attributed strictly.** A headline must carry the ticker or two tokens
      of the registered name. "Reliance Communications" is not a story about
      Reliance Industries, and printing it beside Reliance Industries' price
      would be a false explanation rather than a weak one.

    A mover with no qualifying story is reported as having none. That is a
    finding, not a blank: a large move with no news is a different and often
    more interesting fact than one with news.
    """
    # Gainers, losers and unusual volume overlap, and a duplicate symbol is a
    # duplicate network round trip on a page that has to stay fast.
    symbols = list(dict.fromkeys(symbols))
    try:
        from eulerlab.ingest import news as newsfeed

        # `recent`, not `live`. Rendering must not make a third-party request:
        # Google News began stalling mid-session and `live()` retries three
        # times at a 30s timeout, so thirty-four symbols cost roughly 576
        # seconds and the page returned nothing at all. `make news` does the
        # fetching on a schedule; this opens the files it wrote.
        by_symbol = newsfeed.recent(symbols, hours=36.0)
    except Exception as exc:
        return {
            "available": False,
            "reason": f"news unreachable: {type(exc).__name__}",
            "stories": {},
            "tape": [],
        }

    now = datetime.now(UTC)

    def age_hours(stamp: str) -> float:
        try:
            return max(0.0, (now - datetime.fromisoformat(stamp)).total_seconds() / 3600)
        except ValueError:
            return -1.0

    def row(item: Any) -> dict[str, Any]:
        # Which *other* listed companies the headline names, and their sectors.
        # A sector piece naming four lenders is one event with four exposures,
        # and a reader looking at one mover needs to see the other three.
        hit = newsfeed.affected(item.title)
        return {
            "title": item.title,
            "publisher": item.publisher,
            "link": item.link,
            "symbols": list(item.symbols),
            "affects": list(hit.symbols),
            "sectors": list(hit.sectors),
            "age_hours": round(age_hours(item.event_time), 1),
        }

    stories = {symbol: row(items[0]) for symbol, items in by_symbol.items() if items}
    # The tape is market-wide, not mover-scoped. Built from `by_symbol` it read
    # empty whenever the day's movers were obscure small caps — which is most
    # days — while a hundred landed stories about large caps sat unshown. The
    # per-mover *reason* must still be about that mover; a tape is just what
    # happened, in order.
    feed = [row(i) for i in newsfeed.recent_all(hours=36.0, limit=NEWS_TAPE)]
    covered = len(stories)
    return {
        "available": True,
        "stories": stories,
        "tape": feed,
        "covered": covered,
        "asked": len(symbols),
        "window": newsfeed.LIVE_WINDOW,
        "note": (
            f"{covered} of {len(symbols)} movers have a landed story from the last "
            "36 hours. The rest moved without one, which is itself worth seeing."
        ),
    }


def _calendar_band() -> dict[str, Any]:
    """Scheduled macro releases, from the ForexFactory feed.

    **This is not the missing `why`.** A CPI print explains why the market
    moved; it does not explain why one small-cap rose 40%. Stock-specific news
    is still absent, and conflating a macro calendar with it would be the
    comfortable presentation and the wrong one — so this is its own band and
    says what it does not cover.
    """
    try:
        from eulerlab.ingest import forexfactory

        events = forexfactory.read_all()
    except Exception as exc:
        return {
            "available": False,
            "reason": f"calendar unreadable: {type(exc).__name__}",
            "events": [],
        }

    if not events:
        return {
            "available": False,
            "reason": "No calendar landed. Run `make calendar` to fetch this week.",
            "events": [],
        }

    now = datetime.now(UTC)
    horizon = now + timedelta(days=CALENDAR_WINDOW_DAYS)
    rows: list[dict[str, Any]] = []
    for event in events:
        try:
            when = datetime.fromisoformat(event.event_time)
        except ValueError:
            continue
        if when > horizon:
            continue
        rows.append(
            {
                "title": event.title,
                "country": event.country,
                "at": event.event_time,
                "impact": event.impact,
                "forecast": event.forecast,
                "previous": event.previous,
                "past": when < now,
            }
        )
    rows.sort(key=lambda r: str(r["at"]), reverse=True)
    high = [r for r in rows if r["impact"] == "High"]

    # High-impact first, then the rest, up to the row budget. It used to be
    # `high or rows` — only the high-impact ones whenever any existed — which
    # meant a week with eight high-impact releases showed eight rows and hid
    # the other ninety-two entirely. With a twenty-row budget that throws away
    # twelve rows of real schedule to no purpose. Ordering by consequence and
    # then filling keeps the important ones at the top without pretending the
    # others are not happening.
    ordered = high + [r for r in rows if r not in high]

    return {
        "available": True,
        "events": ordered[:CALENDAR_EVENTS],
        "total": len(rows),
        "high_impact": len(high),
        "reason": (
            "Scheduled macro releases only. This explains why the market moved, not "
            "why one company did — stock-specific news is still absent, and the feed "
            "carries no released value, so surprise against forecast cannot be "
            "computed from it."
        ),
    }


SNAPSHOT_DAYS = 90
"""Sessions the snapshot reads. Its longest look back is 70 days of moves
(71 closes) for the volatility comparison; it used to read 400, a million
rows, and index all of them by day on every request."""


class _SettledOnly(Exception):
    """The caller asked for held data only; no broker is asked."""


@app.get("/api/snapshot")
def snapshot(workspace: str = "", live: bool = True) -> dict[str, Any]:
    """The trader's first screen, computed from the panel.

    `live=false` skips the two broker calls and answers from held data alone:
    the settled panel, with the newest prices already seen laid over it when
    they postdate it (`last_seen`). The screen asks for that first and paints,
    then asks again with `live` and swaps the prices in. The broker calls were 4 to 7 of the 6 to 9
    seconds this route took (measured 2026-10-12), and the first paint was
    waiting on all of it.

    Five bands (docs/RESEARCH/021): regime, the map, movers, cross-asset, and
    evidence. Each reports what it can measure and says plainly what it cannot
    — a band that names its missing source is a shopping list, whereas a band
    quietly omitted is invisible.
    """
    tenant = workspace_mod.resolve(workspace or None)
    try:
        rows = PANEL.rows(SNAPSHOT_DAYS)
    except (FileNotFoundError, OSError) as exc:
        return {"ok": False, "error": str(exc)}
    if not rows:
        return {"ok": False, "error": "no panel on disk. Run `make build-panel` first."}

    days = trading_days(rows)
    if len(days) < 30:
        return {"ok": False, "error": "not enough history for a snapshot"}
    today, yesterday = days[-1], days[-2]
    index = _by_day(rows)
    prior_day, current_day = index.get(yesterday, {}), index.get(today, {})
    returns = {
        symbol: row.close / prior_day[symbol].close - 1.0
        for symbol, row in current_day.items()
        if symbol in prior_day and prior_day[symbol].close > 0 and row.close > 0
    }

    # --- live overlay -------------------------------------------------------
    # The panel is the backtest's source of truth and always will be, but it is
    # end-of-day, and a screen that opens on a settled close is describing
    # yesterday. Kite quotes 500 instruments in 0.2 seconds, so the whole
    # universe is six calls and under four — which is what makes a live map
    # possible rather than a nightly one.
    #
    # Substituted into `returns` rather than carried alongside, so breadth, the
    # map and the movers all move together. Two sources for one number on one
    # screen is how a page ends up disagreeing with itself.
    live_at = ""
    live_returns: dict[str, float] = {}
    live_error = ""
    fetched: dict[str, Any] = {}
    seen_returns: dict[str, float] = {}
    seen_at = ""
    seen_sources: tuple[str, ...] = ()
    try:
        if not live:
            # No broker, but not necessarily the settled close either: the
            # last quotes this machine saw may be from after it (`last_seen`).
            seen = last_seen.newest(today, {s: r.close for s, r in current_day.items()})
            # Only stocks the panel also has. A name with no settled row has
            # no turnover to size it by and would count in breadth unseen.
            seen_returns = {s: r for s, r in seen.returns.items() if s in returns}
            seen_at = seen.taken_at if seen_returns else ""
            seen_sources = seen.sources if seen_returns else ()
            raise _SettledOnly
        fetched, live_error = _universe_quotes(sorted(returns))
        for symbol, quote in fetched.items():
            if quote.previous_close > 0:
                live_returns[symbol] = quote.last / quote.previous_close - 1.0
        if live_returns:
            live_at = next(iter(fetched.values())).at
        if fetched and not live_error:
            # A whole answer only: a universe cut short by an error would
            # replace two thousand saved prices with five hundred.
            last_seen.save(fetched)
    except _SettledOnly:
        live_error = (
            f"{' and '.join(seen_sources)}; live prices are loading"
            if seen_returns
            else "settled closes; live prices are loading"
        )
    except FuturesTimeout:
        live_error = f"no quote in {LIVE_MAP_DEADLINE:.0f}s"
    except Exception as exc:
        live_error = f"{type(exc).__name__}: {exc}"

    # Only symbols the broker actually priced are replaced. A partial answer
    # updates what it covers and leaves the rest on the settled close, which is
    # better than discarding two thousand live prices because six were missing.
    if live_returns or seen_returns:
        returns = {**returns, **seen_returns, **live_returns}

    # --- band 1: regime -----------------------------------------------------
    up = sum(1 for r in returns.values() if r > BREADTH_UNCHANGED_PCT / 100)
    down = sum(1 for r in returns.values() if r < -BREADTH_UNCHANGED_PCT / 100)
    flat = len(returns) - up - down

    # An equal-weighted proxy, stated as such. There is no index in the panel,
    # so this is the average stock rather than the cap-weighted market — which
    # is a different and, for breadth, more honest number.
    latest_close = {symbol: row.close for symbol, row in current_day.items()}
    proxy = _daily_moves(index, days[-70:])

    recent = proxy[-20:]
    older = proxy[-60:-20] if len(proxy) >= 60 else []
    vol = statistics.pstdev(recent) * (252**0.5) if len(recent) > 2 else 0.0
    vol_before = statistics.pstdev(older) * (252**0.5) if len(older) > 2 else 0.0
    cumulative = 1.0
    for move in recent:
        cumulative *= 1.0 + move

    # --- band 2 and 3: the map and the movers -------------------------------
    turnover = {symbol: row.turnover for symbol, row in current_day.items()}
    volume_history: dict[str, list[float]] = {}
    for day in days[-21:-1]:
        for symbol, row in index.get(day, {}).items():
            if row.turnover > 0:
                volume_history.setdefault(symbol, []).append(row.turnover)

    # Sector and market cap come from the screener scrape, which landed them
    # all along under sections nothing was reading (`sector`, `top_ratios`).
    companies = company_digest.load_digest()

    tiles: list[dict[str, Any]] = []
    for symbol, move in returns.items():
        traded = turnover.get(symbol, 0.0)
        if traded <= 0:
            continue
        past = volume_history.get(symbol, [])
        typical = statistics.median(past) if len(past) >= 5 else 0.0
        profile = companies.get(symbol)
        tiles.append(
            {
                "symbol": symbol,
                "return": round(move, 6),
                "turnover": round(traded, 2),
                "close": round(latest_close.get(symbol, 0.0), 2),
                "relative_volume": round(traded / typical, 2) if typical > 0 else None,
                "sector": profile.sector if profile else "",
                "industry": profile.industry if profile else "",
                "market_cap": profile.market_cap if profile else None,
                "pe": profile.pe if profile else None,
            }
        )

    # Sized by market cap where it is known, falling back to turnover. The two
    # are different statements — size against attention — so which one a tile
    # used is reported rather than blended silently.
    capped = [t for t in tiles if t["market_cap"]]
    sized_by = "market cap" if len(capped) > len(tiles) * 0.5 else "turnover"
    key = "market_cap" if sized_by == "market cap" else "turnover"
    tiles.sort(key=lambda t: -float(t[key] or 0))
    by_move = sorted(tiles, key=lambda t: -float(t["return"]))
    unusual = sorted(
        (t for t in tiles if t["relative_volume"] is not None),
        key=lambda t: -float(t["relative_volume"] or 0),
    )

    # --- band 4: cross-asset ------------------------------------------------
    cross: list[dict[str, Any]] = [
        {
            "asset_class": "equity",
            "label": "NSE equities",
            "instruments": len(latest_close),
            "as_of": today.isoformat(),
            "detail": f"{up:,} up / {down:,} down",
        }
    ]
    # Read once, outside the loop. It was called per asset class, and
    # `capabilities()` is not memoised — it lists landing trees to build its
    # description strings, so three classes meant three full passes and the
    # snapshot paid for the same answer three times over.
    daily_cells = {
        c.asset_class.value: c for c in catalog.capabilities() if c.timeframe is Timeframe.DAILY
    }
    for name, klass in (("Crypto", "crypto"), ("FX", "fx"), ("Mutual funds", "mutual_fund")):
        cell = daily_cells.get(klass)
        cross.append(
            {
                "asset_class": klass,
                "label": name,
                "instruments": _instrument_count(klass),
                "as_of": "",
                "detail": cell.detail if cell else "no capability entry",
            }
        )

    # --- band 5: evidence ---------------------------------------------------
    bar = price_search(0, available_years=11.4).bar_after
    fleet_rows = list(strategy_fleet(tenant.ledger))
    # Same adopted results the library judges on, so the snapshot's count and
    # the library's flags cannot disagree about the same strategies.
    clearing = [r for r in fleet_rows if _clears(tenant, r, bar, adopted_mod.read())]

    return {
        "ok": True,
        "as_of": today.isoformat(),
        # What the screen is actually showing, and when it was taken. The page
        # carried a settled date while quoting live prices under it, which is
        # the kind of quiet disagreement a reader has no way to notice.
        "freshness": {
            "live": bool(live_returns),
            "quoted": len(live_returns) or len(seen_returns),
            "of": len(returns),
            "taken_at": live_at or seen_at,
            # Not live, but newer than the panel: the last prices seen here.
            "last_seen": bool(seen_returns),
            "panel_date": today.isoformat(),
            "reason": live_error,
        },
        "previous": yesterday.isoformat(),
        "regime": {
            "advancers": up,
            "decliners": down,
            "unchanged": flat,
            "breadth_ratio": round(up / down, 2) if down else None,
            "proxy_return_20d": round(cumulative - 1.0, 6),
            "volatility": round(vol, 6),
            "volatility_before": round(vol_before, 6) if vol_before else None,
            "volatility_rising": bool(vol_before and vol > vol_before),
            "proxy_note": (
                "Equal-weighted across every symbol in the panel. There is no index "
                "here, so this is the average stock rather than the cap-weighted "
                "market — a different number, and for breadth the more honest one."
            ),
        },
        "map": {
            "tiles": tiles[:180],
            "sized_by": sized_by,
            "note": (
                "Sized by market capitalisation and grouped by sector, both from the "
                "screener scrape."
                if sized_by == "market cap"
                else "Sized by turnover — market cap is known for too few names to size "
                "by it, which measures attention rather than size."
            ),
            "grouped": bool(companies),
            "covered": len(capped),
            "missing": "" if companies else "sector classification",
        },
        "movers": {
            "gainers": by_move[:SNAPSHOT_MOVERS],
            "losers": by_move[-SNAPSHOT_MOVERS:][::-1],
            "unusual_volume": unusual[:SNAPSHOT_MOVERS],
        },
        "world": _world_band(),
        "us": _us_band(),
        "quotes": _quotes_band(
            [str(t["symbol"]) for t in [*by_move[:SNAPSHOT_MOVERS], *by_move[-SNAPSHOT_MOVERS:]]],
            held=fetched,
        )
        if live
        else {"available": False, "reason": "live prices are loading", "quotes": {}},
        "news": _news_band(
            [
                str(t["symbol"])
                for t in [
                    *by_move[:SNAPSHOT_MOVERS],
                    *by_move[-SNAPSHOT_MOVERS:],
                    *unusual[:SNAPSHOT_MOVERS],
                ]
            ]
        ),
        "catalysts": _calendar_band(),
        "cross_asset": cross,
        "evidence": {
            "bar": round(bar, 3),
            "strategies": len(fleet_rows),
            "clearing": len(clearing),
            "clearing_names": [r.declaration.id for r in clearing][:8],
            "trials": sum(r.trials for r in fleet_rows),
        },
        "gaps": [
            *(
                []
                if companies
                else [
                    "sector and market cap — run `make company-digest` to read them "
                    "out of the fundamentals tree"
                ]
            ),
            "index levels — no NIFTY, so breadth has nothing to diverge from "
            "and a mover cannot be read against the market",
        ],
    }


@app.get("/api/risk")
def risk() -> dict[str, Any]:
    """Limits, breaches and the kill switch, for the Risk screen.

    The architecture document puts risk on the home screen, one click away,
    and it was reachable only from a terminal. The numbers here are the ones
    `oms/killswitch.py` actually enforces, read from the same config file it
    reads — not a second copy that could drift from the enforced values.
    """
    from eulerlab.oms import killswitch

    try:
        limits = killswitch.load_limits()
    except Exception as exc:  # a malformed config must not blank the screen
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:200]}

    switch = killswitch.KillSwitch()
    tripped = switch.is_tripped()
    return {
        "ok": True,
        "tripped": tripped,
        "reason": switch.reason() if tripped else "",
        "limits": [
            {
                "name": "max daily loss",
                "value": limits.max_daily_loss,
                "unit": "INR",
                "note": "realised plus unrealised",
            },
            {
                "name": "max orders per day",
                "value": limits.max_orders_per_day,
                "unit": "orders",
                "note": "",
            },
            {
                "name": "max consecutive rejections",
                "value": limits.max_consecutive_rejections,
                "unit": "orders",
                "note": "a run of these means something is misconfigured",
            },
            {
                "name": "max position notional",
                "value": limits.max_position_notional,
                "unit": "INR",
                "note": "in any single name",
            },
            {
                "name": "max unresolved orders",
                "value": limits.max_unresolved_orders,
                "unit": "orders",
                "note": "orders stuck in UNKNOWN; the broker link is unhealthy",
            },
        ],
        # Stated rather than implied. The switch is reset by a separate process
        # with separate credentials, so the interface cannot offer a button for
        # it — and a screen that showed one would be lying about who can act.
        "reset_note": (
            "The kill switch is tripped and reset by a separate process with separate "
            "credentials. This screen reports it; it cannot change it."
        ),
    }


@app.get("/api/mode")
def mode() -> dict[str, Any]:
    """Which mode the platform is in, for the badge on every screen.

    The first design principle in the architecture document is that mode is
    always visible so nobody places a real order by mistake. This platform
    cannot place one at all: `Stage.LIVE` and `Stage.FORWARD_TESTING` exist in
    the enum and nothing produces them, there is no live broker adapter
    (S-015), and no capital has ever been traded.

    So the badge reads PAPER and says why, which is a stronger claim than a
    live/paper toggle: it is not a setting someone can flip by accident.
    """
    from eulerlab.oms import killswitch

    return {
        "ok": True,
        "mode": "paper",
        "live_possible": False,
        "why": "no live broker adapter exists (S-015); no capital has ever been traded",
        "kill_switch_tripped": killswitch.KillSwitch().is_tripped(),
    }


@app.get("/api/options/chain")
def options_chain(underlying: str = "NIFTY", day: str = "", expiry: str = "") -> dict[str, Any]:
    """One option chain in full. The work, and its notes, are in `_chain_payload`."""
    return _chain_payload(underlying, day, expiry, summary=False)


def _chain_payload(underlying: str, day: str, expiry: str, *, summary: bool) -> dict[str, Any]:
    """One option chain, with implied vol and the no-arbitrage findings.

    The options package has parsed chains, solved Black-76 implied vol and run
    five no-arbitrage checks since the options-quality sprint, and none of it
    has ever been reachable from the interface — the capability matrix has read
    "chains parsed, no strategy path" the whole time. This does not add
    analysis; it stops hiding the analysis that exists.

    Violations are reported with `traded` beside them on purpose. An untraded
    contract's price is NSE's model output, so a "violation" involving one is a
    statement about that model rather than about a tradable edge, and the two
    must never be presented as the same finding.
    """
    import datetime as dt
    from decimal import Decimal

    from eulerlab.ingest import landing_reader
    from eulerlab.master.derivatives import Right
    from eulerlab.options import analytics
    from eulerlab.options.arbitrage import implied_forward_and_discount, run_chain_checks
    from eulerlab.options.chain import build_chains, quotes_from_fo_bhavcopy
    from eulerlab.options.iv import implied_vol, years_to_expiry

    found = landing_reader.available("fo", "**/*_udiff.zip", stale_ok=True)
    if not found:
        return {"ok": False, "error": "no F&O bhavcopy has been landed"}

    def day_of(path: str) -> str:
        return path.rsplit("/", 1)[-1].split("_")[0]

    wanted = day or max(day_of(p) for p in found)
    match = next((p for p in found if day_of(p) == wanted), "")
    if not match:
        return {"ok": False, "error": f"no F&O bhavcopy for {wanted}"}

    try:
        payload = landing_reader.read(match)
        trade_day = dt.date.fromisoformat(wanted)
        chains = build_chains(quotes_from_fo_bhavcopy(payload, underlying), trade_day)
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:200]}

    mine = [c for c in chains if c.underlying.upper() == underlying.upper()]
    if not mine:
        # Only now is the whole file read, to say which names it does hold.
        # The common case, a name that exists, never pays for this.
        try:
            names = sorted({q.underlying for q in quotes_from_fo_bhavcopy(payload)})[:40]
        except Exception:
            names = []
        return {"ok": False, "error": f"no chain for {underlying}", "available": names}

    mine.sort(key=lambda c: c.expiry)
    chain = next((c for c in mine if c.expiry.isoformat() == expiry), mine[0])

    # The forward is fitted from put-call parity before it is taken from the
    # future, for two reasons. Index futures are monthly and the options are
    # weekly, so an exact-expiry future exists for roughly one chain in four —
    # every weekly priced `forward: None` and showed no implied vol at all.
    # And the fit returns the discount factor with it, which was otherwise
    # hardcoded to 1.0 and silently shifted every vol on the screen.
    fitted = implied_forward_and_discount(chain, traded_only=True)
    if fitted is not None:
        forward, discount = fitted
        forward_source = "fitted from put-call parity"
    elif chain.future is not None:
        forward, discount = chain.future.price, 1.0
        forward_source = "the exact-expiry future, undiscounted"
    else:
        forward, discount = None, 1.0
        forward_source = "unavailable — no parity fit and no matching future"
    days_out = max((chain.expiry - trade_day).days, 0)
    tenor = years_to_expiry(days_out)

    at_the_money = analytics.atm_strike(chain.strikes, forward or 0.0)

    rows: list[dict[str, Any]] = []
    for strike in chain.strikes:
        # `summary` is the history's question: one at-the-money row per day.
        # Solving implied vol for every strike of every day to read one row
        # was most of the history's 8 s for 30 days (measured 2026-10-12).
        if summary and (at_the_money is None or float(strike) != float(at_the_money)):
            continue
        call, put = chain.calls.get(strike), chain.puts.get(strike)

        def vol(quote: Any, right: Right, *, at: Decimal = strike) -> float | None:
            if quote is None or forward is None or tenor <= 0 or quote.price <= 0:
                return None
            try:
                return implied_vol(
                    price=quote.price,
                    forward=forward,
                    strike=float(at),
                    years=tenor,
                    discount=discount,
                    right=right,
                )
            except Exception:
                # A strike the solver cannot price is blank, never zero. Zero
                # vol is a number someone will average.
                return None

        rows.append(
            {
                "strike": float(strike),
                "call_price": call.price if call else None,
                "call_oi": call.open_interest if call else None,
                "call_volume": call.volume if call else None,
                "call_traded": bool(call and call.traded),
                # Lot size travels with the chain because a payoff in rupees
                # needs it and it is a time-versioned contract field, never a
                # constant to hardcode (CLAUDE.md).
                "lot_size": (call.lot_size if call else None) or (put.lot_size if put else None),
                "call_iv": vol(call, Right.CALL),
                "put_price": put.price if put else None,
                "put_oi": put.open_interest if put else None,
                "put_volume": put.volume if put else None,
                "put_traded": bool(put and put.traded),
                "put_iv": vol(put, Right.PUT),
            }
        )

    pain = analytics.max_pain(chain)
    ratio = analytics.put_call_ratio(chain)
    if summary:
        # Exactly the fields `options.history.history_point` reads, computed
        # the same way as below; the checks, Greeks, gamma and smile are not.
        return {
            "ok": True,
            "underlying": chain.underlying,
            "day": wanted,
            "expiry": chain.expiry.isoformat(),
            "days_to_expiry": days_out,
            "forward": forward,
            "strikes": rows,
            "atm_strike": at_the_money,
            "max_pain": {"strike": pain.strike} if pain else None,
            "put_call_ratio": {"by_open_interest": ratio.by_open_interest},
        }

    findings = [
        {
            "check": f.check,
            "severity": str(getattr(f.severity, "value", f.severity)),
            "detail": f.detail,
        }
        for f in run_chain_checks(chain, traded_only=True)
    ]

    # The derived views. Solved once from one enriched set of rows, so every
    # tool on the screen is reading the same vol and the same Greeks — six
    # separate solves would be six chances to use a different forward.
    enriched = analytics.enrich(chain, forward=forward or 0.0, discount=discount, years=tenor)
    gamma = analytics.gamma_exposure(enriched, forward=forward or 0.0)
    curve = analytics.smile(enriched, forward=forward or 0.0)

    for row, enriched_row in zip(rows, enriched, strict=False):
        call_g, put_g = enriched_row.call_greeks, enriched_row.put_greeks
        row["call_delta"] = call_g.delta if call_g else None
        row["call_gamma"] = call_g.gamma if call_g else None
        row["call_vega"] = call_g.vega if call_g else None
        row["call_theta"] = call_g.theta / 365.0 if call_g else None
        row["put_delta"] = put_g.delta if put_g else None
        row["put_gamma"] = put_g.gamma if put_g else None
        row["put_vega"] = put_g.vega if put_g else None
        row["put_theta"] = put_g.theta / 365.0 if put_g else None

    return {
        "ok": True,
        "underlying": chain.underlying,
        "day": wanted,
        "expiry": chain.expiry.isoformat(),
        "expiries": [c.expiry.isoformat() for c in mine],
        "days_to_expiry": days_out,
        "forward": forward,
        "forward_source": forward_source,
        "discount": discount,
        "strikes": rows,
        "atm_strike": at_the_money,
        "max_pain": (
            {"strike": pain.strike, "payout": pain.payout, "curve": pain.curve} if pain else None
        ),
        "put_call_ratio": {
            "by_open_interest": ratio.by_open_interest,
            "by_volume": ratio.by_volume,
            "call_open_interest": ratio.call_open_interest,
            "put_open_interest": ratio.put_open_interest,
            "call_volume": ratio.call_volume,
            "put_volume": ratio.put_volume,
        },
        "gamma": {
            "total": gamma.total,
            "flip": gamma.flip,
            "convention": gamma.convention,
            "points": [{"strike": p.strike, "exposure": p.gamma_exposure} for p in gamma.points],
        },
        "smile": [
            {
                "strike": p.strike,
                "moneyness": p.moneyness,
                "call_iv": p.call_iv,
                "put_iv": p.put_iv,
            }
            for p in curve
        ],
        "findings": findings,
        # Stated because it changes what a finding means, and the distinction
        # is invisible in the numbers themselves.
        "findings_note": (
            "Checked against traded contracts only. An untraded contract's price is NSE's "
            "model output, so a violation involving one describes that model, not an edge."
        ),
    }


_HISTORY_POINTS: dict[tuple[str, str], dict[str, Any] | None] = {}
"""One straddle-history point per (underlying, day), kept for the server's life.
A landed bhavcopy never changes, so neither does its point; re-parsing 30 of
them was 3.2 s of every warm request (measured 2026-10-16). A day whose chain
could not be read is not kept, so a failed fetch is tried again next time."""


@app.get("/api/options/history")
def options_history(underlying: str = "NIFTY", days: int = 30) -> dict[str, Any]:
    """The at-the-money straddle, its implied vol and the forward, day by day.

    The straddle chart and the option-Greeks history are OpenAlgo tools that
    need a series where the chain endpoint gives a point. This walks the most
    recent landed bhavcopy days and reduces each day's nearest-expiry chain with
    `options.history.history_point`, so every point is the same computation the
    chain screen shows for that day. A day whose chain cannot be read or has no
    priced at-the-money pair is listed in `skipped`, never drawn as zero.

    Each day parses a whole bhavcopy, so `days` is capped at 120.
    """
    from eulerlab.options.history import history_point

    listed = options_days(limit=max(1, min(days, 120)))
    points: list[dict[str, Any]] = []
    skipped: list[str] = []
    for day in reversed(listed["days"]):
        key = (underlying.upper(), day)
        if key in _HISTORY_POINTS:
            point = _HISTORY_POINTS[key]
        else:
            payload = _chain_payload(underlying, day, "", summary=True)
            point = history_point(payload)
            if payload.get("ok"):
                _HISTORY_POINTS[key] = point
        if point is None:
            skipped.append(day)
        else:
            points.append(point)
    if not points:
        return {
            "ok": False,
            "error": f"no priced at-the-money straddle for {underlying}",
            "skipped": skipped,
        }
    return {"ok": True, "underlying": underlying.upper(), "points": points, "skipped": skipped}


@app.get("/api/options/days")
def options_days(limit: int = 400) -> dict[str, Any]:
    """Trade dates with a landed F&O bhavcopy, newest first.

    Served separately from the chain itself. The chain endpoint parses a whole
    bhavcopy to answer, and listing 678 dates alongside every chain request
    would make the cheap question pay the cost of the expensive one.
    """
    from eulerlab.ingest import landing_reader

    found = landing_reader.available("fo", "**/*_udiff.zip", stale_ok=True)
    days = sorted({p.rsplit("/", 1)[-1].split("_")[0] for p in found}, reverse=True)
    return {"ok": True, "days": days[:limit], "total": len(days)}
