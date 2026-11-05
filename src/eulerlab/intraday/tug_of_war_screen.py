"""Five cash rules from the overnight-daytime tug of war (research 159).

Pre-registered as H-0066 to H-0070 before any run. No minute file of a stock is
opened: the india-five cache holds each stock-day's overnight move to 09:19 and
its 09:20 and 15:10 fills. Index signals come from Kite Nifty minutes. Stocks ₹1
lakh a position, NIFTYBEES ₹10 lakh, 1x, cash-intraday charges plus 2 bps a
side, to 2024-11-29.

- **H-0066** short the top decile of 252-to-21 session momentum, buy the
  bottom, in the daytime (Lou, Polk and Skouras 2019: momentum is earned
  overnight and reverses by day).
- **H-0067** buy the top decile by count of overnight-up, daytime-down days in
  the last 20 sessions, short the bottom (Akbas et al. 2022).
- **H-0068** buy the top decile of 20-session returns, short the bottom, in the
  daytime (reversal profits are overnight, so the daytime sign is opposite).
- **H-0069** the Nifty's 20-session mean overnight move in the top fifth of its
  last 250 values: short NIFTYBEES for the day; bottom fifth: buy.
- **H-0070** a top-fifth count of overnight-up, daytime-down Nifty days: buy
  NIFTYBEES for the day.

`make tug-of-war` writes `data/derived/tug_of_war.json`. `make tug-of-war
DAILY=1` runs H-0071, H-0070's rule unchanged on daily bars from 2016 (the
Nifty's daily open and close; NIFTYBEES bought at the open, sold at the close),
and writes `data/derived/tug_of_war_daily.json`.
"""

from __future__ import annotations

import argparse
import json
import math
import pickle
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any

from eulerlab.intraday import cash_five_screen as five
from eulerlab.intraday import cross_section as cs
from eulerlab.intraday import india_five_screen as india_five
from eulerlab.intraday import india_papers as ip
from eulerlab.intraday import option_signal_screen as sig
from eulerlab.intraday import research_screen as rs

OUT = Path("data/derived/tug_of_war.json")
DAILY_OUT = Path("data/derived/tug_of_war_daily.json")
PANEL = Path("data/derived/price_panel.jsonl")
DAILY_START = date(2016, 1, 1)
MOMENTUM_FROM, MOMENTUM_TO = 252, 21
MONTH = 20
HISTORY = 250
TOP, BOTTOM = 0.8, 0.2

Ranked = dict[date, list[tuple[float, str, five.Fill]]]


def stock_ranks(cache: Mapping[str, Mapping[date, Any]]) -> tuple[Ranked, Ranked, Ranked]:
    """(momentum, tug-of-war count, month return) rankings, by session."""
    momentum: Ranked = defaultdict(list)
    tug: Ranked = defaultdict(list)
    month: Ranked = defaultdict(list)
    for symbol, marks in cache.items():
        days = sorted(marks)
        daily, daytime, overnight = [], [], []
        for d in days:
            m = marks[d]
            day_return = m.exit / m.entry - 1.0
            daytime.append(day_return)
            overnight.append(m.overnight)
            daily.append((1.0 + m.overnight) * (1.0 + day_return) - 1.0)
        logs = [math.log1p(r) for r in daily]
        for i, d in enumerate(days):
            m = marks[d]
            fill = five.Fill(sig.DAY_START, 1, m.entry_minute, m.entry, m.exit_minute, m.exit)
            if i >= MONTH:
                count = sum(1 for k in range(i - MONTH, i) if overnight[k] > 0 and daytime[k] < 0)
                tug[d].append((float(count), symbol, fill))
                month[d].append((math.expm1(sum(logs[i - MONTH : i])), symbol, fill))
            if i >= MOMENTUM_FROM:
                past = math.expm1(sum(logs[i - MOMENTUM_FROM : i - MOMENTUM_TO]))
                momentum[d].append((past, symbol, fill))
    return momentum, tug, month


