"""Cost-aware 30-minute random-forest signal screen on NSE one-minute bars.

This is an independent India adaptation of Gaona, Rangel-Madariaga & Uribe
(2026). The published paper compares several learners and horizons; this
screen freezes one source-favored horizon and a Random Forest, trains only on
2022-2023, and evaluates once on 2024 through the existing strict cutoff.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier

from eulerlab.costs.schedule import Side
from eulerlab.intraday import india_papers as ip
from eulerlab.intraday import research_screen as rs
from eulerlab.intraday import screen_common as sc

OUT = Path("data/derived/cost_aware_ml_nse_stock_strategies.json")
SYMBOLS = ("RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "TCS")
CAPITAL = 1_000_000.0
NOTIONAL = CAPITAL / len(SYMBOLS)
SLIPPAGE_BPS = 2.0
HORIZON = 30
TRAIN_START = date(2022, 1, 1)
TRAIN_END = date(2023, 12, 31)
EVAL_START = date(2024, 1, 1)
DATA_END = date(2024, 11, 30)
EXIT_MINUTE = 355  # 15:10, before the broker MIS square-off.
SEED = 20261015

FEATURES = (
    "sma10_gap",
    "ema10_gap",
    "vwap_gap",
    "macd_gap",
    "macd_signal_gap",
    "stoch_k",
    "stoch_d",
    "momentum1",
    "roc1",
    "bb_percent",
    "bb_width",
    "rsi14",
)


def _records(days: list[ip.Day]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for session in days:
        for minute in range(ip.FIRST_TRADABLE, min(session.last, EXIT_MINUTE) + 1):
            rows.append(
                {
                    "day": session.day,
                    "minute": minute,
                    "open": session.open_[minute],
                    "high": session.high[minute],
                    "low": session.low[minute],
                    "close": session.close[minute],
                    "volume": session.volume[minute],
                }
            )
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    frame["typical"] = (frame["high"] + frame["low"] + frame["close"]) / 3.0
    close = frame["close"].astype(float)
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    volume = frame["volume"].astype(float)

    frame["sma10_gap"] = close.rolling(10, min_periods=10).mean() / close - 1.0
    frame["ema10_gap"] = close.ewm(span=10, adjust=False, min_periods=10).mean() / close - 1.0
    cumulative_value = (frame["typical"] * volume).groupby(frame["day"]).cumsum()
    cumulative_volume = volume.groupby(frame["day"]).cumsum().replace(0, np.nan)
    frame["vwap_gap"] = cumulative_value / cumulative_volume / close - 1.0
    macd = (
        close.ewm(span=12, adjust=False, min_periods=26).mean()
        - close.ewm(span=26, adjust=False, min_periods=26).mean()
    )
    frame["macd_gap"] = macd / close
    frame["macd_signal_gap"] = macd.ewm(span=9, adjust=False, min_periods=9).mean() / close
    lowest, highest = low.rolling(14, min_periods=14).min(), high.rolling(14, min_periods=14).max()
    stoch = (close - lowest) / (highest - lowest).replace(0, np.nan)
    frame["stoch_k"] = stoch
    frame["stoch_d"] = stoch.rolling(3, min_periods=3).mean()
    frame["momentum1"] = close.pct_change()
    frame["roc1"] = (close / close.shift(1)) - 1.0
    mean20, sd20 = (
        close.rolling(20, min_periods=20).mean(),
        close.rolling(20, min_periods=20).std(ddof=0),
    )
    upper, lower = mean20 + 2.0 * sd20, mean20 - 2.0 * sd20
    frame["bb_percent"] = (close - lower) / (upper - lower).replace(0, np.nan)
    frame["bb_width"] = (upper - lower) / close
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    frame["rsi14"] = 100.0 - 100.0 / (1.0 + gain / loss.replace(0, np.nan))

    # A target is known only if the signal, next-minute entry, and 30-minute
    # exit are all traded within the same session and before 15:10.
    opens: dict[tuple[date, int], float] = {}
    for row in frame.itertuples():
        row_day = cast(date, row.day)
        minute = cast(int, row.minute)
        open_price = cast(float, row.open)
        opens[row_day, minute] = open_price
    labels: list[int | None] = []
    for row in frame.itertuples():
        row_day = cast(date, row.day)
        minute = cast(int, row.minute)
        open_price = cast(float, row.open)
        entry = opens.get((row_day, minute + 1)) if minute + 1 <= EXIT_MINUTE else None
        exit_ = (
            opens.get((row_day, minute + HORIZON + 1))
            if minute + HORIZON + 1 <= EXIT_MINUTE
            else None
        )
        if (
            pd.isna(open_price)
            or entry is None
            or exit_ is None
            or pd.isna(entry)
            or pd.isna(exit_)
        ):
            labels.append(None)
            continue
        quantity = max(1, int(NOTIONAL // float(entry)))
        # Use the fees for the direction the realized move would require. In
        # NSE cash equities the buy/sell fee mix is asymmetric, so a short
        # target should not use the long-side cost threshold.
        direction = 1 if float(exit_) >= float(entry) else -1
        costs = _trade_cost(entry, exit_, quantity, row_day, direction)
        threshold = costs / (entry * quantity)
        move = (exit_ - entry) / entry
        labels.append(1 if move >= threshold else (-1 if move <= -threshold else 0))
    frame["label"] = labels
    frame["entry_minute"] = frame["minute"] + 1
    frame["exit_minute"] = frame["minute"] + HORIZON + 1
    frame["entry_price"] = [
        opens.get((cast(date, row.day), cast(int, row.minute) + 1)) for row in frame.itertuples()
    ]
    frame["exit_price"] = [
        opens.get((cast(date, row.day), cast(int, row.minute) + HORIZON + 1))
        for row in frame.itertuples()
    ]
    return frame


def _trade_cost(entry: float, exit_: float, quantity: int, day: date, direction: int) -> float:
    entry_side = Side.BUY if direction > 0 else Side.SELL
    exit_side = Side.SELL if direction > 0 else Side.BUY
    fees = sc.intraday_fee(entry, quantity, entry_side, day) + sc.intraday_fee(
        exit_, quantity, exit_side, day
    )
    return fees + (entry + exit_) * quantity * SLIPPAGE_BPS / 10_000.0


def _fit_predict(frame: pd.DataFrame) -> tuple[np.ndarray, int]:
    usable = frame.dropna(subset=[*FEATURES, "label", "entry_price", "exit_price"]).copy()
    train = usable.loc[(usable["day"] >= TRAIN_START) & (usable["day"] <= TRAIN_END)]
    test = usable.loc[(usable["day"] >= EVAL_START) & (usable["day"] <= DATA_END)]
    if len(train) < 10_000 or test.empty or train["label"].nunique() < 2:
        return np.array([], dtype=int), 0
    model = RandomForestClassifier(
        n_estimators=100,
        max_depth=10,
        min_samples_leaf=10,
        max_features="sqrt",
        class_weight="balanced_subsample",
        random_state=SEED,
        n_jobs=-1,
    )
    model.fit(train.loc[:, FEATURES], train["label"].astype(int))
    predictions = model.predict(test.loc[:, FEATURES]).astype(int)
    return predictions, len(test)


def _run_symbol(symbol: str, days: list[ip.Day]) -> dict[str, Any]:
    frame = _records(days)
    predictions, prediction_count = _fit_predict(frame)
    if prediction_count == 0:
        return {"symbol": symbol, "eligible_predictions": 0, "trades": 0}
    test = frame.dropna(subset=[*FEATURES, "label", "entry_price", "exit_price"]).copy()
    test = test.loc[(test["day"] >= EVAL_START) & (test["day"] <= DATA_END)].reset_index(drop=True)
    if len(test) != len(predictions):
        raise AssertionError(
            f"prediction alignment failed for {symbol}: {len(test)} != {len(predictions)}"
        )
    test["prediction"] = predictions
    daily: dict[date, float] = defaultdict(float)
    trades: list[dict[str, Any]] = []
    next_free_minute: dict[date, int] = defaultdict(lambda: ip.FIRST_TRADABLE)
    sleeve_equity = NOTIONAL
    day_start_equity: dict[date, float] = {}
    ruined = False
    for row in test.itertuples():
        row_day = cast(date, row.day)
        minute = cast(int, row.minute)
        prediction = cast(int, row.prediction)
        if ruined or prediction == 0 or minute < next_free_minute[row_day]:
            continue
        day_start_equity.setdefault(row_day, sleeve_equity)
        direction = prediction
        entry, exit_ = cast(float, row.entry_price), cast(float, row.exit_price)
        quantity = int(sleeve_equity // entry)
        if quantity <= 0:
            continue
        raw = direction * (exit_ - entry) * quantity
        cost = _trade_cost(entry, exit_, quantity, row_day, direction)
        net_pnl = raw - cost
        sleeve_equity += net_pnl
        if sleeve_equity <= 0:
            sleeve_equity = 0.0
            ruined = True
        trades.append(
            {
                "symbol": symbol,
                "day": row_day.isoformat(),
                "side": "long" if direction > 0 else "short",
                "signal_minute": minute,
                "entry_minute": cast(int, row.entry_minute),
                "exit_minute": cast(int, row.exit_minute),
                "entry": round(entry, 4),
                "exit": round(exit_, 4),
                "quantity": quantity,
                "gross_pnl": round(raw, 2),
                "costs": round(cost, 2),
            }
        )
        next_free_minute[row_day] = cast(int, row.exit_minute)
    dates = sorted(set(test["day"].unique()))
    # Daily sleeve returns are marked against the sleeve's actual starting
    # equity for that session. Position size and fees are recomputed from live
    # equity at every sequential trade.
    previous_equity = NOTIONAL
    for day in dates:
        start = day_start_equity.get(day, previous_equity)
        end = sleeve_equity if day == dates[-1] else None
        if end is None:
            following = next((d for d in dates if d > day), None)
            if following is not None:
                end = day_start_equity.get(following, previous_equity)
            else:
                end = sleeve_equity
        daily[day] = end / start - 1.0 if start > 0 else 0.0
        previous_equity = end
    series = [daily[d] for d in dates]
    return {
        "symbol": symbol,
        "eligible_predictions": prediction_count,
        "trades": len(trades),
        "fills": 2 * len(trades),
        "gross_pnl_rupees": round(sum(t["gross_pnl"] for t in trades), 2),
        "costs_rupees": round(sum(t["costs"] for t in trades), 2),
        "ending_equity_rupees": round(sleeve_equity, 2),
        "net": sc.daily_stats(series),
        "daily": [[d.isoformat(), round(daily[d], 8)] for d in dates],
        "trade_log": trades,
    }


def run_all(*, root: Path | None = None) -> dict[str, Any]:
    data = {symbol: rs.load_days(symbol, root=root, cutoff=DATA_END) for symbol in SYMBOLS}
    runs = [_run_symbol(symbol, days) for symbol, days in data.items()]
    common_days = sorted(
        set.intersection(
            *[{d.day for d in days if EVAL_START <= d.day <= DATA_END} for days in data.values()]
        )
    )
    sleeve_equity = dict.fromkeys(SYMBOLS, NOTIONAL)
    sleeve_daily = {
        run["symbol"]: {
            date.fromisoformat(day): float(value) for day, value in run.get("daily", [])
        }
        for run in runs
    }
    combined: dict[date, float] = {}
    daily: list[float] = []
    for day in common_days:
        previous_total = sum(sleeve_equity.values())
        for symbol in SYMBOLS:
            sleeve_equity[symbol] *= 1.0 + sleeve_daily[symbol].get(day, 0.0)
        current_total = sum(sleeve_equity.values())
        combined[day] = current_total / previous_total - 1.0 if previous_total > 0 else 0.0
        daily.append(combined[day])
    return {
        "source": "Kite NSE one-minute OHLCV; only files ending on or before 2024-11-30 are opened",
        "window": [TRAIN_START.isoformat(), DATA_END.isoformat()],
        "universe": list(SYMBOLS),
        "train": [TRAIN_START.isoformat(), TRAIN_END.isoformat()],
        "evaluation": [EVAL_START.isoformat(), DATA_END.isoformat()],
        "capital_rupees": CAPITAL,
        "notional_per_stock_rupees": NOTIONAL,
        "model": "RandomForestClassifier(n_estimators=100,max_depth=10,min_samples_leaf=10,max_features=sqrt,class_weight=balanced_subsample)",
        "horizon_minutes": HORIZON,
        "runs": runs,
        "portfolio": {
            "sessions": len(common_days),
            "net": sc.daily_stats(daily),
            "trades": sum(int(r.get("trades", 0)) for r in runs),
            "fills": sum(int(r.get("fills", 0)) for r in runs),
            "ending_equity_rupees": round(sum(sleeve_equity.values()), 2),
            "estimated_costs_rupees": round(sum(float(r.get("costs_rupees", 0)) for r in runs), 2),
            "daily": [[d.isoformat(), round(combined[d], 8)] for d in common_days],
        },
        "assumptions": [
            "Indicators are calculated from information through the signal minute; VWAP resets each session.",
            "Three-class target is cost-aware: +1/-1 only when the next-open to 30-minute later open return clears modeled two-sided costs; otherwise 0.",
            "Train only on 2022-2023; 2024-01-01 through 2024-11-30 is a fixed evaluation sample, not an untouched future holdout.",
            "Signals enter at the next traded minute open and exit 30 minutes later at a traded minute open; no trades cross sessions.",
            "At most one overlapping position per stock; each stock sleeve starts with ₹200,000; date-aware NSE intraday charges plus 2 bp assumed slippage each way.",
            "Five isolated stock sleeves each begin with ₹200,000; trade size is recalculated from that sleeve's live equity before each signal, and a sleeve stops after its equity is exhausted.",
            "Five fixed liquid stocks, survivorship bias; short availability and borrow constraints are not modeled.",
            "No data after 2024-11-30 is opened.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, help="optional local parquet root for tests")
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
    result = run_all(root=args.root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    portfolio = result["portfolio"]
    print(
        f"wrote {args.output}: {portfolio['trades']} trades, net {portfolio['net']['total_return']:.2%}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
