"""Fixed NSE minute screen of the GitHub inside-bar breakout rule.

Price data are read only through 2024-11-30. A 5-minute inside bar is followed
by a completed close beyond that inside bar's high/low. Entry is the next
5-minute bar open, with the opposite inside-bar extreme as the structural stop
and a 2R target. This confirmation-and-next-open adaptation is deliberately
conservative and avoids claiming a fill at a price only known intrabar.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from eulerlab.costs.schedule import Side
from eulerlab.intraday import india_papers as ip
from eulerlab.intraday import research_screen as rs
from eulerlab.intraday import screen_common as sc
from eulerlab.paths import data_path

OUT = data_path("derived/inside_bar_stock_strategies.json")
SYMBOLS = ("RELIANCE", "HDFCBANK", "ICICIBANK", "TCS", "INFY")
CAPITAL = 1_000_000.0
NOTIONAL = CAPITAL / len(SYMBOLS)
SLIPPAGE_BPS = 2.0
EVAL_START = date(2024, 1, 1)
DATA_END = date(2024, 11, 30)
EXIT_MINUTE = 355  # 15:10, before broker MIS square-off.
BAR_MINUTES = 5


@dataclass(frozen=True)
class Bar:
    start: int
    open: float
    high: float
    low: float
    close: float
    volume: float


def _five_minute_bars(day: ip.Day) -> list[Bar]:
    """Build complete 5-minute OHLCV bars, skipping the 09:15 print bin."""
    bars: list[Bar] = []
    for start in range(BAR_MINUTES, EXIT_MINUTE, BAR_MINUTES):
        end = min(start + BAR_MINUTES, day.last + 1)
        rows = [
            (
                day.open_[minute],
                day.high[minute],
                day.low[minute],
                day.close[minute],
                day.volume[minute],
            )
            for minute in range(start, end)
            if day.open_[minute] is not None
            and day.high[minute] is not None
            and day.low[minute] is not None
        ]
        if len(rows) < BAR_MINUTES - 1:
            continue
        opens, highs, lows, closes, volumes = zip(*rows, strict=True)
        bars.append(
            Bar(
                start,
                float(opens[0]),
                max(float(value) for value in highs),
                min(float(value) for value in lows),
                float(closes[-1]),
                sum(float(value or 0) for value in volumes),
            )
        )
    return bars


def _signal(bars: Sequence[Bar], index: int) -> dict[str, float | int] | None:
    """Check an inside bar and the immediately following close-confirmation bar."""
    if index < 2 or index + 1 >= len(bars):
        return None
    mother, inside, trigger = bars[index - 2], bars[index - 1], bars[index]
    if inside.start != mother.start + BAR_MINUTES or trigger.start != inside.start + BAR_MINUTES:
        return None
    if not (inside.high < mother.high and inside.low > mother.low):
        return None
    if trigger.close > inside.high:
        direction = 1
        stop = inside.low
    elif trigger.close < inside.low:
        direction = -1
        stop = inside.high
    else:
        return None
    entry = bars[index + 1]
    risk = direction * (entry.open - stop)
    if risk <= 0:
        return None
    target = entry.open + direction * 2.0 * risk
    return {
        "direction": direction,
        "signal_start": trigger.start,
        "entry_start": entry.start,
        "entry": entry.open,
        "stop": stop,
        "target": target,
    }


def _exit(
    day: ip.Day, bars: Sequence[Bar], signal: Mapping[str, float | int]
) -> tuple[int, float, str]:
    direction = int(signal["direction"])
    stop, target = float(signal["stop"]), float(signal["target"])
    entry_start = int(signal["entry_start"])
    for bar in bars:
        if bar.start < entry_start or bar.start >= EXIT_MINUTE:
            continue
        if direction > 0:
            if bar.open <= stop:
                return bar.start, bar.open, "stop_gap"
            if bar.open >= target:
                return bar.start, target, "target_gap"
            hit_stop, hit_target = bar.low <= stop, bar.high >= target
        else:
            if bar.open >= stop:
                return bar.start, bar.open, "stop_gap"
            if bar.open <= target:
                return bar.start, target, "target_gap"
            hit_stop, hit_target = bar.high >= stop, bar.low <= target
        if hit_stop:
            return bar.start, stop, "stop_first" if hit_target else "stop"
        if hit_target:
            return bar.start, target, "target"
    fill = day.fill_at(EXIT_MINUTE)
    if fill is not None:
        return fill[0], fill[1], "time_exit"
    return min(day.last, EXIT_MINUTE), day.close[min(day.last, EXIT_MINUTE)], "last_close"


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
            bars = _five_minute_bars(day)
            trade_taken = False
            index = 2
            while index + 1 < len(bars) and not trade_taken:
                signal = _signal(bars, index)
                if signal is None:
                    index += 1
                    continue
                exit_minute, exit_price, reason = _exit(day, bars, signal)
                entry_price = float(signal["entry"])
                direction = int(signal["direction"])
                quantity = max(1, int(NOTIONAL / entry_price))
                pnl = direction * (exit_price - entry_price) * quantity
                entry_side = Side.BUY if direction > 0 else Side.SELL
                exit_side = Side.SELL if direction > 0 else Side.BUY
                costs = sc.intraday_fee(
                    entry_price, quantity, entry_side, day.day
                ) + sc.intraday_fee(exit_price, quantity, exit_side, day.day)
                costs += (entry_price + exit_price) * quantity * SLIPPAGE_BPS / 10_000.0
                gross[day.day] += pnl / CAPITAL
                net[day.day] += (pnl - costs) / CAPITAL
                trades.append(
                    {
                        "symbol": symbol,
                        "day": day.day.isoformat(),
                        "side": "long" if direction > 0 else "short",
                        "signal_minute": int(signal["signal_start"]),
                        "entry_minute": int(signal["entry_start"]),
                        "exit_minute": exit_minute,
                        "entry": round(entry_price, 4),
                        "stop": round(float(signal["stop"]), 4),
                        "target": round(float(signal["target"]), 4),
                        "exit": round(exit_price, 4),
                        "exit_reason": reason,
                        "gross_pnl": round(pnl, 2),
                        "costs": round(costs, 2),
                    }
                )
                trade_taken = True
            # Every stock is limited to one trade per session in this fixed screen.
    dates = sorted(seen)
    return {
        "id": "nse_inside_bar_breakout_2r",
        "params": {
            "bar_minutes": BAR_MINUTES,
            "pattern": "inside bar strictly within preceding 5-minute mother bar",
            "trigger": "immediately following 5-minute close outside the inside-bar range",
            "entry": "next 5-minute bar open",
            "stop": "opposite inside-bar extreme",
            "target_r": 2.0,
            "max_trades_per_stock_session": 1,
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
        "source": "Kite NSE one-minute OHLCV archive; files crossing 2024-11-30 are excluded",
        "universe": list(SYMBOLS),
        "window": [EVAL_START.isoformat(), DATA_END.isoformat()],
        "evaluation_sessions_common": len(common),
        "assumptions": [
            "Five fixed large-cap names; no point-in-time universe or survivorship correction.",
            "Equal ₹200,000 notional per name; date-aware NSE intraday fees plus 2 bp assumed slippage per side.",
            "A 5-minute close confirms the break, and entry is delayed to the next 5-minute open.",
            "Only one trade per stock/session; all positions exit by 15:10.",
            "Stops fill at the level unless the bar opens beyond it, when they fill at the open.",
            "If stop and target both touch within a 5-minute bar, the stop is assumed first.",
            "The first 09:15 print bin is excluded; incomplete 5-minute bars are skipped.",
            "No data after 2024-11-30 is opened.",
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
