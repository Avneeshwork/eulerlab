"""`make library-sync` — copy each research study's results into the library.

`strategies/studies.py` lists the papers coded as studies. Their numbers live
in the studies' own output files under `data/derived/`; the library reads the
result store. This writes one stored run per published setting, after costs,
so the Strategies page shows each paper's result, how many settings it is one
of, and its curve, next to everything else.

Safe to run again: a setting already stored for the same data window is not
written twice (`Run.configuration`). The source's main setting is written
last, because the library's headline is the most recent run.

Nothing is computed here and no trial is recorded: these are screening runs
of published settings, and each stored run says so (`trial_recorded` false).
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from eulerlab import results as result_store
from eulerlab import workspace as workspace_mod
from eulerlab.paths import data_path
from eulerlab.strategies import studies

DERIVED = data_path("derived")
CAPITAL = 1_000_000.0
TIER = "study"


STANDARD_RUNS = frozenset(
    {
        studies.STOCK_CANDIDATES,
        studies.COMPANY_GITHUB,
        studies.GITHUB_FOLLOWUP,
        studies.GITHUB_MOMENTUM_PULLBACK,
        studies.INSIDE_BAR,
        studies.HIKKAKE,
        studies.GITHUB_EMA,
        studies.SUPERTREND_MTF,
        studies.GITHUB_KELTNER,
        studies.GITHUB_DONCHIAN,
        studies.GITHUB_PIVOT,
        studies.GITHUB_ENGULFING,
        studies.GITHUB_MOMENTUM_BURST,
        studies.INDIA_FIVE,
    }
)
"""Studies whose output is `runs`, each with an `id`, `net` from
`screen_common.daily_stats`, `fills` and `daily` as [day, return] pairs. One
reader for all of them: the thirteen copies it replaced were identical."""


def _curve(returns: Sequence[float]) -> list[float]:
    equity, out = CAPITAL, [CAPITAL]
    for move in returns:
        equity *= 1 + move
        out.append(equity)
    return result_store.downsample(out)


def measured(study: str, payload: Mapping[str, Any], name: str) -> dict[str, Any] | None:
    """One setting's figures from a study's output, or None if it is not there.

    Intraday study outputs store runs by rule name with daily returns, the
    options study stores a return per holding period, and the stock-candidate
    screen stores daily-return runs by strategy ID.
    """
    if study == studies.OPTIONS:
        run = next((r for r in payload["runs"] if r["name"] == name), None)
        if run is None:
            return None
        whole = run["whole"]
        return {
            "sharpe": whole["sharpe"],
            "total_return": whole["total_return"],
            "max_drawdown": whole["max_drawdown"],
            # The study counts holding periods, not orders. Each is opened and
            # closed, and the library treats a run with no fills as never run.
            "fills": 2 * whole["periods"],
            "days": whole["periods"],
            "curve": _curve([float(p[2]) for p in run["periods"]]),
        }
    if study == studies.GOLD_STOCK_SCREEN:
        if name.startswith(("per-symbol one-minute return", "Gini decision tree")):
            key = "stock_tree_run" if name.startswith("Gini decision tree") else "stock_run"
            run = payload.get(key)
            if run is None or run["rule"] != name:
                return None
            net = run["net"]
            daily = run["daily"]
            return {
                "sharpe": net["sharpe"] or 0.0,
                "total_return": net["total_return"],
                "max_drawdown": net["max_drawdown"],
                "fills": 2 * run["events"],
                "days": net["days"],
                "curve": _curve([float(row[1]) for row in daily]),
            }
        run = next((r for r in payload.get("gold_runs", []) if r["rule"] == name), None)
        if run is None:
            return None
        evaluation = run["evaluation_2024_through_2024_11_30"]
        daily = [
            float(move) for day, move in run["daily"] if day >= "2024-01-01" and day <= "2024-11-30"
        ]
        return {
            "sharpe": evaluation["sharpe"] or 0.0,
            "total_return": evaluation["total_return"],
            "max_drawdown": evaluation["max_drawdown"],
            "fills": run["fills"],
            "days": evaluation["days"],
            "curve": _curve(daily),
        }
    if study == studies.MCX_GOLD_BACKTEST:
        if name != "SMA(50), 20 bp dead band, MCX Gold":
            return None
        net = payload.get("net")
        if not isinstance(net, Mapping) or not net.get("sessions"):
            return None
        base_notional = float(payload["starting_contract_notional_rupees"])
        equity = CAPITAL
        curve = [equity]
        for _, pnl in net["daily"]:
            equity += float(pnl) / base_notional * CAPITAL
            curve.append(equity)
        return {
            "sharpe": net["daily_sharpe"] or 0.0,
            "total_return": net["return_on_initial_contract_notional"],
            "max_drawdown": net["max_drawdown_on_initial_contract_notional"],
            "fills": payload["fills"],
            "days": net["sessions"],
            "curve": result_store.downsample(curve),
        }
    if study in STANDARD_RUNS:
        run = next((row for row in payload.get("runs", []) if row.get("id") == name), None)
        if run is None:
            return None
        net = run["net"]
        return {
            "sharpe": net["sharpe"] or 0.0,
            "total_return": net["total_return"],
            "max_drawdown": net["max_drawdown"],
            "fills": int(run["fills"]),
            "days": int(net["days"]),
            "curve": _curve([float(row[1]) for row in run.get("daily", [])]),
        }
    if study == studies.FII_PARTICIPANT_OI:
        run = payload.get("result")
        if not isinstance(run, Mapping) or name != "nse_fii_index_futures_oi_lagged_direction":
            return None
        net = run["net"]
        return {
            "sharpe": net["sharpe"] or 0.0,
            "total_return": net["total_return"],
            "max_drawdown": net["max_drawdown"],
            "fills": int(run["fills"]),
            "days": int(net["days"]),
            "curve": _curve([float(row[1]) for row in run.get("daily", [])]),
        }
    if study == studies.COST_AWARE_ML:
        run = payload.get("portfolio")
        if not isinstance(run, Mapping) or name != "nse_cost_aware_30m_random_forest":
            return None
        net = run["net"]
        return {
            "sharpe": net["sharpe"] or 0.0,
            "total_return": net["total_return"],
            "max_drawdown": net["max_drawdown"],
            "fills": int(run["fills"]),
            "days": int(run["sessions"]),
            "curve": _curve([float(row[1]) for row in run.get("daily", [])]),
        }
    if study == studies.GITHUB_RSI2:
        run = next((row for row in payload.get("runs", []) if row.get("id") == name), None)
        if run is None:
            return None
        net = run["net"]
        return {
            "sharpe": net["sharpe"] or 0.0,
            "total_return": net["total_return"],
            "max_drawdown": net["max_drawdown"],
            "fills": int(run["fills"]),
            "days": int(net["days"]),
            "curve": _curve([float(row[1]) for row in run.get("daily", [])]),
        }
    run = next((r for r in payload["runs"] if r["rule"] == name), None)
    if run is None or not run["net"].get("days"):
        return None
    net = run["net"]
    return {
        "sharpe": net["sharpe"] or 0.0,
        "total_return": net["total_return"],
        "max_drawdown": net["max_drawdown"],
        "fills": 2 * net["trades"],
        "days": net["days"],
        "curve": _curve([float(move) for _, move in run["daily"]]),
    }


def runs_for(entry: Mapping[str, Any], payload: Mapping[str, Any]) -> list[result_store.Run]:
    """A stored run for each of the entry's settings the study has measured."""
    out: list[result_store.Run] = []
    stocks = len(payload.get("universe") or [])
    if entry["study"] == studies.GOLD_STOCK_SCREEN:
        stocks = 1 if entry["id"] == "gold_intraday_ma_rules" else 5
    if entry["study"] == studies.STOCK_CANDIDATES:
        stocks = 4
    if entry["study"] == studies.COMPANY_GITHUB:
        stocks = 4
    if entry["study"] == studies.GITHUB_FOLLOWUP:
        stocks = 4
    if entry["study"] == studies.GITHUB_MOMENTUM_PULLBACK:
        stocks = 5
    if entry["study"] == studies.INSIDE_BAR:
        stocks = 5
    if entry["study"] == studies.HIKKAKE:
        stocks = 5
    if entry["study"] == studies.GITHUB_EMA:
        stocks = 5
    if entry["study"] == studies.SUPERTREND_MTF:
        stocks = 5
    if entry["study"] == studies.FII_PARTICIPANT_OI:
        stocks = 5
    if entry["study"] == studies.GITHUB_KELTNER:
        stocks = 5
    if entry["study"] == studies.GITHUB_DONCHIAN:
        stocks = 5
    if entry["study"] == studies.GITHUB_PIVOT:
        stocks = 5
    if entry["study"] == studies.GITHUB_ENGULFING:
        stocks = 5
    if entry["study"] == studies.GITHUB_MOMENTUM_BURST:
        stocks = 5
    if entry["study"] == studies.GITHUB_RSI2:
        stocks = 5
    for label, name in entry["configurations"].items():
        found = measured(entry["study"], payload, name)
        if found is None:
            continue
        out.append(
            result_store.Run(
                strategy_id=entry["id"],
                sharpe=float(found["sharpe"]),
                total_return=float(found["total_return"]),
                max_drawdown=float(found["max_drawdown"]),
                fills=int(found["fills"]),
                days=int(found["days"]),
                tier=TIER,
                window_days=int(found["days"]),
                # The setting is part of the name, so each published setting is
                # its own configuration and the library counts them.
                universe=f"{entry['instrument']}: {label}",
                asset_class=entry["asset_class"],
                symbols=stocks if "stocks" in entry["instrument"] else 1,
                data_version=str(payload["window"][1]),
                params={"study": entry["study"], "rule": name},
                curve=found["curve"],
                trial_recorded=entry["study"] == studies.STOCK_CANDIDATES,
            )
        )
    return out


