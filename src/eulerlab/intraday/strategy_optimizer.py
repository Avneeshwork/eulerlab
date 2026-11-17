"""Tune loss filters on 2024, then report on later unseen minutes.

The three source strategies were first screened through November 2024. This
module treats 2024 as filter-development data and 2025-10-14 as a fresh test;
no parameter choice is made from the latter period. The screens only reduce
signals: MA confirmation/bands, tree probability plus a daily trade cap, and a
stricter training-quantile trigger for the extreme-reversal rule.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from typing import Any

from eulerlab.costs.schedule import Segment, Side
from eulerlab.intraday import india_papers as ip
from eulerlab.paths import data_path
from eulerlab.strategies.studies import research as rs

DEV_START = date(2024, 1, 1)
DEV_END = date(2024, 11, 30)
TEST_START = date(2025, 1, 1)
TEST_END = date(2026, 10, 14)
TEST_CUTOFF = TEST_END
CAPITAL = rs.CAPITAL


def _stats(daily: dict[date, float]) -> dict[str, Any]:
    return rs._stats(sorted(daily.items()))


def _summarise(
    daily_gross: dict[date, float],
    daily_net: dict[date, float],
    trades: int,
    base_trades: int,
    costs: float,
    calendar: list[date],
) -> dict[str, Any]:
    gross_rows = {day: daily_gross.get(day, 0.0) for day in calendar}
    net_rows = {day: daily_net.get(day, 0.0) for day in calendar}
    return {
        "gross": _stats(gross_rows),
        "net": _stats(net_rows),
        "trades": trades,
        "baseline_trades": base_trades,
        "trade_reduction_pct": round(100 * (1 - trades / base_trades), 2) if base_trades else 0,
        "estimated_costs": round(costs, 2),
    }


def _fill_cost(price: float, notional: float, side: Side, day: date) -> float:
    return rs._fill_cost(price, notional, side, day)


def _gold(
    days: list[ip.Day],
    *,
    method: str,
    slow: int,
    confirm: int,
    band_bps: int,
    start: date,
    end: date,
    base_trades: int | None = None,
) -> dict[str, Any]:
    daily_gross: dict[date, float] = defaultdict(float)
    daily_net: dict[date, float] = defaultdict(float)
    fills = costs = 0.0
    history: list[float] = []
    ema_value: float | None = None
    ema_alpha = 2 / (slow + 1)
    for day in days:
        opens, closes = rs._bars(day)
        position = 0
        streak_signal, streak = 0, 0
        for i, close in enumerate(closes[:-1]):
            history.append(close)
            if len(history) < slow:
                continue
            if method == "ema":
                ema_value = (
                    sum(history[-slow:]) / slow
                    if ema_value is None
                    else ema_alpha * close + (1 - ema_alpha) * ema_value
                )
                average = ema_value
            else:
                average = rs._average(history[-slow:], method, slow)
            distance = (close / average - 1) * 10_000 if average else 0
            raw = 1 if distance > band_bps else -1 if distance < -band_bps else 0
            if raw and raw == streak_signal:
                streak += 1
            elif raw:
                streak_signal, streak = raw, 1
            else:
                streak_signal, streak = 0, 0
            signal = streak_signal if streak >= confirm else position
            open_price, close_price = opens[i + 1], closes[i + 1]
            if not math.isfinite(open_price) or open_price <= 0 or close_price <= 0:
                continue
            if signal != position:
                for side in (
                    [Side.SELL] if position > 0 else [Side.BUY] if position < 0 else []
                ) + ([Side.BUY] if signal > 0 else [Side.SELL] if signal < 0 else []):
                    fee = _fill_cost(open_price, CAPITAL, side, day.day)
                    slip = CAPITAL * rs.GOLD_SLIPPAGE_BPS / 10_000
                    daily_net[day.day] -= (fee + slip) / CAPITAL
                    if start <= day.day <= end:
                        costs += fee + slip
                        fills += 1
            gross = signal * (close_price / open_price - 1)
            daily_gross[day.day] += gross
            daily_net[day.day] += gross
            position = signal
        if position and closes[-1] > 0:
            side = Side.SELL if position > 0 else Side.BUY
            fee = _fill_cost(closes[-1], CAPITAL, side, day.day)
            slip = CAPITAL * rs.GOLD_SLIPPAGE_BPS / 10_000
            daily_net[day.day] -= (fee + slip) / CAPITAL
            if start <= day.day <= end:
                costs += fee + slip
                fills += 1
        history.append(closes[-1])
    if base_trades is None:
        base_trades = int(fills)
    gross_daily = {d: r for d, r in daily_gross.items() if start <= d <= end}
    net = {d: r for d, r in daily_net.items() if start <= d <= end}
    calendar = [day.day for day in days if start <= day.day <= end]
    return _summarise(gross_daily, net, int(fills), base_trades, costs, calendar)


def _stock_costs(entry: float, exit_: float, shares: int, when: date, direction: int) -> float:
    entry_side, exit_side = (Side.BUY, Side.SELL) if direction > 0 else (Side.SELL, Side.BUY)
    from eulerlab.costs.router import fill_cost

    return (
        float(
            sum(
                fill_cost(
                    venue="equity",
                    price=price,
                    quantity=shares,
                    side=side,
                    day=when,
                    segment=Segment.EQUITY_INTRADAY,
                )
                for price, side in ((entry, entry_side), (exit_, exit_side))
            )
        )
        + (entry + exit_) * shares * rs.STOCK_SLIPPAGE_BPS / 10_000
    )


def _reversal(
    days_by_symbol: dict[str, list[ip.Day]], *, quantile: float, start: date, end: date
) -> dict[str, Any]:
    gross: dict[date, float] = defaultdict(float)
    net: dict[date, float] = defaultdict(float)
    events = costs = 0.0
    per_name = CAPITAL / len(days_by_symbol)
    base_events = 0
    for symbol_days in days_by_symbol.values():
        moves = sorted(
            after / before - 1
            for day in symbol_days
            if rs.TRAIN_START <= day.day <= rs.TRAIN_END
            for minute in range(2, day.last + 1)
            if day.open_[minute - 1] is not None
            and day.open_[minute] is not None
            and (before := day.close[minute - 1]) > 0
            and (after := day.close[minute]) > 0
        )
        if not moves:
            continue
        threshold = moves[max(0, int(0.001 * len(moves)) - 1)]
        trigger = moves[max(0, int(quantile * len(moves)) - 1)]
        # Quantiles below the source's 0.1% cutoff retain only more extreme
        # shocks. The threshold is learned from 2022-2023 and stays frozen.
        for day in symbol_days:
            if not start <= day.day <= end:
                continue
            for minute in range(2, day.last):
                if day.open_[minute - 1] is None or day.open_[minute] is None:
                    continue
                before, after = day.close[minute - 1], day.close[minute]
                move = after / before - 1 if before > 0 else 0
                entry, exit_ = day.open_[minute + 1], day.close[minute + 1]
                if entry is None or entry <= 0 or exit_ <= 0:
                    continue
                if start <= day.day <= end and move <= threshold:
                    base_events += 1
                if move > trigger:
                    continue
                shares = max(1, int(per_name / entry))
                move_dollars = shares * (exit_ - entry)
                fee = _stock_costs(float(entry), exit_, shares, day.day, 1)
                gross[day.day] += move_dollars / CAPITAL
                net[day.day] += (move_dollars - fee) / CAPITAL
                costs += fee
                events += 1
    calendar = sorted(
        {day.day for rows in days_by_symbol.values() for day in rows if start <= day.day <= end}
    )
    return _summarise(dict(gross), dict(net), int(events), base_events, costs, calendar)


def _tree_events(days_by_symbol: dict[str, list[ip.Day]]) -> list[dict[str, Any]]:
    from sklearn.tree import DecisionTreeClassifier

    events: list[dict[str, Any]] = []
    for symbol, days in days_by_symbol.items():
        train_x: list[list[float]] = []
        train_y: list[int] = []
        rows: list[tuple[date, list[float], float, float]] = []
        for day in days:
            for minute in range(210, day.last):
                features = rs._tree_features(day, minute)
                if features is None:
                    continue
                target = int(day.close[minute + 1] > day.close[minute])
                if rs.TRAIN_START <= day.day <= rs.TRAIN_END:
                    train_x.append(features)
                    train_y.append(target)
                elif DEV_START <= day.day <= TEST_END:
                    entry, exit_ = day.open_[minute + 1], day.close[minute + 1]
                    if entry is not None and entry > 0 and exit_ > 0:
                        rows.append((day.day, features, float(entry), exit_))
        if not train_x or not rows:
            continue
        model = DecisionTreeClassifier(criterion="gini", max_depth=4, random_state=0)
        model.fit(train_x, train_y)
        probs = model.predict_proba([r[1] for r in rows])
        for (when, _features, entry, exit_), prob in zip(rows, probs, strict=True):
            cls = model.classes_
            pred_idx = int(prob.argmax())
            direction = 1 if int(cls[pred_idx]) == 1 else -1
            shares = max(1, int((CAPITAL / len(days_by_symbol)) / entry))
            events.append(
                {
                    "symbol": symbol,
                    "day": when,
                    "direction": direction,
                    "confidence": float(prob[pred_idx]),
                    "entry": entry,
                    "exit": exit_,
                    "shares": shares,
                }
            )
    return events


def _tree_score(
    events: list[dict[str, Any]],
    *,
    threshold: float,
    daily_cap: int,
    start: date,
    end: date,
    base_count: int,
) -> dict[str, Any]:
    by_day_symbol: dict[tuple[date, str], list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        if start <= event["day"] <= end and event["confidence"] >= threshold:
            by_day_symbol[event["day"], event["symbol"]].append(event)
    chosen = []
    for rows in by_day_symbol.values():
        chosen.extend(sorted(rows, key=lambda r: r["confidence"], reverse=True)[:daily_cap])
    gross: dict[date, float] = defaultdict(float)
    net: dict[date, float] = defaultdict(float)
    costs = 0.0
    for r in chosen:
        pnl = r["direction"] * r["shares"] * (r["exit"] - r["entry"])
        fee = _stock_costs(r["entry"], r["exit"], r["shares"], r["day"], r["direction"])
        gross[r["day"]] += pnl / CAPITAL
        net[r["day"]] += (pnl - fee) / CAPITAL
        costs += fee
    calendar = sorted({r["day"] for r in events if start <= r["day"] <= end})
    return _summarise(dict(gross), dict(net), len(chosen), base_count, costs, calendar)


def _store_library_results(result: dict[str, Any]) -> dict[str, str]:
    """Expose the frozen OOS filters as new, labeled runs on the three new cards."""
    from eulerlab import results as result_store
    from eulerlab import workspace as workspace_mod

    workspace = workspace_mod.resolve(None)
    selected = {
        "gold_intraday_ma_rules": (
            result["gold_ma"]["selected"],
            "equity",
            1,
            {
                key: result["gold_ma"]["selected"][key]
                for key in ("method", "slow", "confirm", "band_bps")
            },
        ),
        "extreme_minute_reversal": (
            result["extreme_reversal"]["selected"],
            "equity",
            len(rs.STOCKS),
            {"trigger_quantile": result["extreme_reversal"]["selected"]["quantile"]},
        ),
        "nse_minute_decision_tree": (
            result["decision_tree"]["selected"],
            "equity",
            len(rs.STOCKS),
            {key: result["decision_tree"]["selected"][key] for key in ("confidence", "daily_cap")},
        ),
    }
    written: dict[str, str] = {}
    for strategy_id, (selection, asset_class, symbols, params) in selected.items():
        stats = selection["test"]["net"]
        test = selection["test"]
        universe = f"new filtered setup {params}"
        run = result_store.Run(
            strategy_id=strategy_id,
            sharpe=float(stats["sharpe"] or 0.0),
            total_return=float(stats["total_return"]),
            max_drawdown=float(stats["max_drawdown"]),
            fills=int(
                test["trades"] if strategy_id == "gold_intraday_ma_rules" else 2 * test["trades"]
            ),
            days=int(stats["days"]),
            tier="optimization-oos",
            window_days=int(stats["days"]),
            data_version=f"kite-minute-{TEST_START.isoformat()}-{TEST_END.isoformat()}",
            asset_class=asset_class,
            cost_mode="realistic",
            universe=universe,
            symbols=symbols,
            params={**params, "instruments": ["GOLDBEES"] if symbols == 1 else list(rs.STOCKS)},
        )
        if any(
            old.configuration == run.configuration
            for old in result_store.distinct(workspace, strategy_id)
        ):
            written[strategy_id] = "already recorded"
        else:
            path = result_store.record(workspace, run)
            written[strategy_id] = str(path)
    return written


def optimize(*, output: Path | None = None) -> dict[str, Any]:
    output = output if output is not None else data_path("derived/new_strategy_optimization.json")
    symbols = (rs.GOLD, *rs.STOCKS)
    with ThreadPoolExecutor(max_workers=len(symbols)) as pool:
        loaded = dict(
            pool.map(lambda symbol: (symbol, rs.load_days(symbol, cutoff=TEST_CUTOFF)), symbols)
        )
    gold = loaded[rs.GOLD]
    stocks = {symbol: loaded[symbol] for symbol in rs.STOCKS}
    gold_grid: list[dict[str, Any]] = []
    gold_baselines = {
        (method, slow): (
            _gold(
                gold, method=method, slow=slow, confirm=1, band_bps=0, start=DEV_START, end=DEV_END
            )["trades"],
            _gold(
                gold,
                method=method,
                slow=slow,
                confirm=1,
                band_bps=0,
                start=TEST_START,
                end=TEST_END,
            )["trades"],
        )
        for method in rs.GOLD_METHODS
        for slow in rs.GOLD_HORIZONS
    }
    for method in rs.GOLD_METHODS:
        for slow in rs.GOLD_HORIZONS:
            for confirm in (1, 2, 3, 5):
                for band in (0, 5, 10, 20, 40):
                    gold_grid.append(
                        {
                            "method": method,
                            "slow": slow,
                            "confirm": confirm,
                            "band_bps": band,
                            "development": _gold(
                                gold,
                                method=method,
                                slow=slow,
                                confirm=confirm,
                                band_bps=band,
                                start=DEV_START,
                                end=DEV_END,
                                base_trades=gold_baselines[method, slow][0],
                            ),
                        }
                    )
    best_gold = max(gold_grid, key=lambda r: r["development"]["net"]["total_return"])
    best_gold["test"] = _gold(
        gold,
        method=best_gold["method"],
        slow=best_gold["slow"],
        confirm=best_gold["confirm"],
        band_bps=best_gold["band_bps"],
        start=TEST_START,
        end=TEST_END,
        base_trades=gold_baselines[best_gold["method"], best_gold["slow"]][1],
    )

    reversal_grid: list[dict[str, Any]] = []
    for q in (0.00025, 0.0005, 0.001):
        reversal_grid.append(
            {
                "quantile": q,
                "development": _reversal(stocks, quantile=q, start=DEV_START, end=DEV_END),
            }
        )
    best_reversal = max(reversal_grid, key=lambda r: r["development"]["net"]["total_return"])
    best_reversal["test"] = _reversal(
        stocks, quantile=best_reversal["quantile"], start=TEST_START, end=TEST_END
    )

    tree_events = _tree_events(stocks)
    base = sum(1 for r in tree_events if DEV_START <= r["day"] <= DEV_END)
    tree_grid: list[dict[str, Any]] = []
    for confidence in (0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80):
        for cap in (1, 2, 3, 5):
            tree_grid.append(
                {
                    "confidence": confidence,
                    "daily_cap": cap,
                    "development": _tree_score(
                        tree_events,
                        threshold=confidence,
                        daily_cap=cap,
                        start=DEV_START,
                        end=DEV_END,
                        base_count=base,
                    ),
                }
            )
    best_tree = max(tree_grid, key=lambda r: r["development"]["net"]["total_return"])
    test_base = sum(1 for r in tree_events if TEST_START <= r["day"] <= TEST_END)
    best_tree["test"] = _tree_score(
        tree_events,
        threshold=best_tree["confidence"],
        daily_cap=best_tree["daily_cap"],
        start=TEST_START,
        end=TEST_END,
        base_count=test_base,
    )

    result = {
        "data_cutoff": TEST_END.isoformat(),
        "development_window": [DEV_START.isoformat(), DEV_END.isoformat()],
        "test_window": [TEST_START.isoformat(), TEST_END.isoformat()],
        "selection": "best development net return among fixed grids; test window not used for selection",
        "gold_ma": {"selected": best_gold, "grid": gold_grid},
        "extreme_reversal": {"selected": best_reversal, "grid": reversal_grid},
        "decision_tree": {"selected": best_tree, "grid": tree_grid},
        "caution": "Exploratory optimization. The development winner is selected; only the later test period is independent.",
    }
    result["library_runs"] = _store_library_results(result)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    return result


if __name__ == "__main__":
    report = optimize()
    for name in ("gold_ma", "extreme_reversal", "decision_tree"):
        choice = report[name]["selected"]
        print(name, {k: v for k, v in choice.items() if k != "grid"})
