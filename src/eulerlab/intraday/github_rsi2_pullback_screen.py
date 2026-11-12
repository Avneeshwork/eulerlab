"""Fixed NSE 5-minute adaptation of the GitHub Connors RSI(2) strategy."""

from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any

from eulerlab.intraday import india_papers as ip
from eulerlab.intraday import inside_bar_screen as ib
from eulerlab.intraday import research_screen as rs
from eulerlab.intraday import screen_common as sc
from eulerlab.paths import data_path

OUT = data_path("derived/github_rsi2_pullback_stock_strategies.json")
SYMBOLS = ("RELIANCE", "HDFCBANK", "ICICIBANK", "TCS", "INFY")
CAPITAL = 1_000_000.0
NOTIONAL_PER_STOCK = CAPITAL / len(SYMBOLS)
RSI_PERIOD = 2
LONG_RSI_MAX = 10.0
SHORT_RSI_MIN = 90.0
FAST_SMA_PERIOD = 5
TREND_SMA_PERIOD = 200
SLIPPAGE_BPS = 2.0
EVAL_START = date(2024, 1, 1)
DATA_END = date(2024, 11, 30)
EXIT_MINUTE = 355  # 15:10


def _sma(values: Sequence[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    for index in range(period - 1, len(values)):
        out[index] = statistics.fmean(values[index - period + 1 : index + 1])
    return out


def _run(data: Mapping[str, Sequence[ip.Day]]) -> dict[str, Any]:
    gross: dict[date, float] = defaultdict(float)
    net: dict[date, float] = defaultdict(float)
    seen: set[date] = set()
    trades: list[dict[str, Any]] = []

    for symbol, sessions in data.items():
        bars_by_day: dict[date, list[ib.Bar]] = {}
        all_bars: list[ib.Bar] = []
        offsets: dict[date, int] = {}
        for session in sessions:
            bars = ib._five_minute_bars(session)
            bars_by_day[session.day] = bars
            offsets[session.day] = len(all_bars)
            all_bars.extend(bars)
        all_closes = [bar.close for bar in all_bars]
        rsi_values = sc.rsi(all_closes, RSI_PERIOD)
        slow_sma = _sma(all_closes, TREND_SMA_PERIOD)
        fast_sma = _sma(all_closes, FAST_SMA_PERIOD)
        for day in sessions:
            if not EVAL_START <= day.day <= DATA_END:
                continue
            seen.add(day.day)
            bars = bars_by_day[day.day]
            offset = offsets[day.day]
            position: dict[str, float | int] | None = None
            index = 0
            while index < len(bars):
                bar = bars[index]
                global_index = offset + index
                current_fast_sma = fast_sma[global_index]
                if position is not None:
                    direction = int(position["direction"])
                    exit_signal = current_fast_sma is not None and (
                        (direction > 0 and bar.close > current_fast_sma)
                        or (direction < 0 and bar.close < current_fast_sma)
                    )
                    if exit_signal:
                        next_index = index + 1
                        if (
                            next_index < len(bars)
                            and bars[next_index].start == bar.start + ib.BAR_MINUTES
                            and bars[next_index].start < EXIT_MINUTE
                        ):
                            exit_minute, exit_price, reason = (
                                bars[next_index].start,
                                bars[next_index].open,
                                "fast_sma_exit_next_open",
                            )
                            exit_index = next_index
                        else:
                            fill = day.fill_at(EXIT_MINUTE)
                            if fill is None:
                                exit_minute, exit_price, reason = (
                                    day.last,
                                    day.close[day.last],
                                    "last_close",
                                )
                            else:
                                exit_minute, exit_price, reason = fill[0], fill[1], "time_exit"
                            exit_index = len(bars)
                        entry, quantity = float(position["entry"]), int(position["quantity"])
                        pnl = direction * (exit_price - entry) * quantity
                        costs = sc.round_trip_cost(
                            entry,
                            exit_price,
                            quantity,
                            day.day,
                            direction,
                            slippage_bps=SLIPPAGE_BPS,
                        )
                        gross[day.day] += pnl / CAPITAL
                        net[day.day] += (pnl - costs) / CAPITAL
                        trades.append(
                            {
                                "symbol": symbol,
                                "day": day.day.isoformat(),
                                "side": "long" if direction > 0 else "short",
                                "signal_minute": position["signal_minute"],
                                "entry_minute": position["entry_minute"],
                                "exit_minute": exit_minute,
                                "entry": round(entry, 4),
                                "exit": round(float(exit_price), 4),
                                "exit_reason": reason,
                                "quantity": quantity,
                                "gross_pnl": round(pnl, 2),
                                "costs": round(costs, 2),
                            }
                        )
                        position = None
                        index = exit_index
                        continue
                    index += 1
                    continue

                if index + 1 >= len(bars) or bar.start >= EXIT_MINUTE:
                    index += 1
                    continue
                rsi = rsi_values[global_index]
                trend_sma = slow_sma[global_index]
                direction = (
                    1
                    if trend_sma is not None
                    and bar.close > trend_sma
                    and rsi is not None
                    and rsi <= LONG_RSI_MAX
                    else (
                        -1
                        if trend_sma is not None
                        and bar.close < trend_sma
                        and rsi is not None
                        and rsi >= SHORT_RSI_MIN
                        else 0
                    )
                )
                next_bar = bars[index + 1]
                if (
                    direction
                    and next_bar.start == bar.start + ib.BAR_MINUTES
                    and next_bar.start < EXIT_MINUTE
                ):
                    entry = next_bar.open
                    quantity = min(int(NOTIONAL_PER_STOCK / entry), int(CAPITAL / entry))
                    if quantity > 0:
                        position = {
                            "direction": direction,
                            "signal_minute": bar.start,
                            "entry_minute": next_bar.start,
                            "entry": entry,
                            "quantity": quantity,
                        }
                        index += 1
                        continue
                index += 1

            if position is not None:
                fill = day.fill_at(EXIT_MINUTE)
                exit_minute, exit_price, reason = (
                    (fill[0], fill[1], "time_exit")
                    if fill is not None
                    else (day.last, day.close[day.last], "last_close")
                )
                direction = int(position["direction"])
                entry, quantity = float(position["entry"]), int(position["quantity"])
                pnl = direction * (exit_price - entry) * quantity
                costs = sc.round_trip_cost(
                    entry,
                    float(exit_price),
                    quantity,
                    day.day,
                    direction,
                    slippage_bps=SLIPPAGE_BPS,
                )
                gross[day.day] += pnl / CAPITAL
                net[day.day] += (pnl - costs) / CAPITAL
                trades.append(
                    {
                        "symbol": symbol,
                        "day": day.day.isoformat(),
                        "side": "long" if direction > 0 else "short",
                        "signal_minute": position["signal_minute"],
                        "entry_minute": position["entry_minute"],
                        "exit_minute": exit_minute,
                        "entry": round(entry, 4),
                        "exit": round(float(exit_price), 4),
                        "exit_reason": reason,
                        "quantity": quantity,
                        "gross_pnl": round(pnl, 2),
                        "costs": round(costs, 2),
                    }
                )

    dates = sorted(seen)
    pnls = [float(row["gross_pnl"]) - float(row["costs"]) for row in trades]
    winners = [value for value in pnls if value > 0]
    losers = [value for value in pnls if value < 0]
    return {
        "id": "nse_github_connors_rsi2_intraday_pullback",
        "params": {
            "bar_minutes": 5,
            "trend_filter": "signal close above/below 200-bar SMA, as in the source timeframe",
            "signal": "continuous Wilder RSI(2) <=10 long / >=90 short",
            "entry": "next contiguous 5-minute open",
            "exit": "completed close above/below same-session SMA(5), next open",
            "square_off": "15:10",
            "notional_per_stock": NOTIONAL_PER_STOCK,
            "slippage_bps_per_side": SLIPPAGE_BPS,
        },
        "window": [EVAL_START.isoformat(), DATA_END.isoformat()],
        "capital_rupees": CAPITAL,
        "gross": sc.daily_stats([gross[day] for day in dates]),
        "net": sc.daily_stats([net[day] for day in dates]),
        "trades": len(trades),
        "fills": 2 * len(trades),
        "net_winners": len(winners),
        "net_win_rate": round(len(winners) / len(trades), 4) if trades else None,
        "net_profit_factor": round(sum(winners) / -sum(losers), 4) if losers else None,
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
        "research": "docs/RESEARCH/111-github-rsi2-intraday-nse.md",
        "universe": list(SYMBOLS),
        "window": [EVAL_START.isoformat(), DATA_END.isoformat()],
        "evaluation_sessions_common": len(common),
        "spent_trials": 0,
        "runs": [_run(data)],
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="github-rsi2-screen")
    parser.add_argument("--root", type=Path)
    args = parser.parse_args()
    result = run_all(root=args.root)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=1), encoding="utf-8")
    run = result["runs"][0]
    print(
        f"GitHub Connors RSI(2) intraday adaptation: {run['net']['total_return']:+.2%} net, "
        f"Sharpe {run['net']['sharpe']}, {run['trades']} trades; "
        f"costs ₹{run['estimated_costs_rupees']:,.0f}"
    )
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
