"""Fixed, source-backed candidates from research 084.

Only reads Kite minute files whose named end date is on or before
``DATA_END``. The adjacent 60-day file that crosses the cutoff is excluded as
a whole, so no holdout rows are opened or inspected.
"""

from __future__ import annotations

import argparse
import io
import json
import math
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from eulerlab import constitution
from eulerlab.costs.schedule import Segment, Side
from eulerlab.intraday import india_papers as ip
from eulerlab.intraday import screen_common as sc
from eulerlab.paths import data_path

RESEARCH_START, DATA_END = constitution.research_window()
"""The one research window (ADR-184): 2016-01-01 to the constitution's
`backtest_end`. Every screen and the rule engine read it from here."""
EVAL_START = date(2024, 1, 1)
TRAIN_START = date(2022, 1, 1)
TRAIN_END = date(2023, 12, 31)
GOLD = "GOLDBEES"
STOCKS = ("RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "TCS")
GOLD_HORIZONS = (50, 100, 150, 200)
GOLD_METHODS = ("sma", "ema", "wma")
GOLD_SLIPPAGE_BPS = 1.0
STOCK_SLIPPAGE_BPS = 2.0
CAPITAL = 1_000_000.0


def _files(
    symbol: str,
    *,
    root: Path | None = None,
    cutoff: date = DATA_END,
    cache: bool = True,
    since: date | None = None,
) -> list[tuple[str, bytes]]:
    """Read only complete 60-day objects that end before the strict cutoff.

    `since` keeps out every file that starts on or before it: a paper book
    passes the holdout's end (`mandate.yaml`), so no holdout file is opened.
    """
    if root is not None:
        paths = [str(path) for path in (root / symbol).glob("*.parquet")]
        return [
            (path, Path(path).read_bytes())
            for path in sorted(paths)
            if _file_end(path) <= cutoff and (since is None or _file_start(path) > since)
        ]

    from eulerlab.ingest import landing_reader

    names = ip.archive_files(symbol)
    eligible = [
        name
        for name in names
        if _file_end(name) <= cutoff and (since is None or _file_start(name) > since)
    ]
    return [(name, landing_reader.read(name, cache=cache)) for name in eligible]


def _file_end(name: str) -> date:
    return date.fromisoformat(Path(name).stem.rsplit("_", 1)[-1])


def _file_start(name: str) -> date:
    return date.fromisoformat(Path(name).stem.split("_", 1)[0])


HISTORY_FROM = date(2018, 11, 1)
"""The first day of Angel's minute history a reader takes (operator, 2026-11-14)."""

HISTORY_ENV = "EULERLAB_MINUTE_HISTORY"
"""Set to 1 to run the minute screens from `HISTORY_FROM` (ADR-201). Research only:
the paper books (`deploy/mis_book.py`) never set it, so their replays do not change."""


def minute_history() -> bool:
    import os

    return os.environ.get(HISTORY_ENV) == "1"


def history_files(symbol: str, cutoff: date = DATA_END) -> list[str]:
    """Angel minute files of `symbol` from `HISTORY_FROM` that start before Kite's first day."""
    from eulerlab.ingest import landing_reader
    from eulerlab.intraday import store

    names = landing_reader.available("angel_minute_history", f"{symbol}/*.parquet")
    return sorted(
        n
        for n in names
        if _file_end(n) >= HISTORY_FROM
        and _file_start(n) < store.KITE_START
        and _file_end(n) <= cutoff
    )


def load_days(
    symbol: str,
    *,
    root: Path | None = None,
    cutoff: date = DATA_END,
    cache: bool = True,
    since: date | None = None,
    history: bool = False,
) -> list[ip.Day]:
    """Read through a named cutoff; never open a file that crosses it.

    `history=True` adds Angel's minute bars from `HISTORY_FROM` to the day
    before Kite's first session, rescaled to Kite's basis by the symbol's
    ADR-185 factor (`angel_rescale.load_factors`, T-4634). A symbol whose factor
    failed its checks gets no history, never an unscaled one. Kite's bars win
    on any day both hold."""
    rows: dict[str, dict[int, tuple[float, float, float, float, float]]] = {}
    if history and root is None and since is None:
        _history_rows(symbol, rows, cutoff, cache)
    for _, blob in _files(symbol, root=root, cutoff=cutoff, cache=cache, since=since):
        table = pq.read_table(
            io.BytesIO(blob), columns=["ts", "open", "high", "low", "close", "volume"]
        )
        columns = [table.column(name).to_pylist() for name in table.column_names]
        for stamp, open_, high, low, close, volume in zip(*columns, strict=True):
            if stamp is None or open_ is None or high is None or low is None or close is None:
                continue
            day = date.fromisoformat(stamp[:10])
            if day > cutoff:
                raise ValueError(f"cutoff-crossing data reached loader: {symbol} {day}")
            minute = (int(stamp[11:13]) - 9) * 60 + int(stamp[14:16]) - 15
            if 0 <= minute < ip.MINUTES:
                rows.setdefault(stamp[:10], {})[minute] = (
                    float(open_),
                    float(high),
                    float(low),
                    float(close),
                    float(volume or 0),
                )
    return ip.days_from_rows(rows)


def _history_rows(
    symbol: str,
    rows: dict[str, dict[int, tuple[float, float, float, float, float]]],
    cutoff: date,
    cache: bool,
) -> None:
    from eulerlab.ingest import angel_rescale, landing_reader
    from eulerlab.intraday import store

    factor = angel_rescale.load_factors().get(symbol)
    if factor is None:
        return
    f, fv = factor.factor, factor.volume_factor
    for name in history_files(symbol, cutoff):
        table = pq.read_table(
            io.BytesIO(landing_reader.read(name, cache=cache)),
            columns=["ts", "open", "high", "low", "close", "volume"],
        )
        columns = [table.column(n).to_pylist() for n in table.column_names]
        for stamp, open_, high, low, close, volume in zip(*columns, strict=True):
            if stamp is None or open_ is None or high is None or low is None or close is None:
                continue
            day = date.fromisoformat(stamp[:10])
            if not HISTORY_FROM <= day < store.KITE_START or day > cutoff:
                continue
            minute = (int(stamp[11:13]) - 9) * 60 + int(stamp[14:16]) - 15
            if 0 <= minute < ip.MINUTES:
                rows.setdefault(stamp[:10], {})[minute] = (
                    float(open_) * f,
                    float(high) * f,
                    float(low) * f,
                    float(close) * f,
                    float(volume or 0) * fv,
                )


def _bars(day: ip.Day) -> tuple[list[float], list[float]]:
    """(first traded open, close) per five-minute bar, without filling opens."""
    opens: list[float] = []
    closes: list[float] = []
    for start in range(0, ip.MINUTES, 5):
        traded = next(
            (day.open_[m] for m in range(start, min(start + 5, ip.MINUTES)) if day.open_[m]), None
        )
        opens.append(float(traded) if traded is not None else math.nan)
        closes.append(day.close[min(start + 4, ip.MINUTES - 1)])
    return opens, closes


def _average(values: Sequence[float], method: str, period: int | None = None) -> float:
    if method == "sma":
        return sum(values) / len(values)
    if method == "wma":
        denominator = len(values) * (len(values) + 1) / 2
        return sum((index + 1) * value for index, value in enumerate(values)) / denominator
    alpha = 2 / ((period or len(values)) + 1)
    result = values[0]
    for value in values[1:]:
        result = alpha * value + (1 - alpha) * result
    return result


def _fill_cost(price: float, notional: float, side: Side, day: date) -> float:
    shares = max(1, int(notional / price))
    from eulerlab.costs.router import fill_cost

    return fill_cost(
        venue="equity",
        price=price,
        quantity=shares,
        side=side,
        day=day,
        segment=Segment.EQUITY_INTRADAY,
        fund_unit=True,
    )


def _stats(daily: Sequence[tuple[date, float]]) -> dict[str, Any]:
    return sc.daily_stats([value for _, value in daily])


def _gold_rule(
    days: Sequence[ip.Day], *, method: str, slow: int, slippage_bps: float = GOLD_SLIPPAGE_BPS
) -> dict[str, Any]:
    daily: list[tuple[date, float]] = []
    gross_daily: list[tuple[date, float]] = []
    fills = 0
    transaction_costs = 0.0
    sessions: list[tuple[ip.Day, list[float], list[float]]] = [
        (day, *_bars(day)) for day in days if date(2021, 8, 19) <= day.day <= DATA_END
    ]
    history: list[float] = []
    ema_value: float | None = None
    ema_alpha = 2 / (slow + 1)
    for day, opens, closes in sessions:
        position = 0
        result = 0.0
        gross_result = 0.0
        for index, close in enumerate(closes[:-1]):
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
                average = _average(history[-slow:], method, slow)
            signal = 1 if close > average else -1
            open_price = opens[index + 1]
            close_price = closes[index + 1]
            if not math.isfinite(open_price) or open_price <= 0 or close_price <= 0:
                continue
            if signal != position:
                turnover = abs(signal - position)
                if position:
                    side = Side.SELL if position > 0 else Side.BUY
                    fee = _fill_cost(open_price, CAPITAL, side, day.day)
                    slip = CAPITAL * slippage_bps / 10_000
                    transaction_costs += fee + slip
                    result -= (fee + slip) / CAPITAL
                    fills += 1
                if signal:
                    side = Side.BUY if signal > 0 else Side.SELL
                    fee = _fill_cost(open_price, CAPITAL, side, day.day)
                    slip = CAPITAL * slippage_bps / 10_000
                    transaction_costs += fee + slip
                    result -= (fee + slip) / CAPITAL
                    fills += 1
                if turnover > 2:
                    raise AssertionError("position turnover exceeds a direct reversal")
            bar_return = signal * (close_price / open_price - 1)
            result += bar_return
            gross_result += bar_return
            position = signal
        if position:
            final_close = closes[-1]
            side = Side.SELL if position > 0 else Side.BUY
            fee = _fill_cost(final_close, CAPITAL, side, day.day)
            slip = CAPITAL * slippage_bps / 10_000
            transaction_costs += fee + slip
            result -= (fee + slip) / CAPITAL
            fills += 1
        daily.append((day.day, result))
        gross_daily.append((day.day, gross_result))
        history.append(closes[-1])
    prior = [(day, value) for day, value in daily if day < EVAL_START]
    eval_ = [(day, value) for day, value in daily if EVAL_START <= day <= DATA_END]
    gross_prior = [(day, value) for day, value in gross_daily if day < EVAL_START]
    gross_eval = [(day, value) for day, value in gross_daily if EVAL_START <= day <= DATA_END]
    return {
        "source": "Batten-Ciner-Lucey-2018",
        "rule": f"{method.upper()}(1) vs {method.upper()}({slow}), 5m, intraday flat",
        "instrument": "GOLDBEES (listed Gold ETF proxy; not MCX futures)",
        "slippage_bps_per_side": slippage_bps,
        "fills": fills,
        "estimated_transaction_costs": round(transaction_costs, 2),
        "gross_before_2024": _stats(gross_prior),
        "gross_evaluation_2024_through_2024_11_30": _stats(gross_eval),
        "before_2024": _stats(prior),
        "evaluation_2024_through_2024_11_30": _stats(eval_),
        "daily": [[day.isoformat(), round(value, 8)] for day, value in daily],
    }


def _extreme_reversal(
    stock_days: Mapping[str, Sequence[ip.Day]], *, threshold_quantile: float = 0.001
) -> dict[str, Any]:
    """Train per-stock 0.1% one-minute loss cutoffs, then freeze for 2024."""
    thresholds: dict[str, float] = {}
    eval_returns: dict[date, float] = {}
    eval_gross: dict[date, float] = {}
    transaction_costs = 0.0
    events = 0
    capital_per_name = CAPITAL / len(stock_days)
    for symbol, days in stock_days.items():
        train_moves: list[float] = []
        for day in days:
            if not TRAIN_START <= day.day <= TRAIN_END:
                continue
            for minute in range(2, day.last + 1):
                if day.open_[minute - 1] is None or day.open_[minute] is None:
                    continue
                before, after = day.close[minute - 1], day.close[minute]
                if before > 0 and after > 0:
                    train_moves.append(after / before - 1)
        if not train_moves:
            continue
        train_moves.sort()
        thresholds[symbol] = train_moves[max(0, int(threshold_quantile * len(train_moves)) - 1)]
        for day in days:
            if not EVAL_START <= day.day <= DATA_END:
                continue
            for minute in range(2, day.last):
                if day.open_[minute - 1] is None or day.open_[minute] is None:
                    continue
                prior_close = day.close[minute - 1]
                event_close = day.close[minute]
                move = event_close / prior_close - 1 if prior_close > 0 else 0.0
                entry = day.open_[minute + 1]
                exit_ = day.close[minute + 1]
                if move > thresholds[symbol] or entry is None or entry <= 0 or exit_ <= 0:
                    continue
                notional = capital_per_name
                shares = max(1, int(notional / entry))
                from eulerlab.costs.router import fill_cost

                costs = float(
                    sum(
                        fill_cost(
                            venue="equity",
                            price=price,
                            quantity=shares,
                            side=side,
                            day=day.day,
                            segment=Segment.EQUITY_INTRADAY,
                        )
                        for price, side in ((float(entry), Side.BUY), (exit_, Side.SELL))
                    )
                )
                costs += notional * 2 * STOCK_SLIPPAGE_BPS / 10_000
                gross = notional * (exit_ / float(entry) - 1)
                transaction_costs += costs
                net = gross - costs
                eval_gross[day.day] = eval_gross.get(day.day, 0.0) + gross / CAPITAL
                eval_returns[day.day] = eval_returns.get(day.day, 0.0) + net / CAPITAL
                events += 1
    calendar = sorted(
        {
            day.day
            for days in stock_days.values()
            for day in days
            if EVAL_START <= day.day <= DATA_END
        }
    )
    daily = [(day, eval_returns.get(day, 0.0)) for day in calendar]
    return {
        "source": "Rif-Utz-2021",
        "rule": "per-symbol one-minute return <= training 0.1% quantile; enter next traded minute open, exit its close",
        "instrument": ", ".join(stock_days),
        "training_window": [TRAIN_START.isoformat(), TRAIN_END.isoformat()],
        "evaluation_window": [EVAL_START.isoformat(), DATA_END.isoformat()],
        "thresholds": {symbol: round(value, 8) for symbol, value in thresholds.items()},
        "events": events,
        "estimated_transaction_costs": round(transaction_costs, 2),
        "slippage_bps_per_side": STOCK_SLIPPAGE_BPS,
        "gross": _stats([(day, eval_gross.get(day, 0.0)) for day in calendar]),
        "net": _stats(daily),
        "daily": [[day.isoformat(), round(value, 8)] for day, value in daily],
    }


def _tree_features(day: ip.Day, minute: int) -> list[float] | None:
    """Nine source features, computed only when all required bars traded."""
    start = minute - 210
    if start < 1 or any(day.open_[idx] is None for idx in range(start, minute + 2)):
        return None
    close = day.close
    returns = [close[idx] / close[idx - 1] - 1 for idx in range(start, minute + 1)]
    if any(not math.isfinite(value) for value in returns):
        return None

    def volatility(count: int) -> float:
        values = returns[-count:]
        mean = sum(values) / count
        return math.sqrt(max(0.0, sum(value * value for value in values) / count - mean * mean))

    gains = [max(0.0, close[idx] - close[idx - 1]) for idx in range(minute - 13, minute + 1)]
    losses = [max(0.0, close[idx - 1] - close[idx]) for idx in range(minute - 13, minute + 1)]
    gain_mean, loss_mean = sum(gains) / 14, sum(losses) / 14
    rsi = 100.0 if loss_mean == 0 else 100 - 100 / (1 + gain_mean / loss_mean)

    plus_dm: list[float] = []
    minus_dm: list[float] = []
    true_ranges: list[float] = []
    for idx in range(minute - 13, minute + 1):
        high, low = day.high[idx], day.low[idx]
        previous_high, previous_low = day.high[idx - 1], day.low[idx - 1]
        if high is None or low is None or previous_high is None or previous_low is None:
            return None
        up = float(high) - float(previous_high)
        down = float(previous_low) - float(low)
        plus_dm.append(max(up, 0.0) if up > down else 0.0)
        minus_dm.append(max(down, 0.0) if down > up else 0.0)
        true_ranges.append(
            max(
                float(high) - float(low),
                abs(float(high) - close[idx - 1]),
                abs(float(low) - close[idx - 1]),
            )
        )
    tr = sum(true_ranges)
    plus_di = 100 * sum(plus_dm) / tr if tr else 0.0
    minus_di = 100 * sum(minus_dm) / tr if tr else 0.0
    adx_proxy = 100 * abs(plus_di - minus_di) / (plus_di + minus_di) if plus_di + minus_di else 0.0

    sma_series = [sum(close[idx - 13 : idx + 1]) / 14 for idx in range(minute - 13, minute + 1)]
    close_series = list(close[minute - 13 : minute + 1])
    mean_sma, mean_close = sum(sma_series) / 14, sum(close_series) / 14
    covariance = sum(
        (x - mean_sma) * (y - mean_close) for x, y in zip(sma_series, close_series, strict=True)
    )
    var_sma = sum((x - mean_sma) ** 2 for x in sma_series)
    var_close = sum((y - mean_close) ** 2 for y in close_series)
    correlation = covariance / math.sqrt(var_sma * var_close) if var_sma and var_close else 0.0

    typical: list[float] = []
    for idx in range(minute - 13, minute + 1):
        high, low = day.high[idx], day.low[idx]
        if high is None or low is None:
            return None
        typical.append((high + low + close[idx]) / 3)
    volumes = list(day.volume[minute - 13 : minute + 1])
    total_volume = sum(volumes)
    vwap = (
        sum(price * volume for price, volume in zip(typical, volumes, strict=True)) / total_volume
        if total_volume
        else close[minute]
    )
    features = [
        close[minute] / close[minute - 1] - 1,
        close[minute] / close[minute - 15] - 1,
        rsi,
        adx_proxy,
        (sum(close[minute - 13 : minute + 1]) / 14) / close[minute],
        correlation,
        volatility(14),
        volatility(210),
        vwap / close[minute],
    ]
    return features if all(math.isfinite(value) for value in features) else None


def _decision_tree(stock_days: Mapping[str, Sequence[ip.Day]]) -> dict[str, Any]:
    """Depth-four Gini tree adaptation of Naga et al. (2024), trained per stock."""
    try:
        from sklearn.tree import DecisionTreeClassifier
    except ImportError as exc:  # pragma: no cover - exercised by the optional runner
        raise RuntimeError(
            "install the optional research-ml extra to run the Naga et al. tree"
        ) from exc

    eval_returns: dict[date, float] = {}
    gross_returns: dict[date, float] = {}
    costs_total = 0.0
    events = 0
    capital_per_name = CAPITAL / len(stock_days)
    for days in stock_days.values():
        train_x: list[list[float]] = []
        train_y: list[int] = []
        eval_rows: list[tuple[date, list[float], float, float]] = []
        for day in days:
            for minute in range(210, day.last):
                features = _tree_features(day, minute)
                if features is None:
                    continue
                target = int(day.close[minute + 1] > day.close[minute])
                if TRAIN_START <= day.day <= TRAIN_END:
                    train_x.append(features)
                    train_y.append(target)
                elif EVAL_START <= day.day <= DATA_END:
                    entry, exit_ = day.open_[minute + 1], day.close[minute + 1]
                    if entry is not None and entry > 0 and exit_ > 0:
                        eval_rows.append((day.day, features, float(entry), exit_))
        if not train_x or not eval_rows:
            continue
        model = DecisionTreeClassifier(criterion="gini", max_depth=4, random_state=0)
        model.fit(train_x, train_y)
        predictions = model.predict([row[1] for row in eval_rows])
        for prediction, (when, _, entry, exit_) in zip(predictions, eval_rows, strict=True):
            direction = 1 if int(prediction) == 1 else -1
            shares = max(1, int(capital_per_name / entry))
            from eulerlab.costs.router import fill_cost

            entry_side, exit_side = (
                (Side.BUY, Side.SELL) if direction > 0 else (Side.SELL, Side.BUY)
            )
            costs = sum(
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
            costs += capital_per_name * 2 * STOCK_SLIPPAGE_BPS / 10_000
            gross = direction * shares * (exit_ - entry)
            gross_returns[when] = gross_returns.get(when, 0.0) + gross / CAPITAL
            eval_returns[when] = eval_returns.get(when, 0.0) + (gross - costs) / CAPITAL
            costs_total += costs
            events += 1
    calendar = sorted(
        {
            day.day
            for days in stock_days.values()
            for day in days
            if EVAL_START <= day.day <= DATA_END
        }
    )
    gross_daily = [(day, gross_returns.get(day, 0.0)) for day in calendar]
    net_daily = [(day, eval_returns.get(day, 0.0)) for day in calendar]
    return {
        "source": "Naga-et-al-2024",
        "rule": "Gini decision tree, max depth 4, nine one-minute features, predict next-minute return sign",
        "instrument": ", ".join(stock_days),
        "training_window": [TRAIN_START.isoformat(), TRAIN_END.isoformat()],
        "evaluation_window": [EVAL_START.isoformat(), DATA_END.isoformat()],
        "features": [
            "1m return",
            "15m return",
            "RSI14",
            "ADX14 proxy",
            "SMA14/close",
            "correlation(SMA14,close;14)",
            "volatility14",
            "volatility210",
            "VWAP14/close",
        ],
        "events": events,
        "estimated_transaction_costs": round(costs_total, 2),
        "slippage_bps_per_side": STOCK_SLIPPAGE_BPS,
        "gross": _stats(gross_daily),
        "net": _stats(net_daily),
        "daily": [[day.isoformat(), round(value, 8)] for day, value in net_daily],
        "note": "No gap interpolation. ADX14 is a rolling proxy; source vendor, universe and preprocessing differ.",
    }


def screen(*, root: Path | None = None) -> dict[str, Any]:
    """Run the predeclared gold moving-average screen and one stock candidate."""
    gold_days = load_days(GOLD, root=root)
    stock_days = {symbol: load_days(symbol, root=root) for symbol in STOCKS}
    gold_runs = [
        _gold_rule(gold_days, method=method, slow=slow)
        for method in GOLD_METHODS
        for slow in GOLD_HORIZONS
    ]
    return {
        "research": "docs/RESEARCH/084-gold-and-indian-stock-intraday-screen.md",
        "window": (
            [gold_days[0].day.isoformat(), gold_days[-1].day.isoformat()] if gold_days else []
        ),
        "data_cutoff": DATA_END.isoformat(),
        "holdout_read": False,
        "gold_data_window": [day.day.isoformat() for day in gold_days[:1]]
        + ([gold_days[-1].day.isoformat()] if gold_days else []),
        "gold_data_note": "GOLDBEES is a listed Gold ETF proxy; MCX futures are unavailable.",
        "gold_runs": gold_runs,
        "stock_run": _extreme_reversal(stock_days),
        "stock_tree_run": _decision_tree(stock_days),
        "stock_data_windows": {
            symbol: ([days[0].day.isoformat(), days[-1].day.isoformat()] if days else [])
            for symbol, days in stock_days.items()
        },
        "screened_configurations": len(gold_runs) + 2,
        "note": "Fixed literature settings. Screening only; no tuning or profitability claim.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="gold-stock-intraday-screen")
    parser.add_argument(
        "--output", type=Path, default=data_path("derived/gold_stock_intraday_screen.json")
    )
    args = parser.parse_args()
    result = screen()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(f"wrote {args.output}; {result['screened_configurations']} fixed settings")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
