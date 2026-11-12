"""GitHub-derived surge/pullback continuation screen (research 090).

This adapts the public Ross Cameron-style rule from US small-cap equities to
five NSE stocks. It uses the source code's defaults where README prose and code
disagree. It is a fixed screen, not an optimization or profitability claim.
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any

from eulerlab.costs.schedule import Segment, Side
from eulerlab.intraday import india_papers as ip
from eulerlab.intraday import research_screen as rs
from eulerlab.intraday import screen_common as sc
from eulerlab.paths import data_path

OUT = data_path("derived/github_momentum_pullback_stock_strategies.json")
SYMBOLS = ("RELIANCE", "HDFCBANK", "ICICIBANK", "TCS", "INFY")
CAPITAL = 1_000_000.0
NOTIONAL = CAPITAL / len(SYMBOLS)
SLIPPAGE_BPS = 2.0
EVAL_START = date(2024, 1, 1)
DATA_END = date(2024, 11, 30)
EXIT_MINUTE = 355


def _positive_macd(values: Sequence[float]) -> list[bool]:
    fast, slow = sc.ema(values, 12), sc.ema(values, 26)
    line = [a - b for a, b in zip(fast, slow, strict=True)]
    signal = sc.ema(line, 9)
    return [a > b and a - b > 0 for a, b in zip(line, signal, strict=True)]


def _vwap(day: ip.Day, minute: int) -> float | None:
    value_volume = total_volume = 0.0
    for index in range(ip.FIRST_TRADABLE, minute + 1):
        high, low = day.high[index], day.low[index]
        volume = day.volume[index]
        if high is None or low is None or volume <= 0:
            continue
        typical = (high + low + day.close[index]) / 3.0
        value_volume += typical * volume
        total_volume += volume
    return value_volume / total_volume if total_volume > 0 else None


def _signal(day: ip.Day, macd_positive: Sequence[bool]) -> dict[str, Any] | None:
    """First completed-bar long setup from the source's code defaults."""
    for minute in range(10, min(EXIT_MINUTE - 1, day.last - 1)):
        start = max(ip.FIRST_TRADABLE, minute - 29)
        recent = list(range(start, minute + 1))
        if len(recent) < 10:
            continue
        # The source checks 5..20-bar surges in a recent 30-bar window,
        # excluding its last two bars. Keep the first qualifying window.
        surge = False
        for lookback in range(5, min(21, len(recent) - 2)):
            segment = recent[-lookback - 2 : -2]
            if len(segment) < 3:
                continue
            segment_lows: list[float] = []
            segment_highs: list[float] = []
            for index in segment:
                low, high = day.low[index], day.high[index]
                if low is not None:
                    segment_lows.append(low)
                if high is not None:
                    segment_highs.append(high)
            if not segment_lows or not segment_highs:
                continue
            if (max(segment_highs) - min(segment_lows)) / min(segment_lows) >= 0.02:
                surge = True
                break
        if not surge:
            continue
        recent_segment = recent[-17:-2]
        if len(recent_segment) < 3:
            continue
        recent_highs = [day.high[index] for index in recent_segment if day.high[index] is not None]
        if not recent_highs:
            continue
        recent_high = max(value for value in recent_highs if value is not None)
        high_index = next(index for index in recent_segment if day.high[index] == recent_high)
        pullback_bars = [index for index in recent_segment if index > high_index] + [recent[-2]]
        if not pullback_bars:
            continue
        pullback_lows = [day.low[index] for index in pullback_bars if day.low[index] is not None]
        if not pullback_lows:
            continue
        pullback_low = min(value for value in pullback_lows if value is not None)
        pullback_pct = (recent_high - pullback_low) / recent_high
        if not 0.003 <= pullback_pct <= 0.05:
            continue
        current, previous = minute, minute - 1
        current_high, current_open = day.high[current], day.open_[current]
        previous_high = day.high[previous]
        if current_high is None or current_open is None or previous_high is None:
            continue
        if current_high <= previous_high or day.close[current] <= current_open:
            continue
        if (recent_high - day.close[current]) / recent_high > 0.10:
            continue
        if not macd_positive[current]:
            continue
        vwap = _vwap(day, current)
        if vwap is None or day.close[current] <= vwap:
            continue
        vol_window = recent[-10:]
        if len(vol_window) < 5:
            continue
        historical = [day.volume[index] for index in vol_window[:-2]]
        if not historical or statistics.fmean(historical) <= 0:
            continue
        relative_volume = statistics.fmean(
            day.volume[index] for index in vol_window[-2:]
        ) / statistics.fmean(historical)
        if relative_volume < 2.0:
            continue
        signal_bar_volume = day.volume[current]
        upper_wick = float(current_high) - max(float(current_open), day.close[current])
        body = abs(day.close[current] - float(current_open))
        if signal_bar_volume > statistics.fmean(historical) * 2.5 and upper_wick > body * 1.5:
            continue
        if (
            sum(day.close[index] < (day.open_[index] or day.close[index]) for index in recent[-5:])
            >= 4
        ):
            continue
        entry = day.fill_at(current + 1)
        if entry is None or pullback_low >= entry[1]:
            continue
        return {
            "signal_minute": current,
            "entry_minute": entry[0],
            "entry": entry[1],
            "stop": pullback_low * 0.99,
            "target": entry[1] * 1.20,
            "pullback_low": pullback_low,
            "surge_pct": round(
                (recent_high / min(value for value in pullback_lows if value is not None) - 1.0)
                * 100,
                3,
            ),
            "relative_volume": round(relative_volume, 3),
        }
    return None


