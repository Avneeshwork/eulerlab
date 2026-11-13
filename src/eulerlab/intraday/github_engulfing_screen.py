"""Fixed NSE screen of a GitHub engulfing + volume + RSI rule.

The source is a crypto example. This adaptation uses strict two-candle body
engulfing, prior-volume EMA confirmation, RSI(14) thresholds, a structural
pattern stop and a 5R target with next-bar execution.
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
from eulerlab.intraday import inside_bar_screen as ib
from eulerlab.intraday import research_screen as rs
from eulerlab.intraday import screen_common as sc
from eulerlab.paths import data_path

OUT = data_path("derived/github_engulfing_stock_strategies.json")
SYMBOLS = ("RELIANCE", "HDFCBANK", "ICICIBANK", "TCS", "INFY")
CAPITAL = 1_000_000.0
NOTIONAL = CAPITAL / len(SYMBOLS)
RISK_FRACTION_PER_SLEEVE = 0.01
RSI_PERIOD = 14
VOLUME_EMA_PERIOD = 14
RISK_REWARD = 5.0
SLIPPAGE_BPS = 2.0
EVAL_START = date(2024, 1, 1)
DATA_END = rs.DATA_END
EXIT_MINUTE = 355


def _engulfing(previous: ib.Bar, current: ib.Bar) -> int:
    """Return +1/-1 for strict bullish/bearish body engulfing; otherwise 0."""
    if (
        previous.close < previous.open
        and current.close > current.open
        and current.open <= previous.close
        and current.close >= previous.open
    ):
        return 1
    if (
        previous.close > previous.open
        and current.close < current.open
        and current.open >= previous.close
        and current.close <= previous.open
    ):
        return -1
    return 0


def _volume_ema(values: Sequence[float], period: int = VOLUME_EMA_PERIOD) -> list[float]:
    if not values:
        return []
    alpha = 2.0 / (period + 1.0)
    out = [float(values[0])]
    for volume in values[1:]:
        out.append(out[-1] + alpha * (float(volume) - out[-1]))
    return out


def _exit(
    day: ip.Day,
    bars: Sequence[ib.Bar],
    entry_index: int,
    direction: int,
    stop: float,
    target: float,
) -> tuple[int, float, str]:
    for bar in bars[entry_index:]:
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
        all_bars: list[tuple[date, ib.Bar]] = []
        session_bars: dict[date, list[ib.Bar]] = {}
        session_days: dict[date, ip.Day] = {}
        for day in sessions:
            bars = ib._five_minute_bars(day)
            session_bars[day.day] = bars
            session_days[day.day] = day
            all_bars.extend((day.day, bar) for bar in bars)
        closes = [bar.close for _, bar in all_bars]
        volumes = [bar.volume for _, bar in all_bars]
        rsi = sc.rsi(closes, RSI_PERIOD)
        volume_ema = _volume_ema(volumes)
        offsets: dict[date, int] = {}
        cursor = 0
        for day in sessions:
            offsets[day.day] = cursor
            cursor += len(session_bars[day.day])

        for day in sessions:
            if not EVAL_START <= day.day <= DATA_END:
                continue
            seen.add(day.day)
            bars = session_bars[day.day]
            offset = offsets[day.day]
            for index in range(1, len(bars) - 1):
                global_index = offset + index
                previous, signal_bar = bars[index - 1], bars[index]
                entry_bar = bars[index + 1]
                if (
                    entry_bar.start != signal_bar.start + ib.BAR_MINUTES
                    or entry_bar.start >= EXIT_MINUTE
                ):
                    continue
                direction = _engulfing(previous, signal_bar)
                signal_rsi = rsi[global_index]
                baseline_volume = volume_ema[global_index - 1] if global_index else None
                if not direction or signal_rsi is None or baseline_volume is None:
                    continue
                if signal_bar.volume <= baseline_volume:
                    continue
                if direction > 0 and signal_rsi >= 40:
                    continue
                if direction < 0 and signal_rsi <= 60:
                    continue

                entry = entry_bar.open
                stop = (
                    min(previous.low, signal_bar.low)
                    if direction > 0
                    else max(previous.high, signal_bar.high)
                )
                risk = direction * (entry - stop)
                if risk <= 0:
                    continue
                target = entry + direction * RISK_REWARD * risk
                risk_budget = NOTIONAL * RISK_FRACTION_PER_SLEEVE
                quantity = min(int(NOTIONAL / entry), int(risk_budget / risk))
                if quantity <= 0:
                    continue
                exit_minute, exit_price, reason = _exit(
                    session_days[day.day], bars, index + 1, direction, stop, target
                )
                pnl = direction * (exit_price - entry) * quantity
                entry_side = Side.BUY if direction > 0 else Side.SELL
                exit_side = Side.SELL if direction > 0 else Side.BUY
                costs = sc.intraday_fee(entry, quantity, entry_side, day.day) + sc.intraday_fee(
                    exit_price, quantity, exit_side, day.day
                )
                costs += (entry + exit_price) * quantity * SLIPPAGE_BPS / 10_000.0
                gross[day.day] += pnl / CAPITAL
                net[day.day] += (pnl - costs) / CAPITAL
                trades.append(
                    {
                        "symbol": symbol,
                        "day": day.day.isoformat(),
                        "side": "long" if direction > 0 else "short",
                        "signal_minute": signal_bar.start,
                        "entry_minute": entry_bar.start,
                        "exit_minute": exit_minute,
                        "entry": round(entry, 4),
                        "stop": round(stop, 4),
                        "target": round(target, 4),
                        "exit": round(exit_price, 4),
                        "exit_reason": reason,
                        "quantity": quantity,
                        "gross_pnl": round(pnl, 2),
                        "costs": round(costs, 2),
                    }
                )
                break

    dates = sorted(seen)
    net_pnls = [row["gross_pnl"] - row["costs"] for row in trades]
    winners = [value for value in net_pnls if value > 0]
    losers = [value for value in net_pnls if value < 0]
    return {
        "id": "nse_github_engulfing_volume_rsi",
        "params": {
            "bar_minutes": 5,
            "pattern": "strict two-candle body engulfing with opposite candle colors",
            "volume": "signal-bar volume above prior-bar EMA(14)",
            "rsi": "RSI(14) < 40 long, > 60 short",
            "entry": "next contiguous 5-minute open",
            "stop": "outer low/high of the engulfed pair",
            "target_r": RISK_REWARD,
            "risk_per_trade": "1% of each ₹200,000 stock sleeve, capped at sleeve notional",
            "max_trades_per_stock_session": 1,
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
        "source": "Kite NSE one-minute OHLCV; files crossing the research window's end are excluded",
        "research": "docs/RESEARCH/109-github-engulfing-volume-rsi-nse.md",
        "universe": list(SYMBOLS),
        "window": [EVAL_START.isoformat(), DATA_END.isoformat()],
        "evaluation_sessions_common": len(common),
        "spent_trials": 0,
        "runs": [_run(data)],
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="github-engulfing-screen")
    parser.add_argument("--root", type=Path)
    args = parser.parse_args()
    result = run_all(root=args.root)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=1), encoding="utf-8")
    run = result["runs"][0]
    print(
        f"GitHub engulfing + volume + RSI: {run['net']['total_return']:+.2%} net, "
        f"Sharpe {run['net']['sharpe']}, {run['trades']} trades; "
        f"costs ₹{run['estimated_costs_rupees']:,.0f}"
    )
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
