"""Fixed NSE screen of the GitHub 3-bar ATR momentum burst rule.

The source uses a 5-minute move greater than 1.5 ATR, volume above twice the
preceding 20-bar mean, and a 1 ATR trailing stop. This adaptation enters at the
next contiguous bar open and models stop gaps and same-bar stop execution.
"""

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

OUT = Path("data/derived/github_momentum_burst_stock_strategies.json")
SYMBOLS = ("RELIANCE", "HDFCBANK", "ICICIBANK", "TCS", "INFY")
CAPITAL = 1_000_000.0
SYMBOL_SLEEVE = CAPITAL / len(SYMBOLS)
POSITION_FRACTION = 0.03
ATR_PERIOD = 14
LOOKBACK_BARS = 3
MOMENTUM_ATR_MULT = 1.5
VOLUME_AVG_PERIOD = 20
VOLUME_MULT = 2.0
ATR_STOP_MULT = 1.0
MAX_TRADES_PER_SESSION = 2
WARMUP_BARS = 6
SLIPPAGE_BPS = 2.0
EVAL_START = date(2024, 1, 1)
DATA_END = date(2024, 11, 30)
EXIT_MINUTE = 345  # 15:00, as specified by the source.


def _atr(bars: Sequence[ib.Bar], period: int = ATR_PERIOD) -> list[float | None]:
    """Wilder ATR with a complete-period seed; never fills warmup with zeros."""
    out: list[float | None] = [None] * len(bars)
    if len(bars) <= period:
        return out
    true_ranges = [
        max(
            bar.high - bar.low,
            abs(bar.high - bars[index - 1].close),
            abs(bar.low - bars[index - 1].close),
        )
        for index, bar in enumerate(bars)
    ]
    current = statistics.fmean(true_ranges[1 : period + 1])
    out[period] = current
    for index in range(period + 1, len(bars)):
        current = ((period - 1) * current + true_ranges[index]) / period
        out[index] = current
    return out


def _burst(bars: Sequence[ib.Bar], atr_values: Sequence[float | None], index: int) -> int:
    """Return direction if the completed bar confirms the frozen burst rule."""
    if index < LOOKBACK_BARS or index >= len(bars):
        return 0
    atr = atr_values[index]
    if atr is None or atr <= 0:
        return 0
    move = bars[index].close - bars[index - LOOKBACK_BARS].close
    if move > MOMENTUM_ATR_MULT * atr:
        return 1
    if move < -MOMENTUM_ATR_MULT * atr:
        return -1
    return 0


def _fee_cost(entry: float, exit_: float, quantity: int, day: date, direction: int) -> float:
    entry_side = Side.BUY if direction > 0 else Side.SELL
    exit_side = Side.SELL if direction > 0 else Side.BUY
    fees = ib._fee(entry, quantity, entry_side, day)
    fees += ib._fee(exit_, quantity, exit_side, day)
    return fees + (entry + exit_) * quantity * SLIPPAGE_BPS / 10_000.0


def _exit(
    bars: Sequence[ib.Bar],
    atr_values: Sequence[float | None],
    entry_index: int,
    direction: int,
    initial_stop: float,
) -> tuple[int, float, str]:
    stop = initial_stop
    for index in range(entry_index, len(bars)):
        bar = bars[index]
        if bar.start >= EXIT_MINUTE:
            return bar.start, bars[index - 1].close if index else bar.open, "time_exit"
        if direction > 0:
            if bar.open <= stop:
                return bar.start, bar.open, "stop_gap"
            if bar.low <= stop:
                return bar.start, stop, "stop"
        else:
            if bar.open >= stop:
                return bar.start, bar.open, "stop_gap"
            if bar.high >= stop:
                return bar.start, stop, "stop"
        atr = atr_values[index]
        if atr is not None and atr > 0:
            candidate = bar.close - direction * ATR_STOP_MULT * atr
            stop = max(stop, candidate) if direction > 0 else min(stop, candidate)
    last_index = len(bars) - 1
    return bars[last_index].start, bars[last_index].close, "last_close"


def _stats(daily_returns: Sequence[float]) -> dict[str, float | int | None]:
    equity = peak = 1.0
    drawdown = 0.0
    for move in daily_returns:
        equity *= 1.0 + move
        peak = max(peak, equity)
        drawdown = min(drawdown, equity / peak - 1.0)
    deviation = statistics.stdev(daily_returns) if len(daily_returns) > 1 else 0.0
    return {
        "days": len(daily_returns),
        "total_return": round(equity - 1.0, 6),
        "sharpe": round(statistics.fmean(daily_returns) / deviation * math.sqrt(252), 3)
        if deviation
        else None,
        "max_drawdown": round(drawdown, 6),
    }