def _same_measurement(left: result_store.Run, right: result_store.Run) -> bool:
    """Ignore the write timestamp, but detect a recomputation that changed results."""
    fields = (
        "strategy_id",
        "sharpe",
        "total_return",
        "max_drawdown",
        "fills",
        "days",
        "tier",
        "window_days",
        "data_version",
        "asset_class",
        "cost_mode",
        "universe",
        "symbols",
        "params",
        "curve",
        "trial_recorded",
    )
    return all(getattr(left, field) == getattr(right, field) for field in fields)


def sync(derived: Path = DERIVED, workspace: str | None = None) -> dict[str, tuple[int, int]]:
    """Store what is new. Returns {strategy id: (written, already stored)}."""
    tenant = workspace_mod.resolve(workspace)
    payloads: dict[str, dict[str, Any]] = {}
    report: dict[str, tuple[int, int]] = {}
    for entry in studies.ENTRIES:
        study = entry["study"]
        if study not in payloads:
            path = derived / f"{study}.json"
            payloads[study] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        if not payloads[study]:
            report[entry["id"]] = (0, 0)
            continue
        held = {run.configuration: run for run in result_store.distinct(tenant, entry["id"])}
        written = 0
        runs = runs_for(entry, payloads[study])
        for run in runs:
            previous = held.get(run.configuration)
            changed = previous is not None and not _same_measurement(previous, run)
            if previous is None or changed or (run.trial_recorded and not previous.trial_recorded):
                result_store.record(tenant, run)
                written += 1
                held[run.configuration] = run
        report[entry["id"]] = (written, len(runs) - written)
    return report


def main() -> int:
    for strategy, (written, held) in sync().items():
        state = f"{written} stored, {held} already there" if written or held else "study not run"
        print(f"{strategy:<28}{state}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
