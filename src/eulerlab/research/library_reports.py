"""Stored reports for research 166-173's gated strategies, so the library shows them.

Operator, 2026-11-07: "i can't see their report" (H-0161, H-0162). `make
validate` and `make gate` write an evidence pack and a ledger entry but no
stored result, so the Strategies page and the Report page had nothing to show.
This writes, for each gated card, the run on its research window (before the
holdout start; nothing after 2024-11-30 is read) to the workspace result
store with its full report, as `full_history.store` does (ADR-143), and adds
its setting to `full_history_recommended.json` so opening it fills the
backtest controls.

The trades are the ones the gate scored (`validation.intraday.SOURCES`).
`make library-reports` runs it; it spends no trial.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from collections.abc import Sequence
from datetime import date
from typing import Any

from eulerlab.research import full_history as fh

CARDS = (
    "H-0161",
    "H-0162",
    "H-0160",
    "H-0153",
    "H-0146",
    "H-0132",
    "H-0118",
    "H-0121",
    "H-0115",
    "H-0124",
)
"""PROMOTE and PAPER stock cards of research 168-173 (H-0103 is an option rule, out of scope)."""
TIMEFRAME = {"H-0161": "1d", "H-0162": "1d", "H-0153": "1d"}


def _fills_for(hypothesis: str, run: Any) -> tuple[list[Any], int]:
    """(two fills per position, distinct symbols) for the report."""
    from eulerlab.backtest.events import Fill
    from eulerlab.costs.schedule import Side
    from eulerlab.intraday import cross_section as cs

    trades = list(run.trades)
    if trades and isinstance(trades[0], cs.Trade):
        return fh.leg_fills(trades), len({t.symbol for t in trades})
    swings = _swings(hypothesis)
    out = []
    for s in swings:
        buy, sell = s.costs_at()
        out.append(Fill("", s.entry_day, s.symbol, Side.BUY, s.quantity, s.entry, buy))
        out.append(Fill("", s.exit_day, s.symbol, Side.SELL, s.quantity, s.exit, sell))
    return out, len({s.symbol for s in swings})


def _swings(hypothesis: str) -> list[Any]:
    if hypothesis == "H-0162":
        from eulerlab.intraday import daily_universe_screen as du

        ctx = du.Context()
        return du.h0162_positions(ctx.panel, ctx.sessions, ctx.liquid, ctx.promoters)
    from eulerlab.intraday import other_data_screen as od

    return od.h0153(od._context())


def curve(run: Any) -> tuple[list[date], list[float]]:
    pnl: dict[date, float] = defaultdict(float)
    for t in run.trades:
        pnl[t.day] += t.gross - t.costs
    value, equity = float(run.capital), []
    for day in run.sessions:
        value += pnl.get(day, 0.0)
        equity.append(value)
    return list(run.sessions), equity


def setting(hypothesis: str, sessions: Sequence[date], capital: float) -> dict[str, Any]:
    start, end = sessions[0], sessions[-1]
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "window_days": (end - start).days,
        "universe": "nse_500_most_traded" if hypothesis in ("H-0161", "H-0162") else "fo_stocks",
        "tier": "B",
        "asset_class": "equity",
        "timeframe": TIMEFRAME.get(hypothesis, "1m"),
        "capital": capital,
    }


def store_one(hypothesis: str) -> dict[str, Any]:
    from eulerlab import reports, results, workspace
    from eulerlab.validation import intraday

    run = intraday.SOURCES[hypothesis]()
    days, equity = curve(run)
    fills, symbols = _fills_for(hypothesis, run)
    summary = fh.summarise(days, equity)
    chosen = setting(hypothesis, days, float(run.capital))
    params = {
        "start": chosen["start"],
        "end": chosen["end"],
        "capital": chosen["capital"],
        "configuration": "as gated",
        "holdout": "unread (research window only)",
    }
    version = f"research-window {chosen['start']}..{chosen['end']} as gated"
    stored = results.Run(
        strategy_id=hypothesis,
        sharpe=float(summary["sharpe"]),
        total_return=float(summary["total_return"]),
        max_drawdown=float(summary["max_drawdown"]),
        fills=len(fills),
        days=len(equity),
        tier=chosen["tier"],
        window_days=int(chosen["window_days"]),
        data_version=version,
        asset_class=chosen["asset_class"],
        universe=chosen["universe"],
        symbols=symbols,
        params=params,
        curve=results.downsample(list(equity)),
    )
    tenant = workspace.resolve(None)
    results.record(tenant, stored)
    reports.save(
        tenant,
        reports.build(
            strategy_id=hypothesis,
            configuration=stored.configuration,
            universe=chosen["universe"],
            instruments=[],
            tier=chosen["tier"],
            asset_class=chosen["asset_class"],
            window_days=int(chosen["window_days"]),
            equity=equity,
            days=days,
            fills=fills,
            rejections=[],
            marks={},
            starting_cash=float(chosen["capital"]),
            params=params,
            data_version=version,
        ),
    )
    return {"hypothesis": hypothesis, "setting": chosen, **summary, "fills": len(fills)}


def add_recommended(found: Sequence[dict[str, Any]]) -> None:
    settings = fh.load_recommended()
    for one in found:
        settings[one["hypothesis"]] = one["setting"]
    fh.RECOMMENDED_PATH.write_text(json.dumps(settings, indent=1), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(prog="library-reports")
    parser.add_argument("--only", nargs="+", default=list(CARDS))
    args = parser.parse_args()
    found = []
    for hypothesis in args.only:
        one = store_one(hypothesis)
        found.append(one)
        print(
            f"{hypothesis}: stored; Sharpe {one['sharpe']}, total {one['total_return']:.1%}, "
            f"drawdown {one['max_drawdown']:.1%}, {one['years_positive']} years positive"
        )
    add_recommended(found)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
