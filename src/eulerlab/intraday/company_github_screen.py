"""Cost-aware NSE minute screens for research note 088.

Eight source-inspired candidates use the fixed four-stock universe and the
strict research-window cutoff. Volume-profile candidates use a typical-price
OHLCV proxy; they are not faithful volume-at-price replications.
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
from eulerlab.intraday import research_screen as rs
from eulerlab.intraday import screen_common as sc
from eulerlab.paths import data_path

OUT = data_path("derived/company_github_stock_strategies.json")
SYMBOLS = ("HDFCBANK", "ICICIBANK", "TCS", "INFY")
CAPITAL = 1_000_000.0
NOTIONAL = CAPITAL / len(SYMBOLS)
SLIPPAGE_BPS = 2.0
TRAIN_START = date(2022, 1, 1)
TRAIN_END = date(2023, 12, 31)
EVAL_START = date(2024, 1, 1)
DATA_END = rs.DATA_END
EXIT_MINUTE = 355  # 15:10


def _profiles(days: Sequence[ip.Day]) -> dict[date, tuple[float, float, float]]:
    """Prior-session POC/VA levels, assigning each minute's volume to HLC3."""
    out: dict[date, tuple[float, float, float]] = {}
    previous: tuple[float, float, float] | None = None
    for day in sorted(days, key=lambda row: row.day):
        if previous is not None:
            out[day.day] = previous
        bins: dict[float, float] = defaultdict(float)
        for minute in range(ip.FIRST_TRADABLE, day.last + 1):
            high, low, close = day.high[minute], day.low[minute], day.close[minute]
            volume = day.volume[minute]
            if high is None or low is None or volume <= 0:
                continue
            typical = (high + low + close) / 3.0
            price = round(typical / 0.05) * 0.05
            bins[price] += volume
        if bins:
            ordered = sorted(bins.items())
            poc = max(ordered, key=lambda item: item[1])[0]
            total = sum(volume for _, volume in ordered)
            target = 0.70 * total
            center = next(i for i, (price, _) in enumerate(ordered) if price == poc)
            lo = hi = center
            volume = ordered[center][1]
            while volume < target and (lo > 0 or hi < len(ordered) - 1):
                next_lo = ordered[lo - 1][1] if lo > 0 else -1.0
                next_hi = ordered[hi + 1][1] if hi < len(ordered) - 1 else -1.0
                if next_hi > next_lo:
                    hi += 1
                    volume += ordered[hi][1]
                else:
                    lo -= 1
                    volume += ordered[lo][1]
            previous = (poc, ordered[lo][0], ordered[hi][0])
    return out


def _execute(
    day: ip.Day, direction: int, entry_minute: int, exit_minute: int
) -> tuple[float, float, dict[str, Any]] | None:
    entry, exit_ = day.fill_at(entry_minute), day.fill_at(exit_minute)
    if entry is None or exit_ is None or exit_[0] <= entry[0] or entry[1] <= 0:
        return None
    quantity = max(1, int(NOTIONAL / entry[1]))
    gross = direction * (exit_[1] - entry[1]) * quantity
    buy, sell = (entry, exit_) if direction > 0 else (exit_, entry)
    costs = sc.intraday_fee(buy[1], quantity, Side.BUY, day.day) + sc.intraday_fee(
        sell[1], quantity, Side.SELL, day.day
    )
    costs += (entry[1] + exit_[1]) * quantity * SLIPPAGE_BPS / 10_000.0
    trade = {
        "symbol": "",
        "day": day.day.isoformat(),
        "side": "long" if direction > 0 else "short",
        "entry_minute": entry[0],
        "exit_minute": exit_[0],
        "entry": round(entry[1], 4),
        "exit": round(exit_[1], 4),
        "gross_pnl": round(gross, 2),
        "costs": round(costs, 2),
    }
    return gross, costs, trade