def _exit(day: ip.Day, signal: Mapping[str, Any]) -> tuple[int, float, str]:
    entry_minute = int(signal["entry_minute"])
    stop, target = float(signal["stop"]), float(signal["target"])
    for minute in range(entry_minute, min(EXIT_MINUTE, day.last) + 1):
        open_, high, low = day.open_[minute], day.high[minute], day.low[minute]
        if open_ is None or high is None or low is None:
            continue
        if open_ <= stop:
            return minute, open_, "stop_gap"
        if open_ >= target:
            return minute, target, "target_gap"
        hit_stop, hit_target = low <= stop, high >= target
        if hit_stop:
            return minute, stop, "stop_first" if hit_target else "stop"
        if hit_target:
            return minute, target, "target"
        if minute > entry_minute and low < (day.low[minute - 1] or low):
            return minute, day.close[minute], "candle_under_candle"
    minute = min(EXIT_MINUTE, day.last)
    return minute, day.close[minute], "time_exit"


def _run(data: Mapping[str, Sequence[ip.Day]]) -> dict[str, Any]:
    gross_daily: dict[date, float] = defaultdict(float)
    net_daily: dict[date, float] = defaultdict(float)
    days_seen: set[date] = set()
    trades: list[dict[str, Any]] = []
    for symbol, sessions in data.items():
        for day in sessions:
            if not EVAL_START <= day.day <= DATA_END:
                continue
            days_seen.add(day.day)
            macd_positive = _positive_macd(day.close[: day.last + 1])
            signal = _signal(day, macd_positive)
            if signal is None:
                continue
            exit_minute, exit_price, reason = _exit(day, signal)
            entry_price = float(signal["entry"])
            quantity = max(1, int(NOTIONAL / entry_price))
            gross = (exit_price - entry_price) * quantity
            from eulerlab.costs.router import fill_cost

            costs = fill_cost(
                venue="equity",
                price=entry_price,
                quantity=quantity,
                side=Side.BUY,
                day=day.day,
                segment=Segment.EQUITY_INTRADAY,
            ) + fill_cost(
                venue="equity",
                price=exit_price,
                quantity=quantity,
                side=Side.SELL,
                day=day.day,
                segment=Segment.EQUITY_INTRADAY,
            )
            costs += (entry_price + exit_price) * quantity * SLIPPAGE_BPS / 10_000.0
            gross_daily[day.day] += gross / CAPITAL
            net_daily[day.day] += (gross - costs) / CAPITAL
            trades.append(
                {
                    "symbol": symbol,
                    "day": day.day.isoformat(),
                    "signal_minute": int(signal["signal_minute"]),
                    "entry_minute": int(signal["entry_minute"]),
                    "exit_minute": exit_minute,
                    "entry": round(entry_price, 4),
                    "stop": round(float(signal["stop"]), 4),
                    "target": round(float(signal["target"]), 4),
                    "exit": round(exit_price, 4),
                    "exit_reason": reason,
                    "relative_volume": signal["relative_volume"],
                    "gross_pnl": round(gross, 2),
                    "costs": round(costs, 2),
                }
            )
    trade_days = sorted(days_seen)
    return {
        "id": "nse_surge_pullback_new_high",
        "params": {
            "surge_min_pct": 2.0,
            "surge_window_bars": [5, 20],
            "pullback_pct": [0.3, 5.0],
            "macd": [12, 26, 9],
            "relative_volume_min": 2.0,
            "relative_volume_bars": "last 2 / preceding up to 8",
            "vwap_filter": "close above session VWAP",
            "stop": "pullback low minus 1%",
            "target_pct": 20.0,
            "max_trades_per_stock_session": 1,
            "slippage_bps_per_side": SLIPPAGE_BPS,
        },
        "window": [EVAL_START.isoformat(), DATA_END.isoformat()],
        "capital_rupees": CAPITAL,
        "gross": sc.daily_stats([gross_daily[day] for day in trade_days]),
        "net": sc.daily_stats([net_daily[day] for day in trade_days]),
        "trades": len(trades),
        "fills": 2 * len(trades),
        "estimated_costs_rupees": round(sum(float(row["costs"]) for row in trades), 2),
        "daily": [[day.isoformat(), round(net_daily[day], 8)] for day in trade_days],
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
            "Fixed five-stock liquid universe, not the US small-cap source universe.",
            "The source's premarket/catalyst context is absent; no premarket gap or catalyst filter is claimed.",
            "Source README and code conflict on relative-volume threshold (1.5x versus 2.0x) and pullback lower bound (0.3% versus a docstring's 3%); code defaults are frozen.",
            "Equal ₹200,000 notional per stock; date-aware NSE intraday charges plus 2 bp assumed slippage per side.",
            "Completed-bar signals enter at next traded minute open. Same-bar stop and target resolves to stop; gaps through stops fill at the open.",
            "Each stock trades at most once a session; positions flatten by 15:10. No data after 2024-11-30 is opened.",
        ],
        "runs": [_run(data)],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="github-momentum-pullback-screen")
    parser.add_argument("--root", type=Path, default=None, help="test fixture data root")
    args = parser.parse_args(argv)
    payload = run_all(root=args.root)
    if args.root is None:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    run = payload["runs"][0]
    print(
        f"{run['id']}: gross={run['gross']['total_return']:+.2%}; net={run['net']['total_return']:+.2%}; "
        f"Sharpe={run['net']['sharpe']}; trades={run['trades']}; costs=₹{run['estimated_costs_rupees']:,.0f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
