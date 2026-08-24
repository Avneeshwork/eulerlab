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

import hashlib
import os
import statistics
import threading
import time
import traceback
import uuid
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from itertools import pairwise
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field

from eulerlab import cloud_results, reports
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
from eulerlab.features import company as company_digest
from eulerlab.features.alt_panel import coverage as alt_coverage
from eulerlab.features.library import BY_NAME
from eulerlab.features.panel import PanelRow, read_panel, trading_days
from eulerlab.ingest.cloud import load_storage_config
from eulerlab.intraday import scan as tweezer_scan
from eulerlab.intraday.paper_scan import ALL_SIGNALS as PAPER_SIGNALS
from eulerlab.intraday.tweezer import Rules
from eulerlab.llm import client
from eulerlab.research.budget import price_search
from eulerlab.strategies import REGISTRY, AssetClass, Timeframe, catalog
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
        self._indices: dict[tuple[int, str], dict[str, dict[date, float]]] = {}

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

    def index(
        self, days: int, rows: list[PanelRow], universe: str = "all"
    ) -> dict[str, dict[date, float]]:
        """Back-adjusted prices for this row set.

        Keyed by the window AND the universe. Keying by window alone was safe
        only while every run saw the whole panel: once rows are filtered, a
        nifty50 run at 800 days would hand its index to the next 800-day run
        over every symbol, which then has no adjusted prices for the symbols
        nifty50 never contained.
        """
        with self._lock:
            key = (days, universe)
            if key not in self._indices:
                self._indices[key] = build_adjusted_index(rows)
            return self._indices[key]

    def loaded(self) -> bool:
        return self._rows is not None


PANEL = _Panel()


class _AltPanel:
    """Crypto and mutual fund daily bars, loaded once and kept.

    Separate from `_Panel` because these are *derived*: crypto is resampled
    from 52.5M minute candles and funds from 14,280 NAV series, so a rebuild
    per request would make the first backtest on either take minutes. Held by
    asset class, and the lock is the same reason `_Panel` has one — two
    requests arriving together would otherwise both start the resample.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rows: dict[str, list[PanelRow]] = {}

    def rows(self, asset_class: str, days: int = 0) -> list[PanelRow]:
        with self._lock:
            if asset_class not in self._rows:
                self._rows[asset_class] = _load_alt(asset_class)
        rows = self._rows[asset_class]
        if not days:
            return rows
        # Trailing N *trading* days, matching `_Panel.rows`. Crypto trades every
        # day and funds only on business days, so neither is forced onto the NSE
        # calendar; "trading days" is whatever days the data actually has.
        all_days = sorted({r.day for r in rows})
        if days >= len(all_days):
            return rows
        cutoff = all_days[-days]
        return [r for r in rows if r.day >= cutoff]

    def loaded(self, asset_class: str) -> bool:
        return asset_class in self._rows


def _load_alt(asset_class: str) -> list[PanelRow]:
    from eulerlab.features import alt_panel

    if asset_class == AssetClass.CRYPTO.value:
        return alt_panel.crypto_daily()
    if asset_class == AssetClass.MUTUAL_FUND.value:
        return alt_panel.fund_daily()
    if asset_class == AssetClass.FX.value:
        return alt_panel.fx_daily()
    msg = f"no panel for asset class {asset_class!r}"
    raise ValueError(msg)


ALT = _AltPanel()

COSTED_CLASSES = frozenset({AssetClass.EQUITY.value, AssetClass.FX.value})
"""Asset classes the cost model actually covers.

`costs/schedule.py` has segments for equity delivery, equity intraday, futures
and options — all Indian exchange-traded. Running a Binance spot trade or a
mutual fund redemption through EQUITY_DELIVERY would apply STT, stamp duty and
NSE charges to something none of them touch, and produce a confidently wrong
number rather than an obviously missing one.

So crypto and fund runs are executed gross of costs and labelled as such. That
is a real limitation, recorded in docs/STUBS.md, not a rounding decision: a
crypto strategy rebalancing every 21 days pays real Binance taker fees, and a
result that ignores them is an upper bound.

