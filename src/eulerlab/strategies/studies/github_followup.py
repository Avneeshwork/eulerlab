"""Second GitHub-derived NSE minute screen (research 089).

The only sufficiently specified non-duplicate signal found in this pass is a
trend pullback to EMA-20 with MACD histogram confirmation, setup-swing stop and
1R target. The source is a MES futures repository; this is an independent NSE
adaptation. Results are a fixed screen, not a profitability claim.
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
from eulerlab.strategies.studies import research as rs

OUT = data_path("derived/github_followup_stock_strategies.json")
SYMBOLS = ("HDFCBANK", "ICICIBANK", "TCS", "INFY")
CAPITAL = 1_000_000.0
NOTIONAL = CAPITAL / len(SYMBOLS)
SLIPPAGE_BPS = 2.0
EVAL_START = date(2024, 1, 1)
DATA_END = rs.DATA_END
EXIT_MINUTE = 355  # 15:10


def _histogram(values: Sequence[float]) -> list[float]:
    macd = [fast - slow for fast, slow in zip(sc.ema(values, 12), sc.ema(values, 26), strict=True)]
    signal = sc.ema(macd, 9)
    return [line - average for line, average in zip(macd, signal, strict=True)]


def _signal(day: ip.Day) -> dict[str, Any] | None:
    """Return first confirmed EMA-20 pullback; entry is next traded minute."""
    closes = day.close[: day.last + 1]
    ema20 = sc.ema(closes, 20)
    hist = _histogram(closes)
    for minute in range(26, min(EXIT_MINUTE - 7, day.last - 6)):
        prior_close = closes[minute - 1]
        close = closes[minute]
        low = day.low[minute]
        high = day.high[minute]
        if low is None or high is None:
            continue
        long_setup = (
            prior_close > ema20[minute - 1]
            and low <= ema20[minute]
            and close > ema20[minute]
            and hist[minute] > 0
        )
        short_setup = (
            prior_close < ema20[minute - 1]
            and high >= ema20[minute]
            and close < ema20[minute]
            and hist[minute] < 0
        )
        if not (long_setup or short_setup):
            continue
        direction = 1 if long_setup else -1
        recent = range(max(ip.FIRST_TRADABLE, minute - 4), minute + 1)
        swing_lows: list[float] = []
        swing_highs: list[float] = []
        for index in recent:
            swing_low = day.low[index]
            swing_high = day.high[index]
            if swing_low is not None:
                swing_lows.append(swing_low)
            if swing_high is not None:
                swing_highs.append(swing_high)
        entry = day.fill_at(minute + 1)
        if entry is None or not swing_lows or not swing_highs:
            continue
        stop = min(swing_lows) if direction > 0 else max(swing_highs)
        risk = direction * (entry[1] - stop)
        if risk <= 0 or risk / entry[1] > 0.01:
            continue
        return {
            "direction": direction,
            "signal_minute": minute,
            "entry_minute": entry[0],
            "entry": entry[1],
            "stop": stop,
            "target": entry[1] + direction * risk,
        }
    return None


def _exit(day: ip.Day, signal: Mapping[str, Any]) -> tuple[int, float, str]:
    direction = int(signal["direction"])
    stop, target = float(signal["stop"]), float(signal["target"])
    entry_minute = int(signal["entry_minute"])
    for minute in range(entry_minute, min(EXIT_MINUTE, day.last) + 1):
        open_ = day.open_[minute]
        high, low = day.high[minute], day.low[minute]
        if open_ is None or high is None or low is None:
            continue
        if direction > 0:
            if open_ <= stop:
                return minute, float(open_), "stop_gap"
            if open_ >= target:
                return minute, target, "target_gap"
            hit_stop, hit_target = low <= stop, high >= target
        else:
            if open_ >= stop:
                return minute, float(open_), "stop_gap"
            if open_ <= target:
                return minute, target, "target_gap"
            hit_stop, hit_target = high >= stop, low <= target
        if hit_stop:
            return minute, stop, "stop_first" if hit_target else "stop"
        if hit_target:
            return minute, target, "target"
    minute = min(EXIT_MINUTE, day.last)
    return minute, day.close[minute], "time_exit"


def _run(data: Mapping[str, Sequence[ip.Day]]) -> dict[str, Any]:
    daily_gross: dict[date, float] = defaultdict(float)
    daily_net: dict[date, float] = defaultdict(float)
    days_seen: set[date] = set()
    trades: list[dict[str, Any]] = []
    for symbol, sessions in data.items():
        for day in sessions:
            if not EVAL_START <= day.day <= DATA_END:
                continue
            days_seen.add(day.day)
            signal = _signal(day)
            if signal is None:
                continue
            exit_minute, exit_price, reason = _exit(day, signal)
            entry_price = float(signal["entry"])
            direction = int(signal["direction"])
            quantity = max(1, int(NOTIONAL / entry_price))
            gross = direction * (exit_price - entry_price) * quantity
            entry_side = Side.BUY if direction > 0 else Side.SELL
            exit_side = Side.SELL if direction > 0 else Side.BUY
            costs = sc.intraday_fee(entry_price, quantity, entry_side, day.day) + sc.intraday_fee(
                exit_price, quantity, exit_side, day.day
            )
            costs += (entry_price + exit_price) * quantity * SLIPPAGE_BPS / 10_000.0
            daily_gross[day.day] += gross / CAPITAL
            daily_net[day.day] += (gross - costs) / CAPITAL
            trades.append(
                {
                    "symbol": symbol,
                    "day": day.day.isoformat(),
                    "side": "long" if direction > 0 else "short",
                    "signal_minute": int(signal["signal_minute"]),
                    "entry_minute": int(signal["entry_minute"]),
                    "exit_minute": exit_minute,
                    "entry": round(entry_price, 4),
                    "stop": round(float(signal["stop"]), 4),
                    "target": round(float(signal["target"]), 4),
                    "exit": round(exit_price, 4),
                    "exit_reason": reason,
                    "gross_pnl": round(gross, 2),
                    "costs": round(costs, 2),
                }
            )
    trade_days = sorted(days_seen)
    return {
        "id": "nse_ema_macd_swing_pullback",
        "params": {
            "ema_period": 20,
            "macd": [12, 26, 9],
            "confirmation": "histogram sign agrees with trade direction",
            "swing_stop_lookback_bars": 5,
            "target_r": 1.0,
            "max_stop_distance_pct": 1.0,
            "max_trades_per_stock_session": 1,
            "slippage_bps_per_side": SLIPPAGE_BPS,
        },
        "window": [EVAL_START.isoformat(), DATA_END.isoformat()],
        "capital_rupees": CAPITAL,
        "gross": sc.daily_stats([daily_gross[day] for day in trade_days]),
        "net": sc.daily_stats([daily_net[day] for day in trade_days]),
        "trades": len(trades),
        "fills": 2 * len(trades),
        "estimated_costs_rupees": round(sum(float(row["costs"]) for row in trades), 2),
        "daily": [[day.isoformat(), round(daily_net[day], 8)] for day in trade_days],
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
            "Four fixed stocks only; survivorship bias and narrow-universe risk remain.",
            "Equal ₹2.5 lakh notional per name; date-aware NSE intraday charges plus 2 bp assumed slippage per side.",
            "Signal is evaluated on a completed minute and entered at the next traded minute open.",
            "Stop and target are checked after entry; if both touch in a bar, stop is filled first.",
            "Gap-through stops fill at the bar open; targets fill at the target price.",
            "Each stock trades at most once a session and every position exits by 15:10.",
            "No data after the research window's end is opened.",
        ],
        "runs": [_run(data)],
        "triage": [
            {
                "repository": "spagnola-analytics/intraday-strategies",
                "candidate": "EMA-20 pullback + MACD histogram + setup swing / 1R",
                "status": "tested",
                "reason": "Minute OHLCV supports a rule-based adaptation; not an NSE edge claim.",
            },
            {
                "repository": "spagnola-analytics/intraday-strategies",
                "candidate": "overnight high/low fade",
                "status": "blocked",
                "reason": "Source uses MES overnight extremes; local NSE cash archive has no corresponding overnight traded session.",
            },
            {
                "repository": "spagnola-analytics/intraday-strategies",
                "candidate": "FVG gap fade and overnight gap ride",
                "status": "duplicate_or_incompatible",
                "reason": "Gap family is already in the library and its overnight futures session does not map cleanly to NSE cash hours.",
            },
            {
                "repository": "spagnola-analytics/intraday-strategies",
                "candidate": "ORB pullback and VIX-regime ORB",
                "status": "duplicate",
                "reason": "Opening-range and ORB variants are already represented in the Strategy Library.",
            },
            {
                "repository": "spagnola-analytics/intraday-strategies",
                "candidate": "VWAP mean reversion",
                "status": "duplicate",
                "reason": "VWAP/noise-area mean reversion is already represented and has costed NSE results.",
            },
            {
                "repository": "spagnola-analytics/intraday-strategies",
                "candidate": "market-structure break / order block",
                "status": "not_specified",
                "reason": "README references discretionary market-structure terminology but does not provide one deterministic entry/exit configuration.",
            },
            {
                "repository": "ezhilengels/zerodhaAutoIntraBot",
                "candidate": "gap-up quiet-volume VWAP pullback",
                "status": "duplicate",
                "reason": "Gap and VWAP reclaim/pullback combinations overlap existing studies and candidates.",
            },
            {
                "repository": "notvikke/NSE_Trade_Simulation",
                "candidate": "extreme RSI mean reversion",
                "status": "duplicate",
                "reason": "Extreme-minute reversal and extreme-move fade are already in the library; repository combines rule with discretionary AI confirmation.",
            },
            {
                "repository": "HeneelParmar/Algorithmic-Trading-Strategy-Backtester",
                "candidate": "MA crossover / RSI mean reversion",
                "status": "duplicate_or_wrong_frequency",
                "reason": "The published example is daily-bar index testing; those families are already represented.",
            },
            {
                "repository": "CuriousObservator/Systematic-Intraday-Mean-reversion-Strategy",
                "candidate": "open-to-close gap reversal",
                "status": "duplicate_or_wrong_frequency",
                "reason": "Signal is formed at the open and held to the close; it is daily open-close, not a minute-entry rule, and overlaps gap-reversal work.",
            },
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="github-followup-intraday-screen")
    parser.add_argument("--root", type=Path, default=None, help="test fixture data root")
    args = parser.parse_args(argv)
    payload = run_all(root=args.root)
    if args.root is None:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for run in payload["runs"]:
        print(
            f"{run['id']}: gross={run['gross']['total_return']:+.2%}; "
            f"net={run['net']['total_return']:+.2%}; Sharpe={run['net']['sharpe']}; "
            f"trades={run['trades']}; costs=₹{run['estimated_costs_rupees']:,.0f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
