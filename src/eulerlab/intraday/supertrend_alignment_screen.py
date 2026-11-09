"""Fixed NSE screen of a 15-minute/1-hour Supertrend re-alignment setup."""

from __future__ import annotations

import argparse
import statistics
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

OUT = Path("data/derived/supertrend_alignment_stock_strategies.json")
SYMBOLS = ("RELIANCE", "HDFCBANK", "ICICIBANK", "TCS", "INFY")
CAPITAL = 1_000_000.0
NOTIONAL = CAPITAL / len(SYMBOLS)
EVAL_START = date(2024, 1, 1)
DATA_END = date(2024, 11, 30)
ATR_PERIOD = 10
ATR_MULTIPLIER = 3.0
VOLUME_PERIOD = 20
TARGET_R = 2.0
SLIPPAGE_BPS = 2.0
EXIT_MINUTE = 355


@dataclass(frozen=True)
class Bar:
    start: int
    end: int
    open: float
    high: float
    low: float
    close: float
    volume: float


def _bars(day: ip.Day, width: int) -> list[Bar]:
    result: list[Bar] = []
    for start in range(0, EXIT_MINUTE + width, width):
        end = start + width
        rows = [
            (day.open_[m], day.high[m], day.low[m], day.close[m], day.volume[m])
            for m in range(start, min(end, day.last + 1, ip.MINUTES))
            if m >= ip.FIRST_TRADABLE
            and day.open_[m] is not None
            and day.high[m] is not None
            and day.low[m] is not None
        ]
        if len(rows) < max(1, int(width * 0.8)):
            continue
        opens, highs, lows, closes, volumes = zip(*rows, strict=True)
        result.append(
            Bar(
                start=start,
                end=min(end, day.last + 1, ip.MINUTES),
                open=float(opens[0]),
                high=max(float(value) for value in highs),
                low=min(float(value) for value in lows),
                close=float(closes[-1]),
                volume=sum(float(value or 0) for value in volumes),
            )
        )
    return result


def _supertrend(bars: Sequence[Bar]) -> list[tuple[int, float | None]]:
    """Wilder ATR Supertrend; direction +1 is bullish and -1 bearish."""
    output: list[tuple[int, float | None]] = [(0, None)] * len(bars)
    true_ranges: list[float] = []
    previous_close: float | None = None
    atr: float | None = None
    final_upper: float | None = None
    final_lower: float | None = None
    direction = 0
    for index, bar in enumerate(bars):
        tr = (
            bar.high - bar.low
            if previous_close is None
            else max(
                bar.high - bar.low,
                abs(bar.high - previous_close),
                abs(bar.low - previous_close),
            )
        )
        true_ranges.append(tr)
        if index + 1 < ATR_PERIOD:
            previous_close = bar.close
            continue
        if atr is None:
            atr = statistics.fmean(true_ranges[-ATR_PERIOD:])
        else:
            atr = (atr * (ATR_PERIOD - 1) + tr) / ATR_PERIOD
        midpoint = (bar.high + bar.low) / 2.0
        basic_upper = midpoint + ATR_MULTIPLIER * atr
        basic_lower = midpoint - ATR_MULTIPLIER * atr
        if final_upper is None or final_lower is None:
            final_upper, final_lower = basic_upper, basic_lower
            direction = 1 if bar.close >= midpoint else -1
        else:
            final_upper = (
                basic_upper
                if basic_upper < final_upper
                or (previous_close is not None and previous_close > final_upper)
                else final_upper
            )
            final_lower = (
                basic_lower
                if basic_lower > final_lower
                or (previous_close is not None and previous_close < final_lower)
                else final_lower
            )
            if direction < 0 and bar.close > final_upper:
                direction = 1
            elif direction > 0 and bar.close < final_lower:
                direction = -1
        output[index] = (direction, final_lower if direction > 0 else final_upper)
        previous_close = bar.close
    return output


def _volume_cross(bars: Sequence[Bar], index: int) -> bool:
    if index < VOLUME_PERIOD:
        return False
    previous_mean = statistics.fmean(bars[i].volume for i in range(index - VOLUME_PERIOD, index))
    current_mean = statistics.fmean(
        bars[i].volume for i in range(index - VOLUME_PERIOD + 1, index + 1)
    )
    return bars[index - 1].volume <= previous_mean and bars[index].volume > current_mean


def _exit(day: ip.Day, entry_minute: int, entry: float, stop: float) -> tuple[int, float, str]:
    target = entry + TARGET_R * (entry - stop)
    for minute in range(entry_minute, min(EXIT_MINUTE, day.last + 1)):
        open_, high, low = day.open_[minute], day.high[minute], day.low[minute]
        if open_ is None or high is None or low is None:
            continue
        if open_ <= stop:
            return minute, float(open_), "stop_gap"
        if open_ >= target:
            return minute, float(open_), "target_gap"
        hit_stop, hit_target = low <= stop, high >= target
        if hit_stop:
            return minute, stop, "stop_first" if hit_target else "stop"
        if hit_target:
            return minute, target, "target"
    fill = day.fill_at(EXIT_MINUTE)
    if fill is not None:
        return fill[0], fill[1], "time_exit"
    minute = min(day.last, EXIT_MINUTE)
    return minute, day.close[minute], "last_close"