def _run(
    strategy_id: str,
    data: Mapping[str, Sequence[ip.Day]],
    signal_fn: Any,
    *,
    params: dict[str, Any],
    train_fn: Any | None = None,
) -> dict[str, Any]:
    training = train_fn(data) if train_fn else {}
    daily_net: dict[date, float] = defaultdict(float)
    daily_gross: dict[date, float] = defaultdict(float)
    trades: list[dict[str, Any]] = []
    profile = {symbol: _profiles(days) for symbol, days in data.items()}
    days_seen: set[date] = set()
    for symbol, days in data.items():
        for day in days:
            if not (EVAL_START <= day.day <= DATA_END):
                continue
            days_seen.add(day.day)
            signals = signal_fn(symbol, day, profile[symbol].get(day.day), training)
            # A fixed rule is allowed at most one entry in each symbol/session,
            # except the time-of-day rule, which allows one per fixed segment.
            for signal in signals:
                direction, entry_at, exit_at = signal["direction"], signal["entry"], signal["exit"]
                fill = _execute(day, direction, entry_at, exit_at)
                if fill is None:
                    continue
                gross, costs, trade = fill
                trade["symbol"] = symbol
                trade.update(
                    {
                        key: value
                        for key, value in signal.items()
                        if key not in {"direction", "entry", "exit"}
                    }
                )
                daily_gross[day.day] += gross / CAPITAL
                daily_net[day.day] += (gross - costs) / CAPITAL
                trades.append(trade)
    sessions = sorted(days_seen)
    gross_values = [daily_gross[day] for day in sessions]
    net_values = [daily_net[day] for day in sessions]
    return {
        "id": strategy_id,
        "params": params | ({"training_selection": training} if training else {}),
        "window": [EVAL_START.isoformat(), DATA_END.isoformat()],
        "capital_rupees": CAPITAL,
        "gross": sc.daily_stats(gross_values),
        "net": sc.daily_stats(net_values),
        "trades": len(trades),
        "fills": 2 * len(trades),
        "estimated_costs_rupees": round(sum(float(row["costs"]) for row in trades), 2),
        "daily": [[day.isoformat(), round(daily_net[day], 8)] for day in sessions],
        "trade_log": trades,
    }


def _squeeze(_symbol: str, day: ip.Day, _profile: Any, _training: Any) -> list[dict[str, Any]]:
    closes = day.close
    widths: list[float] = []
    for minute in range(ip.FIRST_TRADABLE + 19, EXIT_MINUTE - 16):
        values = closes[minute - 19 : minute + 1]
        mean = statistics.fmean(values)
        deviation = statistics.stdev(values)
        width = 4.0 * deviation / mean if mean else 0.0
        prior_widths = widths[-60:]
        widths.append(width)
        if len(prior_widths) < 60 or width > statistics.quantiles(prior_widths, n=5)[0]:
            continue
        recent = closes[minute - 19 : minute]
        close = closes[minute]
        direction = 1 if close > max(recent) else (-1 if close < min(recent) else 0)
        if direction:
            return [
                {
                    "direction": direction,
                    "entry": minute + 1,
                    "exit": min(minute + 16, EXIT_MINUTE),
                    "signal": "20-bar squeeze then 20-bar range break",
                }
            ]
    return []


def _initial_balance(
    _symbol: str, day: ip.Day, _profile: Any, _training: Any
) -> list[dict[str, Any]]:
    ib = day.span(ip.FIRST_TRADABLE, 60)
    if ib is None:
        return []
    high, low = ib
    for minute in range(60, EXIT_MINUTE - 2):
        current_high, current_low, close = day.high[minute], day.low[minute], day.close[minute]
        if current_high is None or current_low is None:
            continue
        direction = (
            -1
            if current_high > high and close < high
            else (1 if current_low < low and close > low else 0)
        )
        if direction:
            return [
                {
                    "direction": direction,
                    "entry": minute + 1,
                    "exit": min(minute + 31, EXIT_MINUTE),
                    "signal": "initial-balance break rejected; 30-minute hold",
                }
            ]
    return []


def _adaptive_train(data: Mapping[str, Sequence[ip.Day]]) -> dict[str, str]:
    segments = {"open": (30, 75), "midday": (135, 255), "late": (285, 345)}
    totals = {name: {"momentum": 0.0, "reversion": 0.0, "n": 0} for name in segments}
    for days in data.values():
        for day in days:
            if not (TRAIN_START <= day.day <= TRAIN_END):
                continue
            for name, (start, end) in segments.items():
                for minute in range(start + 5, end - 6, 5):
                    prior = day.close[minute] / day.close[minute - 5] - 1.0
                    future = day.close[minute + 5] / day.close[minute] - 1.0
                    totals[name]["momentum"] += math.copysign(future, prior) if prior else 0.0
                    totals[name]["reversion"] -= math.copysign(future, prior) if prior else 0.0
                    totals[name]["n"] += 1
    return {
        name: max(("momentum", "reversion"), key=lambda mode: totals[name][mode])
        for name in segments
    }


def _time_adaptive(
    _symbol: str, day: ip.Day, _profile: Any, training: Mapping[str, str]
) -> list[dict[str, Any]]:
    signals = []
    segments = {"open": (30, 75), "midday": (135, 255), "late": (285, 345)}
    for name, (start, end) in segments.items():
        for minute in range(start + 5, end - 6, 5):
            prior = day.close[minute] / day.close[minute - 5] - 1.0
            if abs(prior) < 0.001:
                continue
            direction = 1 if prior > 0 else -1
            if training.get(name) == "reversion":
                direction *= -1
            signals.append(
                {
                    "direction": direction,
                    "entry": minute + 1,
                    "exit": minute + 6,
                    "signal": f"{name}:{training.get(name, 'momentum')}",
                }
            )
            break
    return signals


