"""Fixed NSE screen of the public GitHub prior-day pivot breakout rule."""

from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any

from eulerlab.costs.schedule import Side
from eulerlab.intraday import india_papers as ip
from eulerlab.intraday import inside_bar_screen as ib
from eulerlab.intraday import research_screen as rs

OUT = Path("data/derived/github_pivot_stock_strategies.json")
SYMBOLS = ("RELIANCE", "HDFCBANK", "ICICIBANK", "TCS", "INFY")
CAPITAL = 1_000_000.0
NOTIONAL = CAPITAL / len(SYMBOLS)
SLIPPAGE_BPS = 2.0
EVAL_START = date(2024, 1, 1)
DATA_END = date(2024, 11, 30)
EXIT_MINUTE = 355


def _stats(values: Sequence[float]) -> dict[str, float | int | None]:
    equity = peak = 1.0
    drawdown = 0.0
    for change in values:
        equity *= 1.0 + change
        peak = max(peak, equity)
        drawdown = min(drawdown, equity / peak - 1.0)
    deviation = statistics.stdev(values) if len(values) > 1 else 0.0
    return {
        "days": len(values),
        "total_return": round(equity - 1.0, 6),
        "sharpe": round(statistics.fmean(values) / deviation * math.sqrt(252), 3)
        if deviation
        else None,
        "max_drawdown": round(drawdown, 6),
    }


def _day_hlc(day: ip.Day) -> tuple[float, float, float] | None:
    highs = [value for value in day.high[: day.last + 1] if value is not None]
    lows = [value for value in day.low[: day.last + 1] if value is not None]
    if not highs or not lows or day.last < 0:
        return None
    return max(highs), min(lows), day.close[day.last]


def _pivot_levels(previous: tuple[float, float, float]) -> tuple[float, float]:
    high, low, close = previous
    pivot = (high + low + close) / 3.0
    return 2.0 * pivot - low, 2.0 * pivot - high


def _run(data: Mapping[str, Sequence[ip.Day]]) -> dict[str, Any]:
    gross: dict[date, float] = defaultdict(float)
    net: dict[date, float] = defaultdict(float)
    seen: set[date] = set()
    trades: list[dict[str, Any]] = []

    for symbol, sessions in data.items():
        previous: tuple[float, float, float] | None = None
        for day in sessions:
            bars = ib._five_minute_bars(day)
            in_evaluation = EVAL_START <= day.day <= DATA_END
            if in_evaluation:
                seen.add(day.day)
            levels = _pivot_levels(previous) if previous is not None else None
            position: dict[str, float | int] | None = None
            pending: int | None = None

            def close_position(
                minute: int,
                price: float,
                reason: str,
                *,
                closing_day: ip.Day = day,
                closing_symbol: str = symbol,
                evaluation: bool = in_evaluation,
            ) -> None:
                nonlocal position
                if position is None:
                    return
                direction = int(position["direction"])
                entry = float(position["entry"])
                quantity = int(position["quantity"])
                pnl = direction * (price - entry) * quantity
                entry_side = Side.BUY if direction > 0 else Side.SELL
                exit_side = Side.SELL if direction > 0 else Side.BUY
                costs = ib._fee(entry, quantity, entry_side, closing_day.day) + ib._fee(
                    price, quantity, exit_side, closing_day.day
                )
                costs += (entry + price) * quantity * SLIPPAGE_BPS / 10_000.0
                if evaluation:
                    gross[closing_day.day] += pnl / CAPITAL
                    net[closing_day.day] += (pnl - costs) / CAPITAL
                    trades.append(
                        {
                            "symbol": closing_symbol,
                            "day": closing_day.day.isoformat(),
                            "side": "long" if direction > 0 else "short",
                            "entry_minute": int(position["entry_minute"]),
                            "exit_minute": minute,
                            "entry": round(entry, 4),
                            "exit": round(price, 4),
                            "exit_reason": reason,
                            "gross_pnl": round(pnl, 2),
                            "costs": round(costs, 2),
                        }
                    )
                position = None

            for index, bar in enumerate(bars):
                if in_evaluation and pending is not None:
                    target = pending
                    if position is not None and int(position["direction"]) != target:
                        close_position(bar.start, bar.open, "opposite_pivot_break")
                    if position is None:
                        quantity = max(1, int(NOTIONAL / bar.open))
                        position = {
                            "direction": target,
                            "entry": bar.open,
                            "entry_minute": bar.start,
                            "quantity": quantity,
                        }
                pending = None

                if (
                    not in_evaluation
                    or levels is None
                    or index + 1 >= len(bars)
                    or bars[index + 1].start != bar.start + ib.BAR_MINUTES
                    or bars[index + 1].start >= EXIT_MINUTE
                ):
                    continue
                resistance, support = levels
                target = 1 if bar.close > resistance else (-1 if bar.close < support else 0)
                current = int(position["direction"]) if position is not None else 0
                if target and target != current:
                    pending = target

            if position is not None and in_evaluation:
                fill = day.fill_at(EXIT_MINUTE)
                if fill is not None:
                    close_position(fill[0], fill[1], "time_exit")
            previous = _day_hlc(day)

    dates = sorted(seen)
    return {
        "id": "nse_github_prior_day_pivot_breakout",
        "params": {
            "bar_minutes": 5,
            "levels": "prior-session floor pivot R1=2*PP-Low, S1=2*PP-High; PP=(H+L+C)/3",
            "entry": "close above R1 long or below S1 short; next contiguous 5-minute open",
            "exit": "reverse at opposite pivot break; otherwise 15:10",
            "slippage_bps_per_side": SLIPPAGE_BPS,
        },
        "window": [EVAL_START.isoformat(), DATA_END.isoformat()],
        "capital_rupees": CAPITAL,
        "gross": _stats([gross[day] for day in dates]),
        "net": _stats([net[day] for day in dates]),
        "trades": len(trades),
        "fills": 2 * len(trades),
        "estimated_costs_rupees": round(sum(float(row["costs"]) for row in trades), 2),
        "daily": [[day.isoformat(), round(net[day], 8)] for day in dates],
        "trade_log": trades,
    }


def run_all(*, root: Path | None = None) -> dict[str, Any]:
    data = {symbol: rs.load_days(symbol, root=root, cutoff=DATA_END) for symbol in SYMBOLS}
    common = set.intersection(
        *[{day.day for day in days if EVAL_START <= day.day <= DATA_END} for days in data.values()]
    )
    return {
        "source": "Kite NSE one-minute OHLCV; files crossing 2024-11-30 are excluded",
        "research": "docs/RESEARCH/108-github-prior-day-pivot-nse-screen.md",
        "universe": list(SYMBOLS),
        "window": [EVAL_START.isoformat(), DATA_END.isoformat()],
        "evaluation_sessions_common": len(common),
        "spent_trials": 0,
        "runs": [_run(data)],
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="github-pivot-breakout-screen")
    parser.add_argument("--root", type=Path)
    args = parser.parse_args()
    result = run_all(root=args.root)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=1), encoding="utf-8")
    run = result["runs"][0]
    print(
        f"GitHub prior-day pivot breakout: {run['net']['total_return']:+.2%} net, "
        f"Sharpe {run['net']['sharpe']}, {run['trades']} round trips; "
        f"costs ₹{run['estimated_costs_rupees']:,.0f}"
    )
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
