"""Fixed NSE screen of Chesler's Hikkake false-breakout strategy.

The source entry must trigger within three bars of the setup. The local
adaptation uses 5-minute bars, source-style pattern and 6x ATR stops, and
flattens by 15:10. All fills are costed; no parameters are selected on 2024.
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
from eulerlab.paths import data_path

OUT = data_path("derived/hikkake_stock_strategies.json")
SYMBOLS = ("RELIANCE", "HDFCBANK", "ICICIBANK", "TCS", "INFY")
CAPITAL = 1_000_000.0
NOTIONAL = CAPITAL / len(SYMBOLS)
SLIPPAGE_BPS = 2.0
EVAL_START = date(2024, 1, 1)
DATA_END = rs.DATA_END
EXIT_MINUTE = 355
TICK = 0.05
ATR_LENGTH = 20
ATR_MULTIPLIER = 6.0
ENTRY_WINDOW_BARS = 3


def _atr(bars: Sequence[ib.Bar], index: int) -> float | None:
    if index + 1 < ATR_LENGTH:
        return None
    first = index - ATR_LENGTH + 1
    ranges = []
    for i in range(first, index + 1):
        previous_close = bars[i - 1].close if i > 0 else bars[i].open
        bar = bars[i]
        ranges.append(
            max(bar.high - bar.low, abs(bar.high - previous_close), abs(bar.low - previous_close))
        )
    return sum(ranges) / len(ranges)


def _setup(bars: Sequence[ib.Bar], index: int) -> dict[str, float | int] | None:
    """Find strict inside bar followed by the source's opposite-range Hikkake bar."""
    if index < 2 or bars[index - 1].start != bars[index - 2].start + ib.BAR_MINUTES:
        return None
    mother, inside, hikkake = bars[index - 2], bars[index - 1], bars[index]
    if hikkake.start != inside.start + ib.BAR_MINUTES:
        return None
    if not (inside.high < mother.high and inside.low > mother.low):
        return None
    if hikkake.high < inside.high and hikkake.low < inside.low:
        direction = 1
        trigger = inside.high + TICK
    elif hikkake.high > inside.high and hikkake.low > inside.low:
        direction = -1
        trigger = inside.low - TICK
    else:
        return None
    atr = _atr(bars, index)
    if atr is None:
        return None
    return {
        "direction": direction,
        "setup_index": index,
        "trigger": trigger,
        "atr": atr,
        "pattern_start": inside.start,
    }


def _entry(
    bars: Sequence[ib.Bar], setup: Mapping[str, float | int]
) -> dict[str, float | int] | None:
    direction = int(setup["direction"])
    trigger = float(setup["trigger"])
    setup_index = int(setup["setup_index"])
    previous_start = bars[setup_index].start
    for offset in range(1, ENTRY_WINDOW_BARS + 1):
        index = setup_index + offset
        if index >= len(bars):
            return None
        bar = bars[index]
        if bar.start != previous_start + ib.BAR_MINUTES:
            return None
        previous_start = bar.start
        crossed = bar.high >= trigger if direction > 0 else bar.low <= trigger
        if not crossed:
            continue
        entry = max(bar.open, trigger) if direction > 0 else min(bar.open, trigger)
        pattern_bars = bars[int(setup["setup_index"]) - 1 : index + 1]
        if direction > 0:
            pattern_stop = min(bar.low for bar in pattern_bars) - TICK
        else:
            pattern_stop = max(bar.high for bar in pattern_bars) + TICK
        atr_stop = entry - direction * float(setup["atr"]) * ATR_MULTIPLIER
        stop = max(pattern_stop, atr_stop) if direction > 0 else min(pattern_stop, atr_stop)
        if direction * (entry - stop) <= 0:
            return None
        return {
            "direction": direction,
            "setup_index": setup_index,
            "pattern_start": int(setup["pattern_start"]),
            "entry_index": index,
            "signal_start": bar.start,
            "entry_start": bar.start,
            "entry": entry,
            "stop": stop,
            "trigger": trigger,
            # If entry and pattern stop coexist in the trigger bar, use the
            # conservative stop-first assumption because 5-minute path is unknown.
            "trigger_bar_stop_first": int(bar.low <= stop if direction > 0 else bar.high >= stop),
        }
    return None