def _volume_exhaustion(
    _symbol: str, day: ip.Day, _profile: Any, _training: Any
) -> list[dict[str, Any]]:
    for minute in range(ip.FIRST_TRADABLE + 20, EXIT_MINUTE - 11):
        low = day.low[minute]
        prior_lows = [value for value in day.low[minute - 20 : minute] if value is not None]
        if low is None or not prior_lows or low >= min(prior_lows):
            continue
        prior_volume = [v for v in day.volume[minute - 20 : minute] if v > 0]
        if len(prior_volume) < 10 or day.volume[minute] >= statistics.median(prior_volume):
            continue
        return [
            {
                "direction": 1,
                "entry": minute + 1,
                "exit": minute + 11,
                "signal": "new 20-minute low on below-median volume",
            }
        ]
    return []


def _profile_rules(rule: str) -> Any:
    def signal(
        _symbol: str, day: ip.Day, profile: tuple[float, float, float] | None, _training: Any
    ) -> list[dict[str, Any]]:
        if profile is None:
            return []
        poc, val, vah = profile
        if rule == "va_breakout":
            for minute in range(30, EXIT_MINUTE - 11):
                if day.close[minute] > vah and day.close[minute - 1] > vah:
                    return [
                        {
                            "direction": 1,
                            "entry": minute + 1,
                            "exit": minute + 11,
                            "signal": "two closes above prior value area",
                        }
                    ]
                if day.close[minute] < val and day.close[minute - 1] < val:
                    return [
                        {
                            "direction": -1,
                            "entry": minute + 1,
                            "exit": minute + 11,
                            "signal": "two closes below prior value area",
                        }
                    ]
        elif rule == "edge_to_edge":
            for minute in range(30, EXIT_MINUTE - 31):
                if day.close[minute - 1] < val <= day.close[minute] and day.close[minute + 1] > val:
                    return [
                        {
                            "direction": 1,
                            "entry": minute + 2,
                            "exit": minute + 32,
                            "signal": "accepted back above VAL; target VAH, 30-minute cap",
                        }
                    ]
                if day.close[minute - 1] > vah >= day.close[minute] and day.close[minute + 1] < vah:
                    return [
                        {
                            "direction": -1,
                            "entry": minute + 2,
                            "exit": minute + 32,
                            "signal": "accepted back below VAH; target VAL, 30-minute cap",
                        }
                    ]
        elif rule == "eighty_rule":
            open_price = day.open_[ip.FIRST_TRADABLE]
            if open_price is None:
                return []
            outside = 1 if open_price > vah else (-1 if open_price < val else 0)
            if outside:
                for minute in range(ip.FIRST_TRADABLE + 1, 45):
                    reentered = day.close[minute] < vah if outside > 0 else day.close[minute] > val
                    if reentered:
                        return [
                            {
                                "direction": -outside,
                                "entry": minute + 1,
                                "exit": min(minute + 31, EXIT_MINUTE),
                                "signal": "open outside value area then re-entry; 30-minute cap",
                            }
                        ]
        elif rule == "poc_rejection":
            for minute in range(30, EXIT_MINUTE - 16):
                high, low, close = day.high[minute], day.low[minute], day.close[minute]
                if high is None or low is None:
                    continue
                if low <= poc and close > poc and day.close[minute - 1] < poc:
                    return [
                        {
                            "direction": 1,
                            "entry": minute + 1,
                            "exit": minute + 16,
                            "signal": "POC reclaim/rejection; 15-minute hold",
                        }
                    ]
                if high >= poc and close < poc and day.close[minute - 1] > poc:
                    return [
                        {
                            "direction": -1,
                            "entry": minute + 1,
                            "exit": minute + 16,
                            "signal": "POC rejection; 15-minute hold",
                        }
                    ]
        return []

    return signal


