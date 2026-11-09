"""Research 182's screening runs: the six top-down models and the lists they must beat.

Each model is run through the same engine call as the screening batch
(`api.server._engine_run`, Tier B, realistic Indian costs, the liquid universe
the strategy picks itself), on the full window, on each half, and on the full
window at twice the costs. The full run's equity curve also gives each
calendar year's return, which is what "stable 20% a year" has to be judged on.

Screening runs only: nothing here enters the trial ledger or faces the gate,
and nothing reads the holdout (spent 2026-11-06, ADR-143; research 182).
"""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Sequence
from datetime import date
from itertools import pairwise
from pathlib import Path
from typing import Any

OUT = Path("data/derived/topdown_screen.json")

FULL = ("2016-01-01", "2026-09-30")
HALVES = (("2016-01-01", "2020-12-31"), ("2021-01-01", "2026-09-30"))
# The announcement data covers 2021-08 to 2024-11 (`events_daily`).
EVENTS = ("2021-08-01", "2024-11-30")
EVENT_HALVES = (("2021-08-01", "2023-03-31"), ("2023-04-01", "2024-11-30"))

NEW = (
    "screen_topdown_sectors",
    "screen_topdown_quality_momentum",
    "screen_topdown_discount",
    "screen_topdown_pullback",
    "screen_topdown_breakout",
    "india_drift_momentum_topdown",
)
# What each must beat, and the parts the swing filters wrap (research 182's rule).
COMPARE = (
    "screen_consensus_3of5",
    "screen_quality_momentum",
    "nse_github_stocks_on_the_move",
    "screen_swing_mom_weinstein",
    "screen_trend_pullback",
    "screen_52w_breakout",
    "india_drift_momentum_combo",
)
EVENT_IDS = frozenset({"india_drift_momentum_topdown", "india_drift_momentum_combo"})


def _stats(equity: Sequence[float], days: Sequence[date], cash: float) -> dict[str, Any]:
    from eulerlab.api.server import _drawdown
    from eulerlab.validation.statistics import sharpe_stats

    returns = [b / a - 1.0 for a, b in pairwise(equity) if a > 0]
    years = max((days[-1] - days[0]).days / 365.25, 1e-9)
    total = equity[-1] / cash
    # Each calendar year from the previous year's last close (the first from the start).
    by_year: dict[str, float] = {}
    base = equity[0]
    for i, (d, v) in enumerate(zip(days, equity, strict=True)):
        if i == len(days) - 1 or days[i + 1].year != d.year:
            by_year[str(d.year)] = round(v / base - 1.0, 4)
            base = v
    return {
        "sharpe": round(sharpe_stats(returns).sharpe, 4),
        "total_return": round(total - 1.0, 4),
        "cagr": round(total ** (1 / years) - 1.0, 4),
        "max_drawdown": round(_drawdown(list(equity)), 4),
        "by_year": by_year,
    }


def run(strategy_id: str, start: str, end: str, cost_multiplier: float = 1.0) -> dict[str, Any]:
    from eulerlab.api.panels import _rows_for, cost_mode_for
    from eulerlab.api.server import (
        _build_registered,
        _engine_run,
        _universe_rows,
        windowed,
    )
    from eulerlab.strategies import AssetClass

    asset = AssetClass.EQUITY.value
    span = (date.fromisoformat(start), date.fromisoformat(end))
    rows = windowed(_rows_for(asset, 3000), *span)
    rows, _, _ = _universe_rows(rows, "all")
    strategy = _build_registered(strategy_id)
    cash = 1_000_000.0
    began = time.monotonic()
    engine = _engine_run(
        strategy,
        rows,
        asset_class=asset,
        days_window=3000,
        tier="B",
        starting_cash=cash,
        rebalance=int(getattr(strategy, "rebalance_every", 21)),
        universe="all",
        cost_mode=cost_mode_for(asset),
        span=span,
        cost_multiplier=cost_multiplier,
    )
    if not engine.equity or engine.fills == 0:
        return {"window": [start, end], "cost_multiplier": cost_multiplier, "error": "no fills"}
    return {
        "window": [start, end],
        "cost_multiplier": cost_multiplier,
        "fills": engine.fills,
        "costs": round(engine.costs, 2),
        "seconds": round(time.monotonic() - began),
        **_stats(engine.equity, engine.days, cash),
    }


def run_all(ids: Sequence[str], out: Path = OUT) -> dict[str, Any]:
    from eulerlab.research.run_india import benchmark

    have: dict[str, Any] = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
    results: dict[str, Any] = dict(have.get("runs", {}))
    for sid in ids:
        full, halves = (EVENTS, EVENT_HALVES) if sid in EVENT_IDS else (FULL, HALVES)
        print(f"running {sid}...", flush=True)
        got: dict[str, Any] = {
            "full": run(sid, *full),
            "halves": [run(sid, *h) for h in halves],
            "costs_2x": run(sid, *full, cost_multiplier=2.0),
        }
        results[sid] = got
        f = got["full"]
        print(
            f"  sharpe {f.get('sharpe')} cagr {f.get('cagr')} dd {f.get('max_drawdown')} "
            f"halves {[h.get('sharpe') for h in got['halves']]} 2x {got['costs_2x'].get('sharpe')}",
            flush=True,
        )
        payload = {
            "note": "Screening runs (research 182): none is in the trial ledger.",
            "benchmark": {"full": benchmark(*FULL), "events": benchmark(*EVENTS)},
            "runs": results,
        }
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=1, sort_keys=True), encoding="utf-8")
    return results


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="topdown-screen")
    parser.add_argument("--only", default="", help="comma-separated ids; default all")
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args(argv)
    ids = [x for x in args.only.split(",") if x] or [*NEW, *COMPARE]
    run_all(ids, Path(args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
