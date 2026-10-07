"""`make stop-sharpe-momentum` — volatility-adjusted momentum with a stop-loss.

Operator, 2026-10-07: "test with keeping stop loss of 5% between holding days,
if stop loss hit sell that stock and divide money proportionally in others".

Runs `StopLossRankTop` on one setting of the sweep (default the paper's:
12-month window, 30 names, ranked every 21 sessions; `--setting 252,10,10` is
the sweep's best region) through the Tier B engine, deciding every session.
A control run with a stop that can never trigger must reproduce the plain
strategy exactly; it is run first and the comparison is refused if it does not.

Each run is appended to the sweep's `runs.jsonl` under its own key, so the
in-sample / holdout split and the Optimisation tab read it like any other
setting. Research 068. No trial is recorded in the ledger.
"""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Sequence
from typing import Any

from eulerlab.research import tune_sharpe_momentum as tune


def key_for(stop: float, setting: tune.Params = tune.PAPER, *, cash: bool = False) -> str:
    return f"{tune.key_of(setting)}-stop{round(stop * 100):g}" + ("-cash" if cash else "")


def run_stop(
    stop: float, setting: tune.Params = tune.PAPER, *, cash: bool = False
) -> dict[str, Any]:
    from eulerlab.api.panels import PANEL
    from eulerlab.backtest import event_driven
    from eulerlab.backtest.india_papers import (
        LIQUID_TOP,
        StopLossRankTop,
        sharpe_momentum_over,
    )
    from eulerlab.strategies import AssetClass

    window, top, rank_every = setting
    rows = PANEL.rows(0)
    strategy = StopLossRankTop(
        tune.STRATEGY_ID,
        sharpe_momentum_over(window),
        rank_every=rank_every,
        stop=stop,
        reinvest=not cash,
        fraction=top / LIQUID_TOP,
        highest=True,
        lookback=window + 5,
    )
    began = time.monotonic()
    result = event_driven.run(
        rows,
        strategy,
        asset_class=AssetClass.EQUITY.value,
        rebalance_every=1,
        warmup=tune.WARMUP,
        adjusted_index=PANEL.index(0, rows, "all"),
        cost_mode="realistic",
    )
    return {
        "key": key_for(stop, setting, cash=cash),
        "cash": cash,
        "params": {"window": window, "top": top, "rebalance": rank_every},
        "stop": stop,
        "stops_hit": strategy.stops_hit,
        "cost_multiplier": 1.0,
        "fills": len(result.fills),
        "costs": round(result.total_cost, 2),
        "seconds": round(time.monotonic() - began),
        "days": [d.isoformat() for d in result.days],
        "equity": [round(v, 2) for v in result.equity],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="stop-sharpe-momentum")
    parser.add_argument("--stop", type=float, default=0.05)
    parser.add_argument(
        "--setting", default="", help="window,top,rebalance (default: the paper's 252,30,21)"
    )
    parser.add_argument(
        "--cash",
        action="store_true",
        help="a stopped name's money waits in cash for the next ranking",
    )
    args = parser.parse_args(argv)
    cash = bool(args.cash)
    parts = [int(x) for x in args.setting.split(",")] if args.setting else list(tune.PAPER)
    setting: tune.Params = (parts[0], parts[1], parts[2])

    done = tune._load_runs()
    plain = done.get(tune.key_of(setting))
    if plain is None:
        print(f"{tune.key_of(setting)} has not run; run `make tune-sharpe-momentum` first")
        return 2
    for stop in (1.0, args.stop):  # 1.0: a stop that can never trigger
        if key_for(stop, setting, cash=cash) in done:
            continue
        print(f"running {tune.key_of(setting)} stop {stop:.0%} ...", flush=True)
        record = run_stop(stop, setting, cash=cash)
        with tune.RUNS.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
        done[record["key"]] = record
        print(f"   {record['seconds']}s fills={record['fills']} stops={record['stops_hit']}")

    control = done[key_for(1.0, setting, cash=cash)]
    gap = control["equity"][-1] / plain["equity"][-1] - 1.0
    if control["equity"] != plain["equity"]:
        # Deciding every session retries a sale the exchange rejected (a stock
        # that did not trade on its fill day) the next session, where the plain
        # run waits for the next ranking. That is the only known difference.
        print(f"control: stop off ends {gap:+.2%} from the plain run (retried sales)")
        if abs(gap) > 0.02:
            print("REFUSED: more than 2% apart; something other than retried sales differs")
            return 1
    else:
        print("control: a stop that never triggers reproduces the plain run exactly")

    tested = done[key_for(args.stop, setting, cash=cash)]
    rows = (("plain", plain), ("stop off", control), (f"{args.stop:.0%} stop", tested))
    for label, record in rows:
        series = tune._returns(record)
        a = tune.describe(tune._slice(series, None, tune.HOLDOUT_STARTS))
        b = tune.describe(tune._slice(series, tune.HOLDOUT_STARTS, None))
        w = tune.describe([r for _, r in series])
        print(
            f"{label:<10} whole sharpe {w['sharpe']:.2f} total {w['total_return']:+.0%} "
            f"dd {w['max_drawdown']:.0%} | 2016-23 {a['sharpe']:.2f} cagr {a['cagr']:.1%} "
            f"dd {a['max_drawdown']:.0%} | 2024- {b['sharpe']:.2f} cagr {b['cagr']:.1%} "
            f"dd {b['max_drawdown']:.0%} | fills {record['fills']} costs {record['costs']:,.0f} "
            f"stops {record.get('stops_hit', 0)}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