def _run(data: Mapping[str, Sequence[ip.Day]]) -> dict[str, Any]:
    gross: dict[date, float] = defaultdict(float)
    net: dict[date, float] = defaultdict(float)
    seen: set[date] = set()
    trades: list[dict[str, Any]] = []

    for symbol, sessions in data.items():
        for day in sessions:
            if not EVAL_START <= day.day <= DATA_END:
                continue
            seen.add(day.day)
            bars = ib._five_minute_bars(day)
            atr_values = _atr(bars)
            volumes: list[float] = []
            for bar in bars:
                volumes.append(bar.volume)
            index = 0
            count = 0
            position: dict[str, Any] | None = None
            while index < len(bars):
                bar = bars[index]
                atr = atr_values[index]
                if position is not None:
                    exit_minute, exit_price, reason = _exit(
                        bars, atr_values, index, position["direction"], position["stop"]
                    )
                    # _exit manages this position to its actual close. Book it,
                    # then resume at the bar after that close for any second trade.
                    exit_index = next(
                        (i for i in range(index, len(bars)) if bars[i].start == exit_minute),
                        len(bars) - 1,
                    )
                    direction = int(position["direction"])
                    entry, quantity = float(position["entry"]), int(position["quantity"])
                    pnl = direction * (exit_price - entry) * quantity
                    costs = _fee_cost(entry, exit_price, quantity, day.day, direction)
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
                            "exit": round(exit_price, 4),
                            "exit_reason": reason,
                            "quantity": quantity,
                            "gross_pnl": round(pnl, 2),
                            "costs": round(costs, 2),
                        }
                    )
                    position = None
                    index = exit_index + 1
                    continue

                # The reference rule warms up six bars; ATR(14) naturally
                # keeps signals disabled until a full true-range seed exists.
                if index >= WARMUP_BARS and index < len(bars) - 1 and bar.start < EXIT_MINUTE:
                    direction = _burst(bars, atr_values, index)
                    preceding = bars[max(0, index - VOLUME_AVG_PERIOD) : index]
                    avg_volume = (
                        statistics.fmean([item.volume for item in preceding]) if preceding else 0.0
                    )
                    next_bar = bars[index + 1]
                    if (
                        direction
                        and atr is not None
                        and avg_volume > 0
                        and bar.volume > VOLUME_MULT * avg_volume
                        and next_bar.start == bar.start + ib.BAR_MINUTES
                        and next_bar.start < EXIT_MINUTE
                        and count < MAX_TRADES_PER_SESSION
                    ):
                        entry = next_bar.open
                        initial_stop = bar.close - direction * ATR_STOP_MULT * atr
                        quantity = min(
                            int(CAPITAL * POSITION_FRACTION / entry),
                            int(SYMBOL_SLEEVE / entry),
                        )
                        if quantity > 0:
                            count += 1
                            position = {
                                "direction": direction,
                                "signal_minute": bar.start,
                                "entry_minute": next_bar.start,
                                "entry": entry,
                                "stop": initial_stop,
                                "quantity": quantity,
                            }
                            index += 1
                            continue
                index += 1

    dates = sorted(seen)
    net_pnls = [float(row["gross_pnl"]) - float(row["costs"]) for row in trades]
    winners = [value for value in net_pnls if value > 0]
    losers = [value for value in net_pnls if value < 0]
    return {
        "id": "nse_github_3bar_atr_momentum_burst",
        "params": {
            "bar_minutes": 5,
            "warmup_bars": WARMUP_BARS,
            "burst": "absolute 3-bar close-to-close move > 1.5 * Wilder ATR(14)",
            "volume": "signal bar volume > 2 * prior 20-bar mean volume",
            "entry": "next contiguous 5-minute open",
            "initial_and_trailing_stop": "1 * Wilder ATR(14), updated after each completed bar",
            "max_trades_per_stock_session": MAX_TRADES_PER_SESSION,
            "position_notional": "3% of portfolio capital, capped at ₹200,000 per stock",
            "square_off": "15:00",
            "slippage_bps_per_side": SLIPPAGE_BPS,
        },
        "window": [EVAL_START.isoformat(), DATA_END.isoformat()],
        "capital_rupees": CAPITAL,
        "gross": _stats([gross[day] for day in dates]),
        "net": _stats([net[day] for day in dates]),
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
        "research": "docs/RESEARCH/110-github-momentum-burst-nse.md",
        "universe": list(SYMBOLS),
        "window": [EVAL_START.isoformat(), DATA_END.isoformat()],
        "evaluation_sessions_common": len(common),
        "spent_trials": 0,
        "runs": [_run(data)],
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="github-momentum-burst-screen")
    parser.add_argument("--root", type=Path)
    args = parser.parse_args()
    result = run_all(root=args.root)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=1), encoding="utf-8")
    run = result["runs"][0]
    print(
        f"GitHub 3-bar ATR momentum burst: {run['net']['total_return']:+.2%} net, "
        f"Sharpe {run['net']['sharpe']}, {run['trades']} trades; "
        f"costs ₹{run['estimated_costs_rupees']:,.0f}"
    )
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
