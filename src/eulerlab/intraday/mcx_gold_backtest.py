"""Run the frozen Gold ETF filter on landed MCX Gold futures minute bars.

The settings are SMA(50), a 20 bp dead band, next-five-minute-open execution,
and intraday flat. They are carried over unchanged from research 085; this
module does not optimize on the short MCX sample.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

DEFAULT_ROOT = Path("data/landing/mcx_gold")
DEFAULT_OUTPUT = Path("data/derived/mcx_gold_backtest.json")
PRICE_MULTIPLIER = 100  # MCX standard Gold: 1 kg lot, quoted per 10 grams.
SMA_BARS = 50
BAND_BPS = 20
SLIPPAGE_BPS = 2.0
MIN_SESSION_BARS = 150


@dataclass(frozen=True)
class Bar:
    open: float
    high: float
    low: float
    close: float
    volume: int


def load_sessions(root: Path = DEFAULT_ROOT, *, symbol: str | None = None) -> dict[date, list[Bar]]:
    """Read landed minute chunks and aggregate their observed minutes to 5m."""
    manifest = root / "manifest.jsonl"
    if not manifest.exists():
        raise FileNotFoundError(f"No MCX Gold minute manifest at {manifest}")
    entries = [
        json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines() if line
    ]
    by_session: dict[date, dict[datetime, list[float | int]]] = defaultdict(dict)
    for entry in entries:
        if symbol is not None and entry.get("symbol") != symbol:
            continue
        path = root / entry["path"]
        table = pq.read_table(path, columns=["ts", "open", "high", "low", "close", "volume"])
        for stamp, open_, high, low, close, volume in zip(
            *(table.column(name).to_pylist() for name in table.column_names), strict=True
        ):
            if None in (stamp, open_, high, low, close):
                continue
            minute_ts = datetime.fromisoformat(str(stamp)[:19])
            # MCX session is 09:00 through 23:30/23:55. Bars outside it are
            # ignored instead of being misfiled into the following session.
            if not 9 <= minute_ts.hour <= 23:
                continue
            minutes_from_open = minute_ts.hour * 60 + minute_ts.minute - 9 * 60
            if minutes_from_open < 0 or minutes_from_open > 14 * 60 + 55:
                continue
            bucket = minutes_from_open // 5
            start = datetime.combine(minute_ts.date(), datetime.min.time()).replace(hour=9)
            bar_ts = start + timedelta(minutes=bucket * 5)
            key = date.fromisoformat(str(stamp)[:10])
            row = by_session[key].setdefault(
                bar_ts, [float(open_), float(high), float(low), float(close), 0]
            )
            row[1] = max(row[1], float(high))
            row[2] = min(row[2], float(low))
            row[3] = float(close)
            row[4] += int(volume or 0)
    return {
        day: [
            Bar(
                open=float(row[0]),
                high=float(row[1]),
                low=float(row[2]),
                close=float(row[3]),
                volume=int(row[4]),
            )
            for _, row in sorted(bars.items())
        ]
        for day, bars in sorted(by_session.items())
        if bars
    }


def _fill_cost(price: float, lot_size: int, side: str, slippage_bps: float) -> tuple[float, float]:
    """Zerodha/MCX commodity futures charges plus explicit slippage.

    Rates: MCX transaction 0.0021%; non-agri CTT 0.01% on sells; stamp duty
    0.002% on buys; SEBI ₹10/crore; brokerage 0.03% capped at ₹20; GST 18%
    on brokerage, exchange and SEBI charges. The market-value multiplier is
    100 because a standard Gold contract is 1 kg quoted per 10 g.
    """
    turnover = price * lot_size * PRICE_MULTIPLIER
    brokerage = min(turnover * 0.0003, 20.0)
    transaction = turnover * 0.000021
    sebi = turnover * 0.000001
    ctt = turnover * 0.0001 if side == "sell" else 0.0
    stamp = turnover * 0.00002 if side == "buy" else 0.0
    gst = 0.18 * (brokerage + transaction + sebi)
    fees = brokerage + transaction + sebi + ctt + stamp + gst
    slippage = turnover * slippage_bps / 10_000
    return fees, slippage


def _summarize(daily_pnl: dict[date, float], base_notional: float) -> dict[str, Any]:
    ordered = sorted(daily_pnl.items())
    returns = [pnl / base_notional for _, pnl in ordered]
    mean = statistics.fmean(returns) if returns else 0.0
    stdev = statistics.stdev(returns) if len(returns) > 1 else 0.0
    equity = peak = 1.0
    max_drawdown = 0.0
    for value in returns:
        equity += value
        peak = max(peak, equity)
        max_drawdown = min(max_drawdown, equity / peak - 1)
    return {
        "sessions": len(returns),
        "pnl_rupees": round(sum(daily_pnl.values()), 2),
        "return_on_initial_contract_notional": round(sum(returns), 6),
        "daily_sharpe": round(mean / stdev * math.sqrt(252), 3) if stdev else None,
        "max_drawdown_on_initial_contract_notional": round(max_drawdown, 6),
        "daily": [[day.isoformat(), round(value, 2)] for day, value in ordered],
    }


def run_backtest(
    sessions: dict[date, list[Bar]],
    *,
    symbol: str,
    lot_size: int = 1,
    slippage_bps: float = SLIPPAGE_BPS,
) -> dict[str, Any]:
    """Apply frozen SMA(50)+20bp filter to one contract, flat every session."""
    if lot_size <= 0:
        raise ValueError("lot_size must be positive")
    usable = {day: bars for day, bars in sessions.items() if len(bars) >= MIN_SESSION_BARS}
    if not usable:
        raise ValueError("No MCX Gold sessions to backtest")

    first_bar = next(iter(usable.values()))[0]
    base_notional = first_bar.open * lot_size * PRICE_MULTIPLIER
    history: list[float] = []
    gross_daily: dict[date, float] = defaultdict(float)
    net_daily: dict[date, float] = defaultdict(float)
    benchmark_gross: dict[date, float] = defaultdict(float)
    benchmark_net: dict[date, float] = defaultdict(float)
    fees_total = slippage_total = 0.0
    fills = 0
    trade_days = 0
    total_bars = 0

    def transact(day: date, price: float, side: str) -> None:
        nonlocal fees_total, slippage_total, fills
        fees, slip = _fill_cost(price, lot_size, side, slippage_bps)
        net_daily[day] -= fees + slip
        fees_total += fees
        slippage_total += slip
        fills += 1

    for day, bars in sorted(usable.items()):
        if len(bars) < SMA_BARS + 2:
            continue
        total_bars += len(bars)
        benchmark_pnl = (bars[-1].close - bars[0].open) * lot_size * PRICE_MULTIPLIER
        benchmark_gross[day] += benchmark_pnl
        benchmark_net[day] += benchmark_pnl
        buy_fees, buy_slippage = _fill_cost(bars[0].open, lot_size, "buy", slippage_bps)
        sell_fees, sell_slippage = _fill_cost(bars[-1].close, lot_size, "sell", slippage_bps)
        benchmark_net[day] -= buy_fees + sell_fees + buy_slippage + sell_slippage
        position = 0
        day_traded = False
        for index, bar in enumerate(bars[:-1]):
            history.append(bar.close)
            next_bar = bars[index + 1]
            # Mark the position held from this bar's open to the next bar's
            # open. A signal computed at this close only takes effect at that
            # next open.
            bar_pnl = position * (next_bar.open - bar.open) * lot_size * PRICE_MULTIPLIER
            gross_daily[day] += bar_pnl
            net_daily[day] += bar_pnl
            if len(history) < SMA_BARS:
                continue
            average = sum(history[-SMA_BARS:]) / SMA_BARS
            distance = (bar.close / average - 1) * 10_000
            signal = 1 if distance >= BAND_BPS else -1 if distance <= -BAND_BPS else position
            if signal != position:
                if position:
                    transact(day, next_bar.open, "sell" if position > 0 else "buy")
                if signal:
                    transact(day, next_bar.open, "buy" if signal > 0 else "sell")
                position = signal
                day_traded = True
        history.append(bars[-1].close)
        final_bar = bars[-1]
        final_pnl = position * (final_bar.close - final_bar.open) * lot_size * PRICE_MULTIPLIER
        gross_daily[day] += final_pnl
        net_daily[day] += final_pnl
        if position:
            transact(day, bars[-1].close, "sell" if position > 0 else "buy")
            day_traded = True
        trade_days += int(day_traded)

    gross = _summarize(dict(gross_daily), base_notional)
    net = _summarize(dict(net_daily), base_notional)
    benchmark = {
        "gross": _summarize(dict(benchmark_gross), base_notional),
        "net": _summarize(dict(benchmark_net), base_notional),
    }
    return {
        "instrument": symbol,
        "contract_lot_size": lot_size,
        "contract_price_multiplier": PRICE_MULTIPLIER,
        "bars": total_bars,
        "sessions_seen": len(sessions),
        "sessions_used": len(usable),
        "sessions_excluded_for_sparse_history": len(sessions) - len(usable),
        "trading_days_with_orders": trade_days,
        "fills": fills,
        "starting_contract_notional_rupees": round(base_notional, 2),
        "settings": {
            "method": "SMA",
            "period_5m_bars": SMA_BARS,
            "dead_band_bps": BAND_BPS,
            "execution": "next 5-minute bar open",
            "flat_at_session_end": True,
            "slippage_bps_per_side": slippage_bps,
        },
        "costs": {
            "fees_rupees": round(fees_total, 2),
            "slippage_rupees": round(slippage_total, 2),
            "note": "Zerodha MCX commodity schedule; see source links in research 086.",
        },
        "gross": gross,
        "net": net,
        "long_intraday_benchmark": benchmark,
        "data_limit": "Uses only minute sessions present in the selected landing root.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mcx-gold-backtest")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--slippage-bps", type=float, default=SLIPPAGE_BPS)
    parser.add_argument(
        "--lot-size",
        type=int,
        default=None,
        help="contract lot size when it is not present in the Kite MCX snapshot",
    )
    args = parser.parse_args(argv)
    manifest = [
        json.loads(line)
        for line in (args.root / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
        if line
    ]
    if not manifest:
        raise FileNotFoundError(f"No MCX Gold minute chunks under {args.root}")
    symbol = str(manifest[-1]["symbol"])
    manifest = [row for row in manifest if row["symbol"] == symbol]
    sessions = load_sessions(args.root, symbol=symbol)
    import csv

    lot_size = args.lot_size
    if lot_size is None:
        instrument_files = sorted(Path("data/landing/mcx/instruments").glob("**/*_instruments.csv"))
        if not instrument_files:
            raise FileNotFoundError("No MCX instrument snapshot is available to read lot size")
        with instrument_files[-1].open(newline="") as handle:
            contracts = list(csv.DictReader(handle))
        contract = next(row for row in contracts if row["tradingsymbol"] == symbol)
        lot_size = int(contract["lot_size"])
    result = run_backtest(
        sessions,
        symbol=symbol,
        lot_size=lot_size,
        slippage_bps=args.slippage_bps,
    )
    result["data"] = {
        "start": min(sessions).isoformat(),
        "end": max(sessions).isoformat(),
        "sessions_seen": len(sessions),
        "sessions_used": result["sessions_used"],
        "backtest_start": min(
            day for day, bars in sessions.items() if len(bars) >= MIN_SESSION_BARS
        ).isoformat(),
        "backtest_end": max(
            day for day, bars in sessions.items() if len(bars) >= MIN_SESSION_BARS
        ).isoformat(),
        "minute_chunks": len(manifest),
    }
    result["window"] = [result["data"]["backtest_start"], result["data"]["backtest_end"]]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(
        f"{result['instrument']} {result['data']['start']}..{result['data']['end']}: "
        f"gross {result['gross']['return_on_initial_contract_notional']:+.2%}, "
        f"net {result['net']['return_on_initial_contract_notional']:+.2%}, "
        f"{result['fills']} fills across {result['data']['sessions_used']} usable sessions"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
