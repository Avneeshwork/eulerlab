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
from eulerlab.strategies import studies

DERIVED = Path("data/derived")
CAPITAL = 1_000_000.0
TIER = "study"


def _curve(returns: Sequence[float]) -> list[float]:
    equity, out = CAPITAL, [CAPITAL]
    for move in returns:
        equity *= 1 + move
        out.append(equity)
    return result_store.downsample(out)


def measured(study: str, payload: Mapping[str, Any], name: str) -> dict[str, Any] | None:
    """One setting's figures from a study's output, or None if it is not there.

    The three studies store their runs in two shapes: the intraday ones by
    `rule` with daily net returns, the options one by `name` with a return
    per holding period.
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
            )
        )
    return out


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
        held = {run.configuration for run in result_store.distinct(tenant, entry["id"])}
        written = 0
        runs = runs_for(entry, payloads[study])
        for run in runs:
            if run.configuration not in held:
                result_store.record(tenant, run)
                written += 1
        report[entry["id"]] = (written, len(runs) - written)
    return report


def main() -> int:
    for strategy, (written, held) in sync().items():
        state = f"{written} stored, {held} already there" if written or held else "study not run"
        print(f"{strategy:<28}{state}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