def run_all(*, root: Path | None = None) -> dict[str, Any]:
    data = {symbol: rs.load_days(symbol, root=root, cutoff=DATA_END) for symbol in SYMBOLS}
    common_eval = set.intersection(
        *[{d.day for d in days if EVAL_START <= d.day <= DATA_END} for days in data.values()]
    )
    runs = [
        _run(
            "nse_bollinger_squeeze_expansion",
            data,
            _squeeze,
            params={
                "band_period": 20,
                "squeeze_window": 60,
                "squeeze_quantile": 0.20,
                "breakout_lookback": 20,
                "hold_minutes": 15,
            },
        ),
        _run(
            "nse_initial_balance_failure",
            data,
            _initial_balance,
            params={
                "initial_balance_minutes": 60,
                "confirm": "minute high/low breaks and close returns inside",
                "hold_minutes": 30,
            },
        ),
        _run(
            "nse_time_adaptive_momentum_reversion",
            data,
            _time_adaptive,
            params={
                "segments": {"open": [30, 75], "midday": [135, 255], "late": [285, 345]},
                "selector": "training-only average signed next-5m return after 5m impulse",
                "hold_minutes": 5,
            },
            train_fn=_adaptive_train,
        ),
        _run(
            "nse_value_area_acceptance_breakout",
            data,
            _profile_rules("va_breakout"),
            params={
                "prior_session_value_area": "70% HLC3 volume profile proxy",
                "acceptance_bars": 2,
                "hold_minutes": 10,
            },
        ),
        _run(
            "nse_value_area_edge_to_edge",
            data,
            _profile_rules("edge_to_edge"),
            params={
                "prior_session_value_area": "70% HLC3 volume profile proxy",
                "reentry_confirmation_bars": 2,
                "hold_minutes": 30,
            },
        ),
        _run(
            "nse_volume_exhaustion_no_supply",
            data,
            _volume_exhaustion,
            params={
                "new_low_lookback": 20,
                "volume_filter": "below prior 20-minute median",
                "hold_minutes": 10,
            },
        ),
        _run(
            "nse_value_area_80_rule",
            data,
            _profile_rules("eighty_rule"),
            params={
                "prior_session_value_area": "70% HLC3 volume profile proxy",
                "reentry_window_minutes": 30,
                "hold_minutes": 30,
            },
        ),
        _run(
            "nse_poc_rejection_rotation",
            data,
            _profile_rules("poc_rejection"),
            params={"prior_session_poc": "HLC3 volume profile proxy", "hold_minutes": 15},
        ),
    ]
    return {
        "source": "Kite NSE one-minute OHLCV archive; 60-day files crossing cutoff excluded",
        "universe": list(SYMBOLS),
        "window": [EVAL_START.isoformat(), DATA_END.isoformat()],
        "training_window": [TRAIN_START.isoformat(), TRAIN_END.isoformat()],
        "training_sessions_common": len(
            set.intersection(
                *[
                    {d.day for d in days if TRAIN_START <= d.day <= TRAIN_END}
                    for days in data.values()
                ]
            )
        ),
        "evaluation_sessions_common": len(common_eval),
        "assumptions": [
            "Fixed four-stock universe; results do not generalize to the whole NSE and retain survivorship bias.",
            "Equal ₹2.5 lakh notional per stock, with 2 bps assumed slippage per side plus date-aware NSE charges.",
            "Signals use completed bars and enter at the next traded minute open; no signal uses the 09:15 print.",
            "Each strategy is limited to one trade per stock/session except the time-adaptive rule, which allows one per predefined segment.",
            "Every open position is closed by 15:10. No period after the research window's end is read.",
            "Volume profile assigns each minute's full volume to HLC3; #4, #5, #7 and #8 are proxy screens, not faithful market-profile tests.",
        ],
        "runs": runs,
        "blocked": [
            {
                "id": "nse_inventory_skewed_market_making",
                "reason": "Needs timestamped depth updates, order queue position, signed trades, latency and realistic partial-fill simulation; minute OHLCV cannot estimate passive fills.",
            },
            {
                "id": "nse_cross_venue_same_stock_dislocation",
                "reason": "Needs synchronized NSE and BSE quotes/trades plus venue-specific depth and executable fills; current archive has only NSE candles.",
            },
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="company-github-intraday-screen")
    parser.add_argument("--root", type=Path, default=None, help="test fixture data root")
    args = parser.parse_args(argv)
    payload = run_all(root=args.root)
    if args.root is None:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        from eulerlab.validation import ledger

        for run in payload["runs"]:
            ledger.append(
                kind="backtest",
                subject=str(run["id"]),
                params={**run["params"], "window": run["window"], "universe": payload["universe"]},
                outcome={
                    "net_sharpe": run["net"]["sharpe"],
                    "net_return": run["net"]["total_return"],
                    "trades": run["trades"],
                    "estimated_costs_rupees": run["estimated_costs_rupees"],
                },
            )
    print(
        f"common sessions: train={payload['training_sessions_common']} evaluation={payload['evaluation_sessions_common']}"
    )
    for run in payload["runs"]:
        print(
            f"{run['id']}: net={run['net']['total_return']:+.2%} Sharpe={run['net']['sharpe']} trades={run['trades']} costs=₹{run['estimated_costs_rupees']:,.0f}"
        )
    for blocked in payload["blocked"]:
        print(f"{blocked['id']}: DATA BLOCKED — {blocked['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
