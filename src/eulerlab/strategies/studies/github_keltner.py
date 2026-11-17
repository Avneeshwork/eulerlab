"""Fixed NSE screen of the public GitHub Keltner Channel baseline.

The source's Backtrader example is long-only: close above the upper
EMA-plus-ATR band enters, close below the EMA middle exits. This translation
uses 5-minute bars, next-bar-open fills, and session square-off.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
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

OUT = data_path("derived/github_keltner_stock_strategies.json")
SYMBOLS = ("RELIANCE", "HDFCBANK", "ICICIBANK", "TCS", "INFY")
CAPITAL = 1_000_000.0
NOTIONAL = CAPITAL / len(SYMBOLS)
PERIOD = 20
ATR_MULTIPLIER = 2.0
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
        ema: float | None = None
        atr: float | None = None
        previous_close: float | None = None
        bars_processed = 0
        for day in sessions:
            bars = ib._five_minute_bars(day)
            in_evaluation = EVAL_START <= day.day <= DATA_END
            position: dict[str, float | int] | None = None
            pending: str | None = None
            if in_evaluation:
                seen.add(day.day)

            def close_position(
                minute: int,
                price: float,
                reason: str,
                *,
                closing_day: ip.Day = day,
                closing_symbol: str = symbol,
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
                if EVAL_START <= closing_day.day <= DATA_END:
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
                fill_bar = bar
                if pending == "enter" and position is None:
                    quantity = max(1, int(NOTIONAL / fill_bar.open))
                    position = {
                        "entry": fill_bar.open,
                        "entry_minute": fill_bar.start,
                        "quantity": quantity,
                    }
                elif pending == "exit" and position is not None:
                    close_position(fill_bar.start, fill_bar.open, "ema_midline_close")
                pending = None

                true_range = bar.high - bar.low
                if previous_close is not None:
                    true_range = max(
                        true_range,
                        abs(bar.high - previous_close),
                        abs(bar.low - previous_close),
                    )
                if ema is None:
                    ema = bar.close
                    atr = true_range
                else:
                    ema += (2.0 / (PERIOD + 1)) * (bar.close - ema)
                    assert atr is not None
                    # Wilder ATR, initialized from the first observed range.
                    atr += (true_range - atr) / PERIOD
                previous_close = bar.close
                bars_processed += 1
                if not in_evaluation:
                    continue
                if bars_processed < PERIOD or atr is None or index + 1 >= len(bars):
                    continue
                next_bar = bars[index + 1]
                if next_bar.start != bar.start + ib.BAR_MINUTES or next_bar.start >= EXIT_MINUTE:
                    continue
                if position is not None:
                    if bar.close < ema:
                        pending = "exit"
                elif bar.close > ema + ATR_MULTIPLIER * atr:
                    pending = "enter"

            if position is not None and EVAL_START <= day.day <= DATA_END:
                fill = day.fill_at(EXIT_MINUTE)
                if fill is not None:
                    close_position(fill[0], fill[1], "time_exit")

    dates = sorted(seen)
    return {
        "id": "nse_github_keltner_channel_breakout",
        "params": {
            "bar_minutes": 5,
            "ema_period": PERIOD,
            "atr_period": PERIOD,
            "atr_multiplier": ATR_MULTIPLIER,
            "side": "long_only",
            "entry": "completed close above EMA + 2 ATR; next 5-minute open",
            "exit": "completed close below EMA; next 5-minute open; otherwise 15:10",
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
        "research": "docs/RESEARCH/106-github-keltner-channel-nse-screen.md",
        "universe": list(SYMBOLS),
        "window": [EVAL_START.isoformat(), DATA_END.isoformat()],
        "evaluation_sessions_common": len(common),
        "spent_trials": 0,
        "runs": [_run(data)],
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="github-keltner-screen")
    parser.add_argument("--root", type=Path)
    args = parser.parse_args()
    result = run_all(root=args.root)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=1), encoding="utf-8")
    run = result["runs"][0]
    print(
        f"GitHub Keltner(20, 2 ATR): {run['net']['total_return']:+.2%} net, "
        f"Sharpe {run['net']['sharpe']}, {run['trades']} round trips; "
        f"costs ₹{run['estimated_costs_rupees']:,.0f}"
    )
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
