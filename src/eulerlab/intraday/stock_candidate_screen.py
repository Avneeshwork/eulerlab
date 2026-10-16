"""Price-only screen of three new NSE intraday research candidates.

The sample stops at 2024-11-30. 2025 onward is outside this reader's cutoff.
Rules are frozen source-inspired adaptations, not exact paper replications.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any

from eulerlab.costs.schedule import Segment, Side
from eulerlab.intraday import india_papers as ip
from eulerlab.intraday import research_screen as rs

OUT = Path("data/derived/stock_intraday_candidates.json")
TRAIN_START = date(2022, 1, 1)
TRAIN_END = date(2023, 12, 31)
EVAL_START = date(2024, 1, 1)
DATA_END = date(2024, 11, 30)
CAPITAL = 1_000_000.0
SLIPPAGE_BPS = 2.0
PAIR_SLOTS = (("HDFCBANK", "ICICIBANK"), ("TCS", "INFY"))
SYMBOLS = tuple(dict.fromkeys(symbol for pair in PAIR_SLOTS for symbol in pair))
STOCK_EXIT = 355  # 15:10, before the 15:12 intraday square-off.
BAR_MINUTES = 5
MOVE_TRIGGER = 0.002
LAG_FRACTION = 0.25
PAIR_LOOKBACK = 60
PAIR_ENTRY_Z = 2.0
PAIR_EXIT_Z = 0.5
PAIR_MAX_HOLD = 30


def load_universe(*, root: Path | None = None) -> dict[str, list[ip.Day]]:
    """Load only complete archive objects ending by DATA_END."""
    return {symbol: rs.load_days(symbol, root=root, cutoff=DATA_END) for symbol in SYMBOLS}


def _trade_cost(price: float, quantity: int, side: Side, day: date) -> float:
    from eulerlab.costs.router import fill_cost

    return fill_cost(
        venue="equity",
        price=price,
        quantity=quantity,
        side=side,
        day=day,
        segment=Segment.EQUITY_INTRADAY,
    )


def _quantity(notional: float, price: float) -> int:
    return max(1, int(notional / price))


def _daily_stats(rows: Sequence[tuple[date, float]]) -> dict[str, Any]:
    values = [value for _, value in rows]
    equity = peak = 1.0
    drawdown = 0.0
    for value in values:
        equity *= 1.0 + value
        peak = max(peak, equity)
        drawdown = min(drawdown, equity / peak - 1.0)
    deviation = statistics.stdev(values) if len(values) > 1 else 0.0
    return {
        "days": len(values),
        "total_return": round(equity - 1.0, 6),
        "sharpe": round(statistics.fmean(values) / deviation * math.sqrt(252), 3)
        if deviation
        else None,
        "max_drawdown": round(drawdown, 6),
    }


def _window_return(day: ip.Day, end: int, width: int) -> float | None:
    start = end - width
    if start < ip.FIRST_TRADABLE or day.open_[end] is None or day.open_[start] is None:
        return None
    start_price = day.close[start - 1]
    end_price = day.close[end]
    if start_price <= 0 or end_price <= 0:
        return None
    return end_price / start_price - 1.0


def _daily_turnover(day: ip.Day) -> float:
    values = [day.close[m] * day.volume[m] for m in range(ip.FIRST_TRADABLE, day.last + 1)]
    return sum(values)


def _training_days(data: Mapping[str, Sequence[ip.Day]]) -> dict[str, dict[date, ip.Day]]:
    return {
        symbol: {day.day: day for day in days if TRAIN_START <= day.day <= TRAIN_END}
        for symbol, days in data.items()
    }


def _evaluation_days(data: Mapping[str, Sequence[ip.Day]]) -> dict[str, dict[date, ip.Day]]:
    return {
        symbol: {day.day: day for day in days if EVAL_START <= day.day <= DATA_END}
        for symbol, days in data.items()
    }


def _leader_by_turnover(
    data: Mapping[str, Sequence[ip.Day]],
) -> dict[tuple[str, str], tuple[str, str]]:
    train = _training_days(data)
    leaders: dict[tuple[str, str], tuple[str, str]] = {}
    for a, b in PAIR_SLOTS:
        values_a = [_daily_turnover(day) for day in train[a].values()]
        values_b = [_daily_turnover(day) for day in train[b].values()]
        med_a = statistics.median(values_a) if values_a else 0.0
        med_b = statistics.median(values_b) if values_b else 0.0
        leaders[(a, b)] = (a, b) if med_a >= med_b else (b, a)
    return leaders


def _execute_single(
    *, day: ip.Day, symbol: str, direction: int, entry_at: int, exit_at: int, notional: float
) -> tuple[float, float, tuple[int, float, int, float]] | None:
    entry = day.fill_at(entry_at)
    exit_ = day.fill_at(exit_at)
    if entry is None or exit_ is None or exit_[0] <= entry[0]:
        return None
    shares = _quantity(notional, entry[1])
    gross = direction * (exit_[1] - entry[1]) * shares
    buy, sell = (entry, exit_) if direction > 0 else (exit_, entry)
    fees = _trade_cost(buy[1], shares, Side.BUY, day.day) + _trade_cost(
        sell[1], shares, Side.SELL, day.day
    )
    slip = (entry[1] + exit_[1]) * shares * SLIPPAGE_BPS / 10_000.0
    return gross, fees + slip, (entry[0], entry[1], exit_[0], exit_[1])


def _execute_pair(
    *,
    day_a: ip.Day,
    day_b: ip.Day,
    direction_a: int,
    entry_at: int,
    exit_at: int,
    notional_per_leg: float,
) -> tuple[float, float, tuple[int, float, int, float]] | None:
    entry_a, entry_b = day_a.fill_at(entry_at), day_b.fill_at(entry_at)
    exit_a, exit_b = day_a.fill_at(exit_at), day_b.fill_at(exit_at)
    if None in (entry_a, entry_b, exit_a, exit_b):
        return None
    assert entry_a is not None and entry_b is not None and exit_a is not None and exit_b is not None
    if exit_a[0] <= entry_a[0] or exit_b[0] <= entry_b[0]:
        return None
    shares_a, shares_b = (
        _quantity(notional_per_leg, entry_a[1]),
        _quantity(notional_per_leg, entry_b[1]),
    )
    direction_b = -direction_a
    gross = direction_a * (exit_a[1] - entry_a[1]) * shares_a
    gross += direction_b * (exit_b[1] - entry_b[1]) * shares_b
    entry_side_a = Side.BUY if direction_a > 0 else Side.SELL
    exit_side_a = Side.SELL if direction_a > 0 else Side.BUY
    entry_side_b = Side.BUY if direction_b > 0 else Side.SELL
    exit_side_b = Side.SELL if direction_b > 0 else Side.BUY
    fees = sum(
        (
            _trade_cost(entry_a[1], shares_a, entry_side_a, day_a.day),
            _trade_cost(exit_a[1], shares_a, exit_side_a, day_a.day),
            _trade_cost(entry_b[1], shares_b, entry_side_b, day_b.day),
            _trade_cost(exit_b[1], shares_b, exit_side_b, day_b.day),
        )
    )
    slip = (entry_a[1] + exit_a[1]) * shares_a * SLIPPAGE_BPS / 10_000.0
    slip += (entry_b[1] + exit_b[1]) * shares_b * SLIPPAGE_BPS / 10_000.0
    return gross, fees + slip, (entry_a[0], entry_a[1], exit_a[0], exit_a[1])


def _return_arrays(days: Sequence[ip.Day]) -> dict[date, list[float | None]]:
    out: dict[date, list[float | None]] = {}
    for day in days:
        values: list[float | None] = [None] * ip.MINUTES
        for minute in range(1, day.last + 1):
            before, current = day.close[minute - 1], day.close[minute]
            if day.open_[minute] is not None and before > 0 and current > 0:
                values[minute] = current / before - 1.0
        out[day.day] = values
    return out


def _max_lead_lag_pair(data: Mapping[str, Sequence[ip.Day]]) -> dict[str, Any]:
    """Choose one ordered pair and a 5-minute lag from training data only."""
    train = _training_days(data)
    candidates: list[dict[str, Any]] = []
    for a, b in PAIR_SLOTS:
        returns_a = _return_arrays(list(train[a].values()))
        returns_b = _return_arrays(list(train[b].values()))
        for leader, follower, left, right in (
            (a, b, returns_a, returns_b),
            (b, a, returns_b, returns_a),
        ):
            for lag in (5, 10, 15):
                x: list[float] = []
                y: list[float] = []
                for session in sorted(set(left) & set(right)):
                    lvals, rvals = left[session], right[session]
                    for minute in range(ip.FIRST_TRADABLE + lag, STOCK_EXIT - lag):
                        leader_ret, follower_ret = lvals[minute - lag], rvals[minute]
                        if leader_ret is not None and follower_ret is not None:
                            x.append(leader_ret)
                            y.append(follower_ret)
                corr = _correlation(x, y)
                candidates.append(
                    {
                        "leader": leader,
                        "follower": follower,
                        "lag_minutes": lag,
                        "correlation": corr,
                        "observations": len(x),
                    }
                )
    eligible = [
        row for row in candidates if row["correlation"] is not None and row["observations"] >= 500
    ]
    if not eligible:
        return {
            "leader": "",
            "follower": "",
            "lag_minutes": 0,
            "correlation": None,
            "observations": 0,
        }
    # This is the predeclared training-only selection rule, not an OOS sweep.
    return max(eligible, key=lambda row: float(row["correlation"]))


def _correlation(x: Sequence[float], y: Sequence[float]) -> float | None:
    if len(x) < 2 or len(x) != len(y):
        return None
    mx, my = statistics.fmean(x), statistics.fmean(y)
    dx, dy = [v - mx for v in x], [v - my for v in y]
    denom = math.sqrt(sum(v * v for v in dx) * sum(v * v for v in dy))
    return sum(a * b for a, b in zip(dx, dy, strict=True)) / denom if denom else None


def _screen_single_leg(
    data: Mapping[str, Sequence[ip.Day]], sessions: Sequence[date]
) -> dict[str, Any]:
    """Leader impulse followed by an under-reacting same-sector stock."""
    eval_days = _evaluation_days(data)
    leaders = _leader_by_turnover(data)
    symbol_days = {symbol: {d.day: d for d in days} for symbol, days in data.items()}
    daily_net: dict[date, float] = {}
    daily_gross: dict[date, float] = {}
    trades: list[dict[str, Any]] = []
    pair_notional = CAPITAL / len(PAIR_SLOTS)
    for leader, follower in leaders.values():
        for session, follower_day in eval_days[follower].items():
            leader_day = symbol_days[leader].get(session)
            if leader_day is None:
                continue
            for end in range(BAR_MINUTES, STOCK_EXIT - BAR_MINUTES, BAR_MINUTES):
                leader_return = _window_return(leader_day, end, BAR_MINUTES)
                follower_return = _window_return(follower_day, end, BAR_MINUTES)
                if leader_return is None or follower_return is None:
                    continue
                if abs(leader_return) < MOVE_TRIGGER:
                    continue
                if (
                    math.copysign(1.0, leader_return) * follower_return
                    >= abs(leader_return) * LAG_FRACTION
                ):
                    continue
                entry_at = end + 1
                exit_at = entry_at + BAR_MINUTES
                if exit_at >= STOCK_EXIT:
                    continue
                fill = _execute_single(
                    day=follower_day,
                    symbol=follower,
                    direction=1 if leader_return > 0 else -1,
                    entry_at=entry_at,
                    exit_at=exit_at,
                    notional=pair_notional,
                )
                if fill is None:
                    continue
                gross, costs, prices = fill
                daily_gross[session] = daily_gross.get(session, 0.0) + gross / CAPITAL
                daily_net[session] = daily_net.get(session, 0.0) + (gross - costs) / CAPITAL
                trades.append(
                    {
                        "day": session.isoformat(),
                        "leader": leader,
                        "follower": follower,
                        "entry_minute": prices[0],
                        "exit_minute": prices[2],
                        "gross_pnl": round(gross, 2),
                        "costs": round(costs, 2),
                    }
                )
                break  # at most one entry per pair per session
    return _result(
        "nse_liquid_leader_laggard",
        daily_net,
        daily_gross,
        trades,
        {"leader_by_turnover": {f"{a}/{b}": list(v) for (a, b), v in leaders.items()}},
        sessions=sessions,
    )


def _spread_z(day_a: ip.Day, day_b: ip.Day, minute: int) -> float | None:
    if minute < PAIR_LOOKBACK or day_a.open_[minute] is None or day_b.open_[minute] is None:
        return None
    values: list[float] = []
    for index in range(minute - PAIR_LOOKBACK + 1, minute + 1):
        if day_a.close[index] <= 0 or day_b.close[index] <= 0:
            return None
        values.append(math.log(day_a.close[index]) - math.log(day_b.close[index]))
    deviation = statistics.stdev(values)
    if deviation == 0:
        return None
    return (values[-1] - statistics.fmean(values)) / deviation


def _screen_pair_convergence(
    data: Mapping[str, Sequence[ip.Day]], sessions: Sequence[date]
) -> dict[str, Any]:
    """Trade fixed-sector pair spreads when a 60-minute z-score is extreme."""
    eval_days = _evaluation_days(data)
    by_symbol = {symbol: {d.day: d for d in days} for symbol, days in data.items()}
    daily_net: dict[date, float] = {}
    daily_gross: dict[date, float] = {}
    trades: list[dict[str, Any]] = []
    notional_per_leg = CAPITAL / (2 * len(PAIR_SLOTS))
    for a, b in PAIR_SLOTS:
        for session, day_a in eval_days[a].items():
            day_b = by_symbol[b].get(session)
            if day_b is None:
                continue
            minute = PAIR_LOOKBACK
            while minute < STOCK_EXIT - 1:
                z = _spread_z(day_a, day_b, minute)
                if z is None or abs(z) < PAIR_ENTRY_Z:
                    minute += 1
                    continue
                direction_a = -1 if z > 0 else 1
                entry_at = minute + 1
                deadline = min(entry_at + PAIR_MAX_HOLD, STOCK_EXIT)
                exit_at: int | None = None
                for exit_signal in range(entry_at, deadline):
                    current_z = _spread_z(day_a, day_b, exit_signal)
                    if current_z is not None and (current_z * direction_a >= -PAIR_EXIT_Z):
                        exit_at = exit_signal + 1
                        break
                if exit_at is None or exit_at > STOCK_EXIT:
                    exit_at = STOCK_EXIT
                fill = _execute_pair(
                    day_a=day_a,
                    day_b=day_b,
                    direction_a=direction_a,
                    entry_at=entry_at,
                    exit_at=exit_at,
                    notional_per_leg=notional_per_leg,
                )
                if fill is not None:
                    gross, costs, prices = fill
                    daily_gross[session] = daily_gross.get(session, 0.0) + gross / CAPITAL
                    daily_net[session] = daily_net.get(session, 0.0) + (gross - costs) / CAPITAL
                    trades.append(
                        {
                            "day": session.isoformat(),
                            "pair": f"{a}/{b}",
                            "entry_minute": prices[0],
                            "exit_minute": prices[2],
                            "entry_z": round(z, 4),
                            "gross_pnl": round(gross, 2),
                            "costs": round(costs, 2),
                        }
                    )
                minute = max(exit_at, minute + 1)
    return _result(
        "nse_intraday_pair_convergence",
        daily_net,
        daily_gross,
        trades,
        {
            "pairs": [list(pair) for pair in PAIR_SLOTS],
            "lookback_minutes": PAIR_LOOKBACK,
            "entry_z": PAIR_ENTRY_Z,
            "exit_z": PAIR_EXIT_Z,
            "max_hold_minutes": PAIR_MAX_HOLD,
        },
        sessions=sessions,
        legs=2,
    )


def _screen_leadlag_pair(
    data: Mapping[str, Sequence[ip.Day]], sessions: Sequence[date]
) -> dict[str, Any]:
    """Train-select one lead-lag pair and trade follower catch-up in 2024."""
    selected = _max_lead_lag_pair(data)
    leader, follower = str(selected["leader"]), str(selected["follower"])
    if not leader or not follower:
        return _result(
            "nse_leadlag_pair_convergence",
            {},
            {},
            [],
            {"selected_pair": selected},
            sessions=sessions,
        )
    eval_days = _evaluation_days(data)
    by_symbol = {symbol: {d.day: d for d in days} for symbol, days in data.items()}
    daily_net: dict[date, float] = {}
    daily_gross: dict[date, float] = {}
    trades: list[dict[str, Any]] = []
    notional = CAPITAL
    lag = int(selected["lag_minutes"])
    for session, follower_day in eval_days[follower].items():
        leader_day = by_symbol[leader].get(session)
        if leader_day is None:
            continue
        for end in range(BAR_MINUTES, STOCK_EXIT - max(BAR_MINUTES, lag), BAR_MINUTES):
            leader_return = _window_return(leader_day, end, BAR_MINUTES)
            follower_return = _window_return(follower_day, end, BAR_MINUTES)
            if leader_return is None or follower_return is None:
                continue
            if abs(leader_return) < MOVE_TRIGGER:
                continue
            if (
                math.copysign(1.0, leader_return) * follower_return
                >= abs(leader_return) * LAG_FRACTION
            ):
                continue
            entry_at = end + 1
            exit_at = entry_at + max(lag, BAR_MINUTES)
            if exit_at >= STOCK_EXIT:
                continue
            fill = _execute_single(
                day=follower_day,
                symbol=follower,
                direction=1 if leader_return > 0 else -1,
                entry_at=entry_at,
                exit_at=exit_at,
                notional=notional,
            )
            if fill is None:
                continue
            gross, costs, prices = fill
            daily_gross[session] = daily_gross.get(session, 0.0) + gross / CAPITAL
            daily_net[session] = daily_net.get(session, 0.0) + (gross - costs) / CAPITAL
            trades.append(
                {
                    "day": session.isoformat(),
                    "leader": leader,
                    "follower": follower,
                    "lag_minutes": lag,
                    "entry_minute": prices[0],
                    "exit_minute": prices[2],
                    "gross_pnl": round(gross, 2),
                    "costs": round(costs, 2),
                }
            )
            break  # one trade per session; fixed one-pair portfolio
    return _result(
        "nse_leadlag_pair_convergence",
        daily_net,
        daily_gross,
        trades,
        {
            "selected_pair": selected,
            "selection_period": [TRAIN_START.isoformat(), TRAIN_END.isoformat()],
            "trigger_5m_return": MOVE_TRIGGER,
            "lag_fraction": LAG_FRACTION,
        },
        sessions=sessions,
    )


def _result(
    strategy_id: str,
    net: Mapping[date, float],
    gross: Mapping[date, float],
    trades: Sequence[dict[str, Any]],
    params: dict[str, Any],
    *,
    sessions: Sequence[date],
    legs: int = 1,
) -> dict[str, Any]:
    days = sorted(set(sessions) | set(net) | set(gross))
    net_rows = [(day, float(net.get(day, 0.0))) for day in days]
    gross_rows = [(day, float(gross.get(day, 0.0))) for day in days]
    stats_net, stats_gross = _daily_stats(net_rows), _daily_stats(gross_rows)
    total_cost = sum(float(row["costs"]) for row in trades)
    return {
        "id": strategy_id,
        "params": params,
        "window": [EVAL_START.isoformat(), DATA_END.isoformat()],
        "capital_rupees": CAPITAL,
        "gross": stats_gross,
        "net": stats_net,
        "trades": len(trades),
        "fills": 2 * legs * len(trades),
        "estimated_costs_rupees": round(total_cost, 2),
        "daily": [[day.isoformat(), round(net.get(day, 0.0), 8)] for day in days],
        "trade_log": list(trades),
    }


def run_all(*, root: Path | None = None) -> dict[str, Any]:
    data = load_universe(root=root)
    training_sessions = sorted(
        set.intersection(
            *[
                {d.day for d in data[symbol] if TRAIN_START <= d.day <= TRAIN_END}
                for symbol in SYMBOLS
            ]
        )
    )
    evaluation_sessions = sorted(
        set.intersection(
            *[
                {d.day for d in data[symbol] if EVAL_START <= d.day <= DATA_END}
                for symbol in SYMBOLS
            ]
        )
    )
    return {
        "source": "Kite NSE one-minute archive; files ending after cutoff excluded",
        "universe": list(SYMBOLS),
        "window": [EVAL_START.isoformat(), DATA_END.isoformat()],
        "training_window": [TRAIN_START.isoformat(), TRAIN_END.isoformat()],
        "evaluation_window": [EVAL_START.isoformat(), DATA_END.isoformat()],
        "data_end": DATA_END.isoformat(),
        "training_sessions_common": len(training_sessions),
        "evaluation_sessions_common": len(evaluation_sessions),
        "assumptions": [
            "Fixed five-stock sample; survivorship bias remains.",
            "Two basis points slippage per side, in addition to date-aware NSE intraday charges.",
            "All signals use completed bars and enter at the next traded minute open.",
            "The first 09:15 print is excluded; all positions close by 15:10.",
            "Screening adaptations, not exact source replications; no holdout after 2024-11-30 was read.",
        ],
        "runs": [
            _screen_single_leg(data, evaluation_sessions),
            _screen_pair_convergence(data, evaluation_sessions),
            _screen_leadlag_pair(data, evaluation_sessions),
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="stock-intraday-candidates")
    parser.add_argument("--root", type=Path, default=None, help="test fixture root")
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
