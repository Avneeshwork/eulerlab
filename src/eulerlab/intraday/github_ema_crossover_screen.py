"""Fixed NSE test of a public GitHub 5/15 EMA crossover baseline.

The source describes an options-feature HMM regime filter. The local stock
archive has OHLCV only, so this screen tests its stated price-only crossover
baseline and records the omitted filter as a data blocker.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any

from eulerlab.costs.schedule import Side
from eulerlab.intraday import india_papers as ip
from eulerlab.intraday import inside_bar_screen as ib
from eulerlab.intraday import research_screen as rs
from eulerlab.intraday import screen_common as sc

OUT = Path("data/derived/github_ema_crossover_stock_strategies.json")
SYMBOLS = ("RELIANCE", "HDFCBANK", "ICICIBANK", "TCS", "INFY")
CAPITAL = 1_000_000.0
NOTIONAL = CAPITAL / len(SYMBOLS)
FAST = 5
SLOW = 15
SLIPPAGE_BPS = 2.0
EVAL_START = date(2024, 1, 1)
DATA_END = date(2024, 11, 30)
EXIT_MINUTE = 355  # 15:10


def _cross_signal(previous: float | None, current: float, bars_before: int) -> int:
    """Return the crossover direction after the slow EMA has warmed up."""
    if previous is None or bars_before < SLOW:
        return 0
    if previous <= 0 < current:
        return 1
    if previous >= 0 > current:
        return -1
    return 0


def _run(data: Mapping[str, Sequence[ip.Day]]) -> dict[str, Any]:
    gross: dict[date, float] = defaultdict(float)
    net: dict[date, float] = defaultdict(float)
    sessions_seen: set[date] = set()
    trades: list[dict[str, Any]] = []
    for symbol, sessions in data.items():
        ema_fast: float | None = None
        ema_slow: float | None = None
        previous_difference: float | None = None
        bars_processed = 0
        for day in sessions:
            bars = ib._five_minute_bars(day)
            if EVAL_START <= day.day <= DATA_END:
                sessions_seen.add(day.day)
            position: dict[str, Any] | None = None

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
                direction = int(position["direction"])
                quantity = int(position["quantity"])
                entry = float(position["entry"])
                pnl = direction * (price - entry) * quantity
                entry_side = Side.BUY if direction > 0 else Side.SELL
                exit_side = Side.SELL if direction > 0 else Side.BUY
                costs = sc.intraday_fee(
                    entry, quantity, entry_side, closing_day.day
                ) + sc.intraday_fee(price, quantity, exit_side, closing_day.day)
                costs += (entry + price) * quantity * SLIPPAGE_BPS / 10_000.0
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
                close = bar.close
                if ema_fast is None:
                    ema_fast = ema_slow = close
                    bars_processed += 1
                    continue
                fast_alpha, slow_alpha = 2.0 / (FAST + 1), 2.0 / (SLOW + 1)
                ema_fast += fast_alpha * (close - ema_fast)
                assert ema_slow is not None
                ema_slow += slow_alpha * (close - ema_slow)
                difference = ema_fast - ema_slow
                signal = _cross_signal(previous_difference, difference, bars_processed)
                previous_difference = difference
                bars_processed += 1

                next_index = index + 1
                if (
                    not signal
                    or not EVAL_START <= day.day <= DATA_END
                    or next_index >= len(bars)
                    or bars[next_index].start >= EXIT_MINUTE
                    or bars[next_index].start != bar.start + ib.BAR_MINUTES
                ):
                    continue
                fill_bar = bars[next_index]
                if position is not None:
                    if int(position["direction"]) == signal:
                        continue
                    close_position(fill_bar.start, fill_bar.open, "opposite_cross")
                entry = fill_bar.open
                quantity = max(1, int(NOTIONAL / entry))
                position = {
                    "direction": signal,
                    "entry_minute": fill_bar.start,
                    "entry": entry,
                    "quantity": quantity,
                }

            if position is not None and EVAL_START <= day.day <= DATA_END:
                fill = day.fill_at(EXIT_MINUTE)
                if fill is not None:
                    close_position(fill[0], fill[1], "time_exit")

    dates = sorted(sessions_seen)
    completed = len(trades)
    positive = [
        row["gross_pnl"] - row["costs"] for row in trades if row["gross_pnl"] - row["costs"] > 0
    ]
    negative = [
        row["gross_pnl"] - row["costs"] for row in trades if row["gross_pnl"] - row["costs"] < 0
    ]
    return {
        "id": "nse_github_ema_5_15_crossover",
        "params": {
            "bar_minutes": ib.BAR_MINUTES,
            "fast_ema": FAST,
            "slow_ema": SLOW,
            "entry": "next 5-minute open after a completed-bar crossover",
            "opposite_signal": "close and reverse at next 5-minute open",
            "session_exit": "15:10",
            "max_positions_per_stock": 1,
            "slippage_bps_per_side": SLIPPAGE_BPS,
            "regime_filter": "not applied: source HMM inputs require options/futures fields not in the stock OHLCV archive",
        },
        "window": [EVAL_START.isoformat(), DATA_END.isoformat()],
        "capital_rupees": CAPITAL,
        "gross": sc.daily_stats([gross[day] for day in dates]),
        "net": sc.daily_stats([net[day] for day in dates]),
        "trades": completed,
        "net_winning_trades": sum(row["gross_pnl"] - row["costs"] > 0 for row in trades),
        "net_profit_factor": round(sum(positive) / abs(sum(negative)), 3) if negative else None,
        "fills": 2 * completed,
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
        "source": "Kite NSE one-minute OHLCV archive; files crossing 2024-11-30 are excluded",
        "universe": list(SYMBOLS),
        "window": [EVAL_START.isoformat(), DATA_END.isoformat()],
        "evaluation_sessions_common": len(common),
        "assumptions": [
            "Five fixed large-cap names; no point-in-time universe or survivorship correction.",
            "Equal ₹200,000 notional per stock against ₹1,000,000 capital; no leverage.",
            "The rule is the public repository's EMA(5/15) crossover and next-bar-open execution, adapted to individual NSE shares.",
            "The source's options/futures-feature HMM regime gate is omitted because the local equity archive has no option chain or futures basis fields.",
            "At each opposite crossover, close and reverse at the next contiguous 5-minute open; flatten remaining positions at 15:10.",
            "Date-aware NSE intraday charges plus assumed 2 bp slippage per side. No parameter search or post-cutoff data access.",
        ],
        "runs": [_run(data)],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, help="optional local parquet root for tests")
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
    return sc.write_and_print(args.output, run_all(root=args.root))


if __name__ == "__main__":
    raise SystemExit(main())