def _exit(
    day: ip.Day, bars: Sequence[ib.Bar], trade: Mapping[str, float | int]
) -> tuple[int, float, str]:
    direction = int(trade["direction"])
    stop = float(trade["stop"])
    entry_index = int(trade["entry_index"])
    entry_bar = bars[entry_index]
    if trade["trigger_bar_stop_first"]:
        return entry_bar.start, stop, "trigger_bar_stop_first"
    for bar in bars[entry_index + 1 :]:
        if bar.start >= EXIT_MINUTE:
            break
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
    fill = day.fill_at(EXIT_MINUTE)
    if fill is not None:
        return fill[0], fill[1], "time_exit"
    last = min(day.last, EXIT_MINUTE)
    return last, day.close[last], "last_close"


def _run(data: Mapping[str, Sequence[ip.Day]]) -> dict[str, Any]:
    gross: dict[date, float] = defaultdict(float)
    net: dict[date, float] = defaultdict(float)
    days_seen: set[date] = set()
    trades: list[dict[str, Any]] = []
    for symbol, sessions in data.items():
        for day in sessions:
            if not EVAL_START <= day.day <= DATA_END:
                continue
            days_seen.add(day.day)
            bars = ib._five_minute_bars(day)
            for index in range(ATR_LENGTH - 1, len(bars) - 1):
                setup = _setup(bars, index)
                if setup is None:
                    continue
                trade = _entry(bars, setup)
                if trade is None:
                    continue
                exit_minute, exit_price, reason = _exit(day, bars, trade)
                entry_price = float(trade["entry"])
                direction = int(trade["direction"])
                quantity = max(1, int(NOTIONAL / entry_price))
                pnl = direction * (exit_price - entry_price) * quantity
                entry_side = Side.BUY if direction > 0 else Side.SELL
                exit_side = Side.SELL if direction > 0 else Side.BUY
                fees = sc.intraday_fee(
                    entry_price, quantity, entry_side, day.day
                ) + sc.intraday_fee(exit_price, quantity, exit_side, day.day)
                fees += (entry_price + exit_price) * quantity * SLIPPAGE_BPS / 10_000.0
                gross[day.day] += pnl / CAPITAL
                net[day.day] += (pnl - fees) / CAPITAL
                trades.append(
                    {
                        "symbol": symbol,
                        "day": day.day.isoformat(),
                        "side": "long" if direction > 0 else "short",
                        "setup_minute": int(trade["pattern_start"]),
                        "trigger_minute": int(trade["signal_start"]),
                        "entry_minute": int(trade["entry_start"]),
                        "exit_minute": exit_minute,
                        "entry": round(entry_price, 4),
                        "stop": round(float(trade["stop"]), 4),
                        "exit": round(exit_price, 4),
                        "exit_reason": reason,
                        "gross_pnl": round(pnl, 2),
                        "costs": round(fees, 2),
                    }
                )
                break  # one setup/trade per stock/session in this screen
    dates = sorted(days_seen)
    return {
        "id": "nse_hikkake_failed_inside_bar",
        "params": {
            "bar_minutes": ib.BAR_MINUTES,
            "setup": "strict inside bar followed by lower-high/lower-low bullish Hikkake or higher-high/higher-low bearish Hikkake",
            "entry": "one tick through inside-bar extreme within next three 5-minute bars",
            "pattern_stop": "one tick beyond outermost formation extreme",
            "atr_length": ATR_LENGTH,
            "atr_stop_multiple": ATR_MULTIPLIER,
            "session_exit": "15:10",
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
        "source": "Kite NSE one-minute OHLCV archive; files crossing the research window's end are excluded",
        "universe": list(SYMBOLS),
        "window": [EVAL_START.isoformat(), DATA_END.isoformat()],
        "evaluation_sessions_common": len(common),
        "assumptions": [
            "Five fixed large-cap names; no point-in-time universe or survivorship correction.",
            "Equal ₹200,000 notional per name; date-aware NSE intraday charges plus 2 bp assumed slippage per side.",
            "Hikkake entry uses source's one-tick stop entry but only after the setup bar closes; trigger may occur within the next three complete 5-minute bars.",
            "Pattern and 6x ATR(20) stops are both active; the tighter stop is used. There is no profit target in the source specification.",
            "One trade per stock/session; all positions flatten at 15:10.",
            "If the entry trigger and pattern stop are both inside the same 5-minute bar, assume stop-first.",
            "No data after the research window's end is opened.",
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
