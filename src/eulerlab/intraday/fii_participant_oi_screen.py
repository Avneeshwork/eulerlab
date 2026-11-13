"""Lagged NSE participant futures positioning screen (research 097).

The source is a daily position snapshot, not an intraday order-flow feed. This
screen uses a conservative two-session lag and tests one fixed long/short rule
on five liquid NSE stocks. It must never be described as a stock-level FII
trade signal.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import statistics
from collections import defaultdict
from datetime import date
from itertools import pairwise
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from eulerlab.costs.schedule import Segment, Side
from eulerlab.ingest.landing import Landing
from eulerlab.intraday import india_papers as ip
from eulerlab.intraday import research_screen as rs
from eulerlab.intraday import screen_common as sc
from eulerlab.paths import data_path

OUT = data_path("derived/fii_participant_oi_stock_strategies.json")
LANDING = data_path("landing/nse")
SYMBOLS = ("RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "TCS")
CAPITAL = 1_000_000.0
NOTIONAL = CAPITAL / len(SYMBOLS)
EVAL_START = date(2024, 1, 1)
DATA_END = rs.DATA_END
SLIPPAGE_BPS = 2.0
VOLATILITY_SCREEN = "nse_fii_decline_dii_absorption_volatility"


def _clean_header(value: str | None) -> str:
    return (value or "").replace("\ufeff", "").strip().rstrip(",")


def _number(value: str | None) -> int:
    return int((value or "0").strip().replace(",", ""))


def parse_report(payload: bytes) -> dict[str, int] | None:
    """Return participant index-futures net positions from one NSE report."""
    lines = payload.decode("utf-8-sig", errors="replace").splitlines()
    header = next(
        (i for i, line in enumerate(lines) if line.lstrip().startswith("Client Type")), None
    )
    if header is None:
        return None
    reader = csv.DictReader(io.StringIO("\n".join(lines[header:])))
    fields = {_clean_header(name): name for name in (reader.fieldnames or [])}
    long_field = fields.get("Future Index Long")
    short_field = fields.get("Future Index Short")
    client_field = fields.get("Client Type")
    if not long_field or not short_field or not client_field:
        return None
    result: dict[str, int] = {}
    for row in reader:
        client = (row.get(client_field) or "").strip()
        if client in {"FII", "DII"}:
            result[client] = _number(row.get(long_field)) - _number(row.get(short_field))
    return result if set(result) == {"FII", "DII"} else None


def load_positions(*, start: date, end: date, root: Path = LANDING) -> dict[date, dict[str, int]]:
    landing = Landing(root)
    out: dict[date, dict[str, int]] = {}
    for entry in landing.entries().values():
        if entry.segment != "participant_oi":
            continue
        when = date.fromisoformat(entry.trade_date)
        if start <= when <= end:
            path = root / entry.path
            if path.exists():
                parsed = parse_report(path.read_bytes())
                if parsed is not None:
                    out[when] = parsed
    return out


def load_days(symbol: str, *, cutoff: date = DATA_END) -> list[ip.Day]:
    rows: dict[str, dict[int, tuple[float, float, float, float, float]]] = {}
    for name, blob in rs._files(symbol, cutoff=cutoff):
        table = pq.read_table(
            io.BytesIO(blob), columns=["ts", "open", "high", "low", "close", "volume"]
        )
        columns = [table.column(name).to_pylist() for name in table.column_names]
        for stamp, open_, high, low, close, volume in zip(*columns, strict=True):
            if stamp is None or open_ is None or high is None or low is None or close is None:
                continue
            day_text = stamp[:10]
            if date.fromisoformat(day_text) > cutoff:
                raise ValueError(f"cutoff-crossing price row: {symbol} {day_text}")
            minute = (int(stamp[11:13]) - 9) * 60 + int(stamp[14:16]) - 15
            if 0 <= minute < ip.MINUTES:
                rows.setdefault(day_text, {})[minute] = (
                    float(open_),
                    float(high),
                    float(low),
                    float(close),
                    float(volume or 0),
                )
    return ip.days_from_rows(rows)


def _fill_cost(price: float, quantity: int, side: Side, when: date) -> float:
    from eulerlab.costs.router import fill_cost

    return fill_cost(
        venue="equity",
        price=price,
        quantity=quantity,
        side=side,
        day=when,
        segment=Segment.EQUITY_INTRADAY,
    )


def _stats(daily: list[tuple[date, float]]) -> dict[str, Any]:
    return sc.daily_stats([value for _, value in daily])


def backtest(
    prices: dict[str, list[ip.Day]], positions: dict[date, dict[str, int]]
) -> dict[str, Any]:
    by_symbol = {symbol: {day.day: day for day in rows} for symbol, rows in prices.items()}
    common = sorted(set.intersection(*(set(days) for days in by_symbol.values())))
    if not common:
        raise ValueError("no common stock sessions")
    position_days = sorted(positions)
    # Align only on report dates that match actual common equity sessions.
    position_days = [when for when in position_days if when in set(common)]
    position_index = {when: index for index, when in enumerate(position_days)}
    daily_net: dict[date, float] = defaultdict(float)
    daily_gross: dict[date, float] = defaultdict(float)
    trades: list[dict[str, Any]] = []
    signals: list[dict[str, Any]] = []
    calendar_index = {when: index for index, when in enumerate(common)}

    for when in common:
        if not EVAL_START <= when <= DATA_END:
            continue
        i = calendar_index[when]
        if i < 2:
            continue
        # Signal uses a position change published on a report date two whole
        # equity sessions before entry. This avoids same-day/EOD lookahead.
        current_report = common[i - 2]
        previous_report = common[i - 3] if i >= 3 else None
        if (
            previous_report is None
            or current_report not in position_index
            or previous_report not in position_index
        ):
            continue
        cur = positions[current_report]
        prev = positions[previous_report]
        fii_delta = cur["FII"] - prev["FII"]
        dii_delta = cur["DII"] - prev["DII"]
        direction = 1 if fii_delta > 0 else (-1 if fii_delta < 0 else 0)
        if direction == 0:
            continue
        signals.append(
            {
                "day": when.isoformat(),
                "source_report": current_report.isoformat(),
                "fii_net_index_futures_change": fii_delta,
                "dii_net_index_futures_change": dii_delta,
                "side": "long" if direction > 0 else "short",
                "dii_agrees": bool(dii_delta and (dii_delta > 0) == (direction > 0)),
            }
        )
        for symbol, days in by_symbol.items():
            day = days[when]
            entry, exit_ = day.fill_at(ip.FIRST_TRADABLE), day.fill_at(355)
            if entry is None or exit_ is None or exit_[0] <= entry[0]:
                continue
            qty = max(1, int(NOTIONAL / entry[1]))
            gross = direction * (exit_[1] - entry[1]) * qty
            buy, sell = (entry, exit_) if direction > 0 else (exit_, entry)
            costs = _fill_cost(buy[1], qty, Side.BUY, when) + _fill_cost(
                sell[1], qty, Side.SELL, when
            )
            costs += (entry[1] + exit_[1]) * qty * SLIPPAGE_BPS / 10_000.0
            daily_gross[when] += gross / CAPITAL
            daily_net[when] += (gross - costs) / CAPITAL
            trades.append(
                {
                    "day": when.isoformat(),
                    "symbol": symbol,
                    "side": "long" if direction > 0 else "short",
                    "entry": round(entry[1], 4),
                    "exit": round(exit_[1], 4),
                    "gross_pnl": round(gross, 2),
                    "costs": round(costs, 2),
                }
            )

    traded_dates = sorted(date.fromisoformat(row["day"]) for row in signals)
    gross_daily = [(day, daily_gross[day]) for day in traded_dates]
    net_daily = [(day, daily_net[day]) for day in traded_dates]
    group_returns: dict[str, list[float]] = {"dii_agrees": [], "dii_opposes": []}
    signal_by_day = {date.fromisoformat(row["day"]): row for row in signals}
    for traded_day in traded_dates:
        signal = signal_by_day[traded_day]
        category = "dii_agrees" if signal["dii_agrees"] else "dii_opposes"
        group_returns[category].append(daily_net[traded_day])
    return {
        "window": [EVAL_START.isoformat(), DATA_END.isoformat()],
        "universe": list(prices),
        "lag_sessions": 2,
        "entry_time": "09:16 first traded minute open",
        "exit_time": "15:10 first traded minute open",
        "position_definition": "daily participant index-futures long minus short open interest",
        "fii_signal": "sign of FII net-position change; applied two sessions after report date",
        "dii_role": "separate descriptive split: DII change agrees with or opposes FII signal",
        "capital_rupees": CAPITAL,
        "notional_per_stock": NOTIONAL,
        "slippage_bps_per_side": SLIPPAGE_BPS,
        "gross": _stats(gross_daily),
        "net": _stats(net_daily),
        "trades": len(trades),
        "fills": 2 * len(trades),
        "estimated_costs_rupees": round(sum(row["costs"] for row in trades), 2),
        "dii_agrees_net_daily_mean": round(statistics.fmean(group_returns["dii_agrees"]), 6)
        if group_returns["dii_agrees"]
        else None,
        "dii_opposes_net_daily_mean": round(statistics.fmean(group_returns["dii_opposes"]), 6)
        if group_returns["dii_opposes"]
        else None,
        "daily": [[day.isoformat(), round(value, 8)] for day, value in net_daily],
        "signals": signals,
        "trade_log": trades,
    }


def _realized_volatility(day: ip.Day) -> float | None:
    """Annualization-free one-session realized volatility from minute closes."""
    closes = [value for value in day.close if value is not None and value > 0]
    if len(closes) < 30:
        return None
    returns = [math.log(right / left) for left, right in pairwise(closes)]
    return math.sqrt(sum(value * value for value in returns))


def _summary(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"sessions": 0, "mean_rv_ratio": None, "median_rv_ratio": None}
    return {
        "sessions": len(values),
        "mean_rv_ratio": round(statistics.fmean(values), 4),
        "median_rv_ratio": round(statistics.median(values), 4),
    }


def volatility_moderation(
    prices: dict[str, list[ip.Day]], positions: dict[date, dict[str, int]]
) -> dict[str, Any]:
    """Test whether DII net-OI increases moderate volatility after FII OI drops.

    Shock cutoffs use only the prior 60 report-to-report changes. The report
    must predate the evaluated session by two full equity sessions. Outcomes
    are per-stock realized-volatility ratios against that stock's preceding
    20 sessions, averaged cross-sectionally. This is descriptive, not a
    trading backtest or a test of cash-market flow.
    """
    by_symbol = {symbol: {day.day: day for day in rows} for symbol, rows in prices.items()}
    common = sorted(set.intersection(*(set(days) for days in by_symbol.values())))
    report_days = [when for when in sorted(positions) if when in set(common)]
    report_deltas = {
        when: {
            participant: positions[when][participant] - positions[previous][participant]
            for participant in ("FII", "DII")
        }
        for previous, when in pairwise(report_days)
    }
    sessions: list[dict[str, Any]] = []
    for i, when in enumerate(common):
        if not EVAL_START <= when <= DATA_END or i < 2:
            continue
        signal_report = common[i - 2]
        delta = report_deltas.get(signal_report)
        prior_changes = [
            report_deltas[day]["FII"]
            for day in report_days
            if day < signal_report and day in report_deltas
        ][-60:]
        if delta is None or len(prior_changes) < 40 or delta["FII"] >= 0:
            continue
        cutoff = float(sorted(prior_changes)[int(0.2 * (len(prior_changes) - 1))])
        if delta["FII"] > cutoff:
            continue

        ratios = []
        for days in by_symbol.values():
            history: list[float] = []
            for prior in common[max(0, i - 20) : i]:
                value = _realized_volatility(days[prior])
                if value is not None and value > 0:
                    history.append(value)
            current = _realized_volatility(days[when])
            if current is not None and history:
                ratios.append(current / statistics.fmean(history))
        if ratios:
            sessions.append(
                {
                    "day": when.isoformat(),
                    "source_report": signal_report.isoformat(),
                    "fii_net_index_futures_change": delta["FII"],
                    "dii_net_index_futures_change": delta["DII"],
                    "dii_absorbs_proxy": delta["DII"] > 0,
                    "mean_stock_rv_ratio": statistics.fmean(ratios),
                }
            )

    absorbed: list[float] = [
        float(row["mean_stock_rv_ratio"]) for row in sessions if row["dii_absorbs_proxy"]
    ]
    not_absorbed: list[float] = [
        float(row["mean_stock_rv_ratio"]) for row in sessions if not row["dii_absorbs_proxy"]
    ]
    return {
        "window": [EVAL_START.isoformat(), DATA_END.isoformat()],
        "lag_sessions": 2,
        "fii_shock_definition": "negative FII net index-futures OI change at or below trailing 20th percentile of up to 60 earlier report changes; minimum 40",
        "dii_absorption_proxy": "positive DII net index-futures OI change on the same report interval",
        "outcome": "cross-sectional mean of each stock's full-session minute realized volatility divided by its trailing 20-session mean",
        "dii_absorption": _summary(absorbed),
        "no_dii_absorption": _summary(not_absorbed),
        "event_sessions": len(sessions),
        "event_log": sessions,
        "interpretation": "OI change is a position change, not cash buying/selling, and may include hedging or contract effects.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="fii-participant-oi-screen")
    parser.add_argument("--root", type=Path, default=LANDING)
    args = parser.parse_args()
    positions = load_positions(start=date(2023, 12, 1), end=DATA_END, root=args.root)
    prices = {symbol: load_days(symbol) for symbol in SYMBOLS}
    result = backtest(prices, positions)
    volatility = volatility_moderation(prices, positions)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "research": "docs/RESEARCH/097-fii-dii-entry-exit-impact.md",
        "window": result["window"],
        "universe": result["universe"],
        "spent_trials": 0,
        "result": result,
        "volatility_moderation": volatility,
    }
    OUT.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    print(
        f"FII OI lagged direction: {result['net']['total_return']:+.2%} net, "
        f"Sharpe {result['net']['sharpe']}, {result['trades']} fills, "
        f"costs ₹{result['estimated_costs_rupees']:,.0f}"
    )
    print(f"wrote {OUT}")
    print(
        "FII exposure-drop volatility: DII-rise RV ratio "
        f"{volatility['dii_absorption']['mean_rv_ratio']} "
        f"(n={volatility['dii_absorption']['sessions']}), no DII rise "
        f"{volatility['no_dii_absorption']['mean_rv_ratio']} "
        f"(n={volatility['no_dii_absorption']['sessions']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