**FX is the exception, and for a reason worth stating.** It also pays none of
the Indian charges — but its cost is the bid-ask spread, which is *measured* in
the landed data and carried on every `PanelRow`. Charging what was observed is
not the same kind of act as inventing a fee schedule, so FX runs costed.
"""


def _rows_for(asset_class: str, days: int) -> list[PanelRow]:
    """The daily bars for one asset class, trimmed to the window."""
    if asset_class == AssetClass.EQUITY.value:
        return PANEL.rows(days)
    return ALT.rows(asset_class, days)


def _no_panel_message(asset_class: str) -> str:
    if asset_class == AssetClass.CRYPTO.value:
        return "no crypto landed. Run `make crypto` first."
    if asset_class == AssetClass.FX.value:
        return "no FX landed. Run `make fx-bulk` first."
    if asset_class == AssetClass.MUTUAL_FUND.value:
        return "no mutual fund NAV history landed. Run `make mf` first."
    return "no panel on disk. Run `make build-panel` first."


def cost_mode_for(asset_class: str) -> str:
    """`realistic` where the cost model applies, `replication` where it does not."""
    return "realistic" if asset_class in COSTED_CLASSES else "replication"


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
    symbols: int = 0
    """Distinct instruments that actually traded, counted from the fills."""

    fill_rows: Sequence[reports.FillLike] = ()
    """The fills themselves, for the report's order ledger and attribution.

    A Sequence rather than a list because Tier A and Tier B have separate fill
    types with no common ancestor; `list` is invariant, so only a covariant
    container accepts either against the protocol.
    """

    rejection_rows: tuple[tuple[str, str, str], ...] = ()

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
) -> _EngineRun:
    """The one place this API calls an engine.

    Extracted so a single backtest and a screening batch cannot drift apart —
    the same reasoning as T-2501, which pulled `plan_orders` out so the
    backtest and paper paths shared one implementation. A second path to a
    number is a second answer.
    """
    days = trading_days(rows)
    warmup = warmup_for(len(days))
    index = PANEL.index(days_window, rows, universe)

    if tier == "A":
        run = vector.run(
            rows,
            strategy,
            starting_cash=starting_cash,
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
        )

    run_b = event_driven.run(
        rows,
        strategy,
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


def _clears(tenant: workspace_mod.Workspace, row: Any, bar: float) -> bool:
    value = row.sharpe if row.sharpe is not None else _latest_sharpe(tenant, row)
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
                # Whether the interface can actually run it. Not the same as
                # satisfying the Strategy interface: the intraday signals
                # cannot be expressed as target weights (ADR-037) and still run
                # perfectly well through the minute-bar scanner. Conflating the
                # two left eleven coded strategies greyed out.
                "runnable": (
                    row.declaration.is_strategy_subclass or row.declaration.id in PAPER_SIGNALS
                ),
                "engine": ("intraday" if row.declaration.id in PAPER_SIGNALS else "daily"),
                "source": row.declaration.source,
                "published": row.declaration.published,
                "stage": row.stage.value,
                # The ledger's Sharpe (a validated result) takes precedence over
                # a screened one: it is the stronger claim and was paid for.
                # `result` carries the backtest figure and, inseparably, how
                # many runs it was the best of.
                "sharpe": row.sharpe if row.sharpe is not None else _latest_sharpe(tenant, row),
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
            "symbols": len({row.symbol for row in PANEL.rows()}),
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


class BatchRunRequest(BaseModel):
    """A batch of screening runs."""

    model_config = ConfigDict(extra="forbid")

    strategies: list[str] = Field(default_factory=list)
    days: int = Field(default=800, ge=60, le=3000)
    tier: Literal["A", "B"] = "B"
    universe: str = ALL_INSTRUMENTS
    """Which instruments the strategy may choose from. Part of the cache key
    and of the stored result's configuration, because the same strategy over
    nifty50 and over the whole panel are two different answers."""

    asset_class: str = AssetClass.EQUITY.value
    """Which panel to run against.

    Explicit rather than inferred, because a universe run has no instruments to
    infer from. Mixing classes in one run is refused: a cross-section that ranks
    a Binance pair against a mutual fund NAV is comparing series with different
    calendars, different cost treatment and no shared notion of a trading day.
    """

    instruments: list[str] = Field(default_factory=list)
    """A hand-picked list, which overrides `universe` when non-empty.

    Batches are a convenience, not the only way in: a question like "does this
    work on these eleven banks" is a legitimate backtest and was previously
    unaskable.
    """

    use_cache: bool = True
    workspace: str = ""
    """Which tenant's results this run belongs to. Empty means the default
    single-operator workspace (ADR-040)."""


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


def _intraday_symbols(request: BatchRunRequest) -> list[str]:
    """Which symbols an intraday scan covers.

    Hand-picked instruments win, then the named universe, then whatever has
    minute bars. Always intersected with what actually has minute data, because
    a symbol with daily bars and no minute bars is not a smaller sample - it is
    an absent one.
    """
    # The symbol universe follows the asset class, because a crypto signal on
    # RELIANCE is not a smaller sample, it is a different question.
    if request.asset_class == AssetClass.CRYPTO.value:
        from eulerlab.intraday import crypto_store

        try:
            available = set(crypto_store.symbols())
        except Exception:
            available = set()
    else:
        from eulerlab.intraday import store

        try:
            available = set(store.available_symbols())
        except Exception:
            available = set()

    if request.instruments:
        wanted = [s.strip().upper() for s in request.instruments if s.strip()]
    elif request.asset_class != AssetClass.EQUITY.value:
        # Named batches are equity liquidity slices and mean nothing to another
        # class, so the whole landed universe is the universe.
        wanted = sorted(available)
    elif request.universe != ALL_INSTRUMENTS:
        wanted = list(catalog.universe(request.universe))
    else:
        wanted = sorted(available)

    kept = [s for s in wanted if not available or s in available]
    return kept[:INTRADAY_SYMBOL_CAP]


def _run_intraday(strategy_id: str, request: BatchRunRequest) -> dict[str, Any]:
    """Scan one paper signal across minute bars and shape the result like a
    backtest.

    The Sharpe here is computed over **per-session** returns, not per-day
    returns of a continuously held portfolio. An intraday signal is flat
    overnight and flat on any session it does not fire, so a session it sat out
    contributes a zero - which is a real zero, not a missing observation. That
    makes this comparable to a daily Sharpe in construction but not in meaning,
    and the tier is recorded as `intraday` so the two are never silently
    ranked against each other.
    """
    from datetime import timedelta

    from eulerlab.intraday import paper_scan

    symbols = _intraday_symbols(request)
    if not symbols:
        msg = "no symbols with minute bars for that selection"
        raise RuntimeError(msg)

    # Timezone-explicit: `date.today()` means whatever the running machine's
    # locale says, and an intraday window that silently shifts by a day is the
    # kind of bug that never surfaces as an error.
    end = datetime.now(UTC).astimezone(IST).date()
    start = end - timedelta(days=request.days)
    scans = paper_scan.scan_many(
        strategy_id, symbols, start=start, end=end, asset_class=request.asset_class
    )
    if not scans:
        msg = f"no minute bars readable for any of {len(symbols)} symbols"
        raise RuntimeError(msg)

    # Per-session profit and loss, summed across symbols.
    by_session: dict[date, float] = {}
    sessions_seen: set[date] = set()
    fills = 0
    for scan in scans:
        for trade in scan.trades:
            if not trade.filled or trade.entry_ts is None:
                continue
            fills += 1
            day = trade.entry_ts.date()
            by_session[day] = by_session.get(day, 0.0) + trade.net_pnl()
    for scan in scans:
        for trade in scan.trades:
            if trade.entry_ts is not None:
                sessions_seen.add(trade.entry_ts.date())

    if fills == 0:
        msg = (
            f"no trade filled across {len(symbols)} symbols in {request.days} days. "
            f"The signal either never fired or never filled - check the rejection "
            f"reasons rather than reading this as a zero result."
        )
        raise RuntimeError(msg)

    cash = 1_000_000.0
    equity = [cash]
    for day in sorted(by_session):
        cash += by_session[day]
        equity.append(cash)

    returns = [b / a - 1.0 for a, b in pairwise(equity) if a > 0]
    stats = sharpe_stats(returns, periods_per_year=INTRADAY_SESSIONS_PER_YEAR)
    return {
        "sharpe": round(stats.sharpe, 4),
        "total_return": round(equity[-1] / 1_000_000.0 - 1.0, 6),
        "max_drawdown": round(_drawdown(equity), 6),
        "fills": fills,
        "costs": round(sum(t.costs for s in scans for t in s.trades), 2),
        "days": len(equity) - 1,
        "universe": _universe_label(request),
        "universe_size": len(symbols),
        "symbols": len({s.symbol for s in scans if s.trades}),
        "asset_class": request.asset_class,
        "cost_mode": cost_mode_for(request.asset_class),
        "curve": result_store.downsample(equity),
        "sessions_scanned": sum(s.sessions for s in scans),
        "symbol_cap": INTRADAY_SYMBOL_CAP,
    }


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
                params=_run_params(request),
            )
            for name in request.strategies
        ]

        def compute(item: _BatchItem) -> dict[str, Any]:
            declaration = REGISTRY.get(item.strategy_id)
            if declaration is None:
                msg = f"unknown strategy {item.strategy_id!r}"
                raise KeyError(msg)
            if not declaration.is_strategy_subclass:
                # Intraday signals run through the minute-bar scanner instead of
                # refusing. They still cannot satisfy the `Strategy` interface —
                # a conditional entry with a bracket is not a target weight
                # (ADR-037) — but "cannot be expressed as weights" is not the
                # same as "cannot be evaluated", and treating it as such left
                # eleven coded strategies unrunnable from the interface.
                if item.strategy_id in PAPER_SIGNALS:
                    intraday = _run_intraday(item.strategy_id, request)
                    intraday["tier"] = "intraday"
                    store_one(item, intraday)
                    return intraday
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
            rows, universe_size, resolved = _universe_rows(
                rows,
                request.universe,
                request.instruments,
                # A named equity batch means nothing to a crypto or fund panel;
                # for those the whole panel is the universe unless instruments
                # were picked.
                whole_panel=request.asset_class != AssetClass.EQUITY.value,
            )

            strategy = _build_registered(item.strategy_id)
            engine = _engine_run(
                strategy,
                rows,
                days_window=request.days,
                tier=request.tier,
                starting_cash=1_000_000.0,
                rebalance=21,
                universe=index_key(_universe_label(request), resolved, request.asset_class),
                cost_mode=cost_mode_for(request.asset_class),
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
                "total_return": round(engine.equity[-1] / 1_000_000.0 - 1.0, 6),
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
                    starting_cash=1_000_000.0,
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
            result_store.record(
                workspace,
                result_store.Run(
                    strategy_id=item.strategy_id,
                    sharpe=_as_float(payload, "sharpe"),
                    total_return=_as_float(payload, "total_return"),
                    max_drawdown=_as_float(payload, "max_drawdown"),
                    fills=int(_as_float(payload, "fills")),
                    days=int(_as_float(payload, "days")),
                    tier=str(payload.get("tier") or request.tier),
                    window_days=request.days,
                    universe=_universe_label(request),
                    asset_class=request.asset_class,
                    cost_mode=cost_mode_for(request.asset_class),
                    symbols=int(_as_float(payload, "symbols")),
                    data_version=batch_data_version(),
                    params=dict(item.params),
                    curve=_as_curve(payload),
                    # Screening spends no trial (T-3321). The honest value, and
                    # what lets the library report how much of its own evidence
                    # the noise bar has never seen.
                    trial_recorded=False,
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
        # `compute` stores its own result now, but a cache hit never calls it —
        # and a cached result is still a result, the same numbers just not
        # recomputed. Recording it again is free: the configuration key makes it
        # supersede rather than duplicate.
        for item_outcome in result.outcomes:
            if item_outcome.error or not item_outcome.result:
                continue
            store_one(item_outcome.item, item_outcome.result)

        summary = runner.summarise(result)
        # Every result also goes to the bucket the market data lives in.
        #
        # After the local record, never instead of it. A cloud outage must not
        # turn a completed backtest into a failed one — but it must not be
        # silent either, so the outcome travels back in the job result and the
        # interface can say the mirror is behind.
        mirrored = cloud_results.mirror_quietly(workspace)
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

    check(
        "Satisfies the Strategy interface",
        declaration.is_strategy_subclass,
        "emits target weights"
        if declaration.is_strategy_subclass
        else "intraday bracket shapes cannot be expressed as target weights (ADR-037)",
    )

    supported = [
        c
        for c in catalog.capabilities()
        if c.asset_class == declaration.asset_class and c.timeframe == declaration.timeframe
    ]
    has_data = bool(supported) and supported[0].supported
    check(
        "Data exists for this asset class and timeframe",
        has_data,
        supported[0].detail if supported else "no capability entry for this pair",
    )

    row = next(
        (r for r in strategy_fleet(tenant.ledger) if r.declaration.id == request.strategy), None
    )
    stage = row.stage.value if row else "unknown"
    check(
        "Cleared the gate and is forward-testing",
        stage in {"forward_testing", "live"},
        f"stage is {stage!r}. The forward-test stage is not built (T-3311), so nothing "
        f"can reach it yet — mandate.yaml holds that a strategy is dead until it clears "
        f"the gate, and a screened-only strategy has no evidence behind it"
        if stage not in {"forward_testing", "live"}
        else f"stage is {stage!r}",
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
        from eulerlab.ingest.sync_cloud import main as sync_main

        job.status = "running"
        job.message = "mirroring the landing zone to B2"
        captured = io.StringIO()
        with redirect_stdout(captured):
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

        job = Job(id=uuid.uuid4().hex[:12])
        job.result = {"kind": "sync"}
        JOBS[job.id] = job

    threading.Thread(target=_run_sync, args=(job,), daemon=True).start()
    return {"ok": True, "job": job.id}


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
        panel |= alt_coverage(PANEL.rows())
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


@app.get("/api/cloud/status")
def cloud_status(workspace: str = "") -> dict[str, Any]:
    """Whether results are being mirrored, and how far behind the bucket is.

    `local` is counted from disk. `remote` is one LIST against the bucket, so
    this is a real comparison rather than a record of what the last push
    believed it did.
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
        store = cloud_results.open_store()
        prefix = str(payload["prefix"])
        remote = store.list_sizes(prefix)
        payload["remote_files"] = sorted(key[len(prefix) :] for key in remote)
        payload["reachable"] = True
    except Exception as exc:
        payload["reason"] = f"{type(exc).__name__}: {exc}"
    return payload


