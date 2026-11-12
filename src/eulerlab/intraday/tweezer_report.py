"""`make tweezer-report` — the operator's Tweezer report, re-measured here.

Runs the Tweezer scan over the report's window on each of its three candle
sizes and states the result in the report's own terms, so the two can be read
side by side: signals, triggered trades, win rate, profit factor, average win
and loss, expectancy and the sum of per-trade returns, by exit and by month.

**Per-trade return is the report's measure**: P&L over the money put in at
entry, in percent, summed rather than compounded. It is shown both gross (as
the report has it, "costs not included") and net of this platform's Indian
equity cost model, because a 1% stop on an intraday trade is close enough to
the round-trip cost that the difference is the result.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import replace
from datetime import date
from typing import Any

from eulerlab.intraday import bracket, scan
from eulerlab.intraday.tweezer import Rules
from eulerlab.paths import data_path

OUT = data_path("derived/tweezer_report.json")

REPORT: dict[str, Any] = {
    "source": "Protective Collar AI, Tweezer Bottom Strategy — Performance & Backtest Report, June 2026",
    "window": ["2025-06-01", "2026-06-30"],
    "signals": 195,
    "triggered": 178,
    "win_rate": 51.12,
    "profit_factor": 2.65,
    "avg_win_pct": 2.97,
    "avg_loss_pct": -1.17,
    "expectancy_pct": 0.947,
    "total_pct": 168.51,
    "max_drawdown_pct": -11.81,
    "by_timeframe": {
        "15": {"signals": 58, "triggered": 56, "win_rate": 51.8, "total_pct": 55.46},
        "30": {"signals": 76, "triggered": 66, "win_rate": 45.5, "total_pct": 50.57},
        "60": {"signals": 61, "triggered": 56, "win_rate": 57.1, "total_pct": 62.48},
    },
    "costs": "not included",
}
"""The report's headline figures, copied from its tables (sections 4, 5, 9)."""


def _pct(trade: bracket.Trade, *, net: bool) -> float:
    invested = trade.entry_price * trade.plan.shares
    if invested <= 0:
        return 0.0
    pnl = trade.net_pnl() if net else trade.gross_pnl()
    return 100.0 * pnl / invested


def _stats(returns: Sequence[float]) -> dict[str, Any]:
    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r <= 0]
    peak = running = drawdown = 0.0
    for r in returns:
        running += r
        peak = max(peak, running)
        drawdown = min(drawdown, running - peak)
    loss_total = -sum(losses)
    return {
        "trades": len(returns),
        "win_rate": round(100.0 * len(wins) / len(returns), 2) if returns else None,
        "profit_factor": round(sum(wins) / loss_total, 2) if loss_total > 0 else None,
        "avg_win_pct": round(sum(wins) / len(wins), 3) if wins else None,
        "avg_loss_pct": round(sum(losses) / len(losses), 3) if losses else None,
        "expectancy_pct": round(sum(returns) / len(returns), 3) if returns else None,
        "total_pct": round(sum(returns), 2),
        "max_drawdown_pct": round(drawdown, 2),
    }


def measure(
    symbols: Sequence[str],
    *,
    start: date,
    end: date,
    timeframe: int,
    hold_sessions: int = 1,
    workers: int = 8,
) -> dict[str, Any]:
    rules = replace(Rules(), timeframe_minutes=timeframe, max_hold_sessions=hold_sessions)
    results = scan.scan_many(symbols, start=start, end=end, rules=rules, workers=workers)
    filled = sorted(
        (t for r in results for t in r.trades if t.filled and t.entry_ts is not None),
        key=lambda t: t.entry_ts or t.plan.signal_ts,
    )
    by_exit: dict[str, list[float]] = defaultdict(list)
    by_month: dict[str, list[float]] = defaultdict(list)
    by_symbol: dict[str, list[float]] = defaultdict(list)
    symbol_of = {id(t): r.symbol for r in results for t in r.trades}
    for trade in filled:
        net = _pct(trade, net=True)
        by_exit[trade.exits[-1].reason if trade.exits else "open"].append(net)
        by_month[(trade.entry_ts or trade.plan.signal_ts).strftime("%Y-%m")].append(net)
        by_symbol[symbol_of[id(trade)]].append(net)
    unavailable = sorted(
        r.symbol for r in results if any(k.startswith("unavailable") for k in r.rejections)
    )
    rejections: dict[str, int] = defaultdict(int)
    for r in results:
        for reason, count in r.rejections.items():
            rejections[reason] += count
    return {
        "timeframe": timeframe,
        "hold_sessions": hold_sessions,
        "symbols": len(symbols),
        "unavailable": unavailable,
        "signals": sum(r.plans for r in results),
        "triggered": len(filled),
        "gross": _stats([_pct(t, net=False) for t in filled]),
        "net": _stats([_pct(t, net=True) for t in filled]),
        "costs_paid": round(sum(t.costs for t in filled), 2),
        "by_exit": {
            k: {"trades": len(v), "total_pct": round(sum(v), 2)} for k, v in by_exit.items()
        },
        "by_month": {
            k: {"trades": len(v), "total_pct": round(sum(v), 2)}
            for k, v in sorted(by_month.items())
        },
        "by_symbol": {
            k: {"trades": len(v), "total_pct": round(sum(v), 2)}
            for k, v in sorted(by_symbol.items())
        },
        "rejections": dict(sorted(rejections.items(), key=lambda kv: -kv[1])[:12]),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tweezer-report")
    parser.add_argument("--universe", default="nifty50")
    parser.add_argument("--from", dest="start", default=REPORT["window"][0])
    parser.add_argument("--to", dest="end", default=REPORT["window"][1])
    parser.add_argument("--timeframes", default="15,30,60")
    parser.add_argument("--hold", default="1", help="max sessions held, comma-separated")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args(argv)

    symbols = scan.universe(args.universe)
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    runs = []
    for hold in (int(x) for x in args.hold.split(",")):
        for tf in (int(x) for x in args.timeframes.split(",")):
            print(
                f"scanning {len(symbols)} symbols, {tf}-min candles, held up to {hold} session(s)"
            )
            runs.append(
                measure(
                    symbols,
                    start=start,
                    end=end,
                    timeframe=tf,
                    hold_sessions=hold,
                    workers=args.workers,
                )
            )

    combined_gross = [r["gross"] for r in runs]
    out = {
        "universe": args.universe,
        "universe_note": "liquidity-ranked top names, not index membership (ADR-008)",
        "window": [args.start, args.end],
        "report": REPORT,
        "runs": runs,
        "total_signals": sum(r["signals"] for r in runs),
        "total_triggered": sum(r["triggered"] for r in runs),
        "gross_totals": [g["total_pct"] for g in combined_gross],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")

    print(
        f"\n{'':18}{'report':>10}"
        + "".join(f"{r['timeframe']:>5}m/{r['hold_sessions']:<2} gross{'net':>8}" for r in runs)
    )
    for key in (
        "trades",
        "win_rate",
        "profit_factor",
        "avg_win_pct",
        "avg_loss_pct",
        "expectancy_pct",
        "total_pct",
        "max_drawdown_pct",
    ):
        report_key = "triggered" if key == "trades" else key
        line = f"{key:18}{REPORT.get(report_key, '')!s:>10}"
        for r in runs:
            line += f"{r['gross'][key]!s:>14}{r['net'][key]!s:>9}"
        print(line)
    print(f"\nwritten to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