def nifty_series(index: Sequence[ip.Day]) -> tuple[list[date], list[float], list[float]]:
    """(sessions, overnight moves to the 09:15 open, daytime moves open to last close)."""
    days, overnight, daytime = [], [], []
    for i in range(1, len(index)):
        before = index[i - 1].close[index[i - 1].last]
        opened = index[i].open_[0]
        if opened is None:
            continue
        days.append(index[i].day)
        overnight.append(opened / before - 1.0)
        daytime.append(index[i].close[index[i].last] / opened - 1.0)
    return days, overnight, daytime


def _extreme_signals(
    days: Sequence[date], stat: Sequence[float | None], *, high: int, low: int
) -> dict[date, int]:
    """Direction for each session from its statistic's rank among the previous 250."""
    out: dict[date, int] = {}
    for i, d in enumerate(days):
        value = stat[i]
        past = [x for x in stat[max(0, i - HISTORY) : i] if x is not None]
        if value is None or len(past) < HISTORY:
            continue
        rank = sum(1 for x in past if x < value) / HISTORY
        if rank >= TOP and high:
            out[d] = high
        elif rank <= BOTTOM and low:
            out[d] = low
    return out


def index_signals(index: Sequence[ip.Day]) -> tuple[dict[date, int], dict[date, int]]:
    """(H-0069 overnight-extreme directions, H-0070 tug-of-war longs), by session."""
    days, overnight, daytime = nifty_series(index)
    means: list[float | None] = []
    counts: list[float | None] = []
    for i in range(len(days)):
        if i < MONTH:
            means.append(None)
            counts.append(None)
            continue
        means.append(sum(overnight[i - MONTH : i]) / MONTH)
        counts.append(
            float(sum(1 for k in range(i - MONTH, i) if overnight[k] > 0 and daytime[k] < 0))
        )
    return (
        _extreme_signals(days, means, high=-1, low=1),
        _extreme_signals(days, counts, high=1, low=0),
    )


def daily_signals(bars: Mapping[date, tuple[float, float]]) -> dict[date, int]:
    """H-0070's signal from daily Nifty bars: {session: +1} on a top-fifth count."""
    days = sorted(bars)
    overnight, daytime = [], []
    for i in range(1, len(days)):
        opened, closed = bars[days[i]]
        overnight.append(opened / bars[days[i - 1]][1] - 1.0)
        daytime.append(closed / opened - 1.0)
    counts: list[float | None] = [
        None
        if i < MONTH
        else float(sum(1 for k in range(i - MONTH, i) if overnight[k] > 0 and daytime[k] < 0))
        for i in range(len(overnight))
    ]
    return _extreme_signals(days[1:], counts, high=1, low=0)


def etf_daily_bars(path: Path = PANEL) -> dict[date, tuple[float, float]]:
    out = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if f'"{five.ETF}"' not in line:
                continue
            row = json.loads(line)
            if row["s"] == five.ETF and row.get("o") and row.get("c"):
                out[date.fromisoformat(row["d"])] = (float(row["o"]), float(row["c"]))
    return out