def _run(data: Mapping[str, Sequence[ip.Day]]) -> dict[str, Any]:
    gross: dict[date, float] = defaultdict(float)
    net: dict[date, float] = defaultdict(float)
    sessions_seen: set[date] = set()
    trades: list[dict[str, Any]] = []
    for symbol, sessions in data.items():
        fifteen: list[tuple[ip.Day, Bar]] = []
        hourly: list[tuple[ip.Day, Bar]] = []
        by_day: dict[date, ip.Day] = {}
        for day in sessions:
            by_day[day.day] = day
            fifteen.extend((day, bar) for bar in _bars(day, 15))
            hourly.extend((day, bar) for bar in _bars(day, 60))
            if EVAL_START <= day.day <= DATA_END:
                sessions_seen.add(day.day)
        fifteen_state = _supertrend([bar for _, bar in fifteen])
        hourly_state = _supertrend([bar for _, bar in hourly])
        hourly_cursor = 0
        latest_hour_direction = 0
        hourly_by_day: dict[date, list[tuple[int, int]]] = defaultdict(list)
        for (hour_day, hour_bar), (direction, _) in zip(hourly, hourly_state, strict=True):
            hourly_by_day[hour_day.day].append((hour_bar.end, direction))
        traded_days: set[date] = set()
        for index, ((day, bar), (direction, line)) in enumerate(
            zip(fifteen, fifteen_state, strict=True)
        ):
            while hourly_cursor < len(hourly):
                hour_day, hour_bar = hourly[hourly_cursor]
                if (hour_day.day, hour_bar.end) > (day.day, bar.end):
                    break
                latest_hour_direction = hourly_state[hourly_cursor][0]
                hourly_cursor += 1
            if (
                index == 0
                or day.day in traded_days
                or not EVAL_START <= day.day <= DATA_END
                or bar.end < 30
                or direction != 1
                or fifteen_state[index - 1][0] != -1
                or latest_hour_direction != 1
                or line is None
                or not _volume_cross([item[1] for item in fifteen], index)
            ):
                continue
            if index + 1 >= len(fifteen):
                continue
            next_day, next_bar = fifteen[index + 1]
            if next_day.day != day.day or next_bar.start != bar.end:
                continue
            entry_minute, entry_price = day.fill_at(bar.end) or (-1, 0.0)
            if entry_minute < bar.end or entry_minute >= min(next_bar.end, EXIT_MINUTE):
                continue
            stop = float(line)
            if entry_price <= stop:
                continue
            exit_minute, exit_price, reason = _exit(day, entry_minute, entry_price, stop)
            quantity = max(1, int(NOTIONAL / entry_price))
            pnl = (exit_price - entry_price) * quantity
            fees = sc.intraday_fee(entry_price, quantity, Side.BUY, day.day) + sc.intraday_fee(
                exit_price, quantity, Side.SELL, day.day
            )
            fees += (entry_price + exit_price) * quantity * SLIPPAGE_BPS / 10_000.0
            gross[day.day] += pnl / CAPITAL
            net[day.day] += (pnl - fees) / CAPITAL
            trades.append(
                {
                    "symbol": symbol,
                    "day": day.day.isoformat(),
                    "side": "long",
                    "signal_minute": bar.end,
                    "entry_minute": entry_minute,
                    "exit_minute": exit_minute,
                    "entry": round(entry_price, 4),
                    "stop": round(stop, 4),
                    "target": round(entry_price + TARGET_R * (entry_price - stop), 4),
                    "exit": round(exit_price, 4),
                    "exit_reason": reason,
                    "gross_pnl": round(pnl, 2),
                    "costs": round(fees, 2),
                }
            )
            traded_days.add(day.day)
    dates = sorted(sessions_seen)
    net_trade_pnls = [row["gross_pnl"] - row["costs"] for row in trades]
    winners = [value for value in net_trade_pnls if value > 0]
    losers = [value for value in net_trade_pnls if value < 0]
    return {
        "id": "nse_supertrend_mtf_volume_reclaim",
        "params": {
            "entry_timeframe_minutes": 15,
            "regime_timeframe_minutes": 60,
            "atr_period": ATR_PERIOD,
            "atr_multiplier": ATR_MULTIPLIER,
            "entry": "15-minute Supertrend flips bearish to bullish while latest completed 1-hour Supertrend is bullish; 15-minute volume crosses above its trailing 20-bar mean",
            "execution": "next 15-minute open; only long entries",
            "stop": "15-minute Supertrend line at signal close",
            "target_r": TARGET_R,
            "max_trades_per_stock_session": 1,
            "session_exit": "15:10",
            "slippage_bps_per_side": SLIPPAGE_BPS,
        },
        "window": [EVAL_START.isoformat(), DATA_END.isoformat()],
        "capital_rupees": CAPITAL,
        "gross": sc.daily_stats([gross[day] for day in dates]),
        "net": sc.daily_stats([net[day] for day in dates]),
        "trades": len(trades),
        "net_winning_trades": sum(value > 0 for value in net_trade_pnls),
        "net_profit_factor": round(sum(winners) / abs(sum(losers)), 3) if losers else None,
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
            "The fixed rule is LeadFinn's 15-minute Supertrend pullback/re-alignment setup: hourly trend bullish, 15-minute trend flips bullish, and 15-minute volume crosses above its 20-bar mean.",
            "The article's setup example uses Supertrend(10,3), the Supertrend line as stop, and a 1:2 target; its written signal is adapted to next 15-minute open execution.",
            "Only long signals are taken; at most one trade per stock/session. Signals before 09:45 are skipped per the source's session guidance.",
            "ATR and Supertrend are computed continuously from prior available 15-minute and 60-minute bars. Only fully completed hourly bars are used for the regime filter.",
            "One-minute OHLC is used for stop/target handling; if both touch within one minute, assume stop first. Positions flatten at 15:10.",
            "Five fixed large-cap names, ₹200,000 notional per stock, date-aware NSE intraday charges and assumed 2 bp slippage per side; no settings were tuned.",
            "No parquet object crossing 2024-11-30 is opened.",
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
