"""Fixed NSE screen of the public GitHub 5-minute Donchian strategy."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict, deque
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any

from eulerlab.costs.schedule import Side
from eulerlab.intraday import india_papers as ip
from eulerlab.intraday import screen_common as sc
from eulerlab.paths import data_path
from eulerlab.strategies.studies import inside_bar as ib
from eulerlab.strategies.studies import research as rs

OUT = data_path("derived/github_donchian_stock_strategies.json")
SYMBOLS = ("RELIANCE", "HDFCBANK", "ICICIBANK", "TCS", "INFY")
CAPITAL = 1_000_000.0
NOTIONAL = CAPITAL / len(SYMBOLS)
ENTRY_WINDOW = 78
EXIT_WINDOW = 39
SLIPPAGE_BPS = 2.0
EVAL_START = date(2024, 1, 1)
DATA_END = rs.DATA_END
EXIT_MINUTE = 355


def _run(data: Mapping[str, Sequence[ip.Day]]) -> dict[str, Any]:
    gross: dict[date, float] = defaultdict(float)
    net: dict[date, float] = defaultdict(float)
    seen: set[date] = set()
    trades: list[dict[str, Any]] = []

    for symbol, sessions in data.items():
        recent_highs: deque[float] = deque(maxlen=ENTRY_WINDOW)
        recent_lows: deque[float] = deque(maxlen=ENTRY_WINDOW)
        position: dict[str, float | int] | None = None
        for day in sessions:
            bars = ib._five_minute_bars(day)
            in_evaluation = EVAL_START <= day.day <= DATA_END
            if in_evaluation:
                seen.add(day.day)
            position = None
            pending: str | None = None

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
                entry = float(position["entry"])
                quantity = int(position["quantity"])
                pnl = (price - entry) * quantity
                costs = sc.intraday_fee(
                    entry, quantity, Side.BUY, closing_day.day
                ) + sc.intraday_fee(price, quantity, Side.SELL, closing_day.day)
                costs += (entry + price) * quantity * SLIPPAGE_BPS / 10_000.0
                if evaluation:
                    gross[closing_day.day] += pnl / CAPITAL
                    net[closing_day.day] += (pnl - costs) / CAPITAL
                    trades.append(
                        {
                            "symbol": closing_symbol,
                            "day": closing_day.day.isoformat(),
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
                if in_evaluation and pending == "enter" and position is None:
                    quantity = max(1, int(NOTIONAL / bar.open))
                    position = {
                        "entry": bar.open,
                        "entry_minute": bar.start,
                        "quantity": quantity,
                    }
                elif in_evaluation and pending == "exit" and position is not None:
                    close_position(bar.start, bar.open, "donchian_exit_channel")
                pending = None

                prior_entry_high = max(recent_highs) if len(recent_highs) == ENTRY_WINDOW else None
                prior_exit_low = (
                    min(list(recent_lows)[-EXIT_WINDOW:])
                    if len(recent_lows) >= EXIT_WINDOW
                    else None
                )
                if (
                    in_evaluation
                    and index + 1 < len(bars)
                    and bars[index + 1].start == bar.start + ib.BAR_MINUTES
                    and bars[index + 1].start < EXIT_MINUTE
                ):
                    if (
                        position is not None
                        and prior_exit_low is not None
                        and bar.close < prior_exit_low
                    ):
                        pending = "exit"
                    elif (
                        position is None
                        and prior_entry_high is not None
                        and bar.close > prior_entry_high
                    ):
                        pending = "enter"
                recent_highs.append(bar.high)
                recent_lows.append(bar.low)

            if position is not None and in_evaluation:
                fill = day.fill_at(EXIT_MINUTE)
                if fill is not None:
                    close_position(fill[0], fill[1], "time_exit")

    dates = sorted(seen)
    return {
        "id": "nse_github_donchian_breakout",
        "params": {
            "bar_minutes": 5,
            "entry_window_bars": ENTRY_WINDOW,
            "exit_window_bars": EXIT_WINDOW,
            "entry": "completed close above prior 78-bar highest high; next open",
            "exit": "completed close below prior 39-bar lowest low; next open; otherwise 15:10",
            "side": "long_only",
            "slippage_bps_per_side": SLIPPAGE_BPS,
        },
        "window": [EVAL_START.isoformat(), DATA_END.isoformat()],
        "capital_rupees": CAPITAL,
        "gross": sc.daily_stats([gross[day] for day in dates]),
        "net": sc.daily_stats([net[day] for day in dates]),
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
        "source": "Kite NSE one-minute OHLCV; files crossing the research window's end are excluded",
        "research": "docs/RESEARCH/107-github-donchian-intraday-nse-screen.md",
        "universe": list(SYMBOLS),
        "window": [EVAL_START.isoformat(), DATA_END.isoformat()],
        "evaluation_sessions_common": len(common),
        "spent_trials": 0,
        "runs": [_run(data)],
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="github-donchian-screen")
    parser.add_argument("--root", type=Path)
    args = parser.parse_args()
    result = run_all(root=args.root)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=1), encoding="utf-8")
    run = result["runs"][0]
    print(
        f"GitHub Donchian(78/39): {run['net']['total_return']:+.2%} net, "
        f"Sharpe {run['net']['sharpe']}, {run['trades']} round trips; "
        f"costs ₹{run['estimated_costs_rupees']:,.0f}"
    )
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