def run_daily(output: Path = DAILY_OUT) -> dict[str, Any]:
    from eulerlab.options import expiry_straddle_screen as straddle

    index = straddle.index_days()
    signals = daily_signals(index)
    # The trade return is the Nifty's own open to close: NIFTYBEES daily opens are
    # bad first prints (median 43 bps off the index's open-to-close; research 075).
    etf = etf_daily_bars()
    bars = {d: index[d] for d in etf if d in index}
    sessions = sorted(d for d in bars if DAILY_START <= d <= cs.DATA_END)
    trades = []
    for day in sessions:
        if signals.get(day) != 1:
            continue
        opened, closed = bars[day]
        quantity = cs.sized(five.ETF_CAPITAL, opened)  # index units: charges scale with notional
        if quantity:
            trades.append(
                cs.Trade(five.ETF, day, 1, quantity, 0, opened, ip.MINUTES - 1, closed, "close")
            )
    run = cs.report(
        "nifty_tug_of_war_niftybees_daily",
        trades,
        sessions,
        params={
            "bars": "Nifty 50 daily open to close, costed as NIFTYBEES",
            "slippage_bps_per_side": cs.SLIPPAGE_BPS,
        },
        capital=five.ETF_CAPITAL,
    )
    daily = [(date.fromisoformat(d), r) for d, r in run.pop("daily")]
    from eulerlab.intraday import screen_common as sc

    run["net_halves"] = {
        "2016_2020": sc.daily_stats([r for d, r in daily if d.year <= 2020]),
        "2021_2024": sc.daily_stats([r for d, r in daily if d.year >= 2021]),
    }
    run["trade_log"] = run.get("trade_log", [])[:200]
    result = {
        "hypothesis": "H-0071",
        "research": "docs/RESEARCH/159-overnight-daytime-tug-of-war.md",
        "spent_trials": 0,
        **run,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=1), encoding="utf-8")
    return result


def run(output: Path = OUT) -> dict[str, Any]:
    cache = {}
    for symbol in cs.universe():
        cached = india_five._cached(symbol)
        if cached.exists():
            cache[symbol] = pickle.loads(cached.read_bytes())["marks"]["overnight"]
    sessions = sorted({d for marks in cache.values() for d in marks if d <= cs.DATA_END})
    momentum, tug, month = stock_ranks(cache)
    index = five.load_index()
    etf = rs.load_days(five.ETF, cache=False)
    index_window = sorted({d.day for d in index} & {d.day for d in etf})
    extremes, tugs = index_signals(index)
    momentum_window = [d for d in sessions if d in momentum and len(momentum[d]) >= sig.MIN_NAMES]
    runs = [
        {
            "hypothesis": "H-0066",
            **sig._deciles(
                "nse_momentum_daytime_reversal",
                momentum,
                [d for d in sessions if not momentum_window or d >= momentum_window[0]],
                top_direction=-1,
            ),
        },
        {
            "hypothesis": "H-0067",
            **sig._deciles("nse_tug_of_war_intensity", tug, sessions, top_direction=1),
        },
        {
            "hypothesis": "H-0068",
            **sig._deciles("nse_month_winners_daytime", month, sessions, top_direction=1),
        },
        {
            "hypothesis": "H-0069",
            **sig._etf_run(
                "nifty_overnight_extreme_niftybees", sig.pcr_trades(etf, extremes), index_window
            ),
        },
        {
            "hypothesis": "H-0070",
            **sig._etf_run("nifty_tug_of_war_niftybees", sig.pcr_trades(etf, tugs), index_window),
        },
    ]
    result = {
        "research": "docs/RESEARCH/159-overnight-daytime-tug-of-war.md",
        "universe": len(cache),
        "index_signal_days": {"H-0069": len(extremes), "H-0070": len(tugs)},
        "spent_trials": 0,
        "runs": runs,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=1), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(prog="tug-of-war")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--daily", action="store_true", help="H-0071: daily bars from 2016")
    args = parser.parse_args()
    if args.daily:
        daily = run_daily(args.output or DAILY_OUT)
        print(
            f"H-0071: {daily['trades']} trades; {daily['per_trade_bps']['gross_mean']} bps gross, "
            f"{daily['per_trade_bps']['net_mean']} net a trade; net Sharpe {daily['net']['sharpe']}"
        )
        return 0
    result = run(args.output or OUT)
    for one in result["runs"]:
        print(
            f"{one['hypothesis']} {one['id']}: {one['trades']} trades; "
            f"{one['per_trade_bps']['gross_mean']} bps gross, "
            f"{one['per_trade_bps']['net_mean']} net a trade; net Sharpe {one['net']['sharpe']}"
        )
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