@app.post("/api/cloud/mirror")
def cloud_mirror(request: MirrorRequest) -> dict[str, Any]:
    """Pull the bucket's results, merge, then push. Both copies end up equal."""
    tenant = workspace_mod.resolve(request.workspace or None).ensure()
    outcome = cloud_results.mirror_quietly(tenant)
    return {
        "ok": outcome.ok,
        "pushed": outcome.pushed,
        "pulled": outcome.pulled,
        "merged_rows": outcome.merged_rows,
        "failed": outcome.failed,
    }


# --- the full report ----------------------------------------------------------


@app.get("/api/report")
def report(strategy: str, workspace: str = "", configuration: str = "") -> dict[str, Any]:
    """The full analysis of one run.

    Defaults to the configuration behind the strategy's best stored result, so
    the report opens on the run the library is showing. Passing `configuration`
    explicitly opens any other run of the same strategy.
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

    payload = reports.load(tenant, strategy, target)
    if payload is None:
        return {
            "ok": False,
            "error": (
                "no report stored for that run. Reports are written when a backtest runs, "
                "so a result recorded before reports existed has none — re-run it to get one."
            ),
            "runs": [_run_choice(run) for run in runs],
        }
    return {"ok": True, "report": payload, "runs": [_run_choice(run) for run in runs]}


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


@app.get("/api/explain")
def explain(strategy: str = "") -> dict[str, Any]:
    """What a backtest here actually does, and what this strategy is.

    Every number in the procedure section is the value the engine uses, not a
    description of what it might use. A page that explains a run the code does
    not perform is worse than no explanation.
    """
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
            "title": "Warmup",
            "body": (
                "The first stretch of every run is discarded so features have history to "
                "compute from — a quarter of the window, capped at 253 days and floored "
                "at 20. A strategy whose lookback is longer than the window will hold "
                "nothing and the run refuses rather than reporting a Sharpe of zero."
            ),
        },
        {
            "title": "Tier A and Tier B",
            "body": (
                "Tier A is a vectorised screen: fast, and it assumes it can transact at "
                "the price it saw. Tier B is the event-driven engine that the paper and "
                "live paths also use — it places orders, they can be rejected, and cash "
                "has to be there. A Tier A number read as a Tier B number is worse than "
                "no number."
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
        rows = _rows_for(asset_class, days)
        every = _rows_for(asset_class, 0)
    except (FileNotFoundError, OSError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}
    if not rows:
        return {"ok": False, "error": _no_panel_message(asset_class)}

    all_days = trading_days(every)
    picked = trading_days(rows)
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

QUOTES_DEADLINE = 15.0
"""Seconds the snapshot waits for a live quote before rendering without one."""

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


def _quotes_band(symbols: list[str]) -> dict[str, Any]:
    """Live prices for the movers, broker first.

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
        with ThreadPoolExecutor(1) as pool:
            result = pool.submit(quotes.live, symbols).result(timeout=QUOTES_DEADLINE)
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
    feed = [row(i) for i in newsfeed.tape(by_symbol, limit=NEWS_TAPE)]
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


@app.get("/api/snapshot")
def snapshot(workspace: str = "") -> dict[str, Any]:
    """The trader's first screen, computed from the panel.

    Five bands (docs/RESEARCH/021): regime, the map, movers, cross-asset, and
    evidence. Each reports what it can measure and says plainly what it cannot
    — a band that names its missing source is a shopping list, whereas a band
    quietly omitted is invisible.
    """
    tenant = workspace_mod.resolve(workspace or None)
    try:
        rows = PANEL.rows(400)
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
    clearing = [r for r in fleet_rows if _clears(tenant, r, bar)]

    return {
        "ok": True,
        "as_of": today.isoformat(),
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
        "quotes": _quotes_band(
            [str(t["symbol"]) for t in [*by_move[:SNAPSHOT_MOVERS], *by_move[-SNAPSHOT_MOVERS:]]]
        ),
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
