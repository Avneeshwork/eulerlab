"""Five more minute-level cash rules: bursts and calendar days (research 156).

Pre-registered as H-0051 to H-0055 before any run; Kite one-minute bars to
2024-11-29; stocks ₹1 lakh a trade, NIFTYBEES ₹10 lakh, 1x, cash-intraday
charges plus 2 bps a side.

- **H-0051 drift burst, stocks.** Christensen, Oomen and Renò (2022): 09:45 to
  14:10, a close 3% or more below the highest close of the previous 30
  minutes, on 30-minute volume at least 3x the 14-session norm: buy the next
  open, sell at 15:10.
- **H-0052 pre-holiday, NIFTYBEES.** The session before a weekday holiday
  (A-110): long 09:20 to 15:10.
- **H-0053 turn of the month, NIFTYBEES.** McConnell and Xu (2008): the last
  session of a month and the first three of the next, long 09:20 to 15:10.
- **H-0054 results day, stocks.** Barber et al. (2013): a stock whose results
  reach NSE that evening, 15:30 or later (A-111), long 09:20 to 15:10. Read
  from the india-five cache, whose overnight marks hold every stock-day's
  09:20 and 15:10 fills.
- **H-0055 drift burst, Nifty.** The Nifty 1% or more below its 30-minute
  high, 09:45 to 14:10: buy NIFTYBEES at the next open, sell at 15:10.

`make cash-events` writes `data/derived/cash_events.json`.
"""

from __future__ import annotations

import argparse
import importlib
import json
import pickle
import subprocess
import sys
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from eulerlab.ingest import nse_earnings_announcements as announcements
from eulerlab.intraday import cash_five_screen as five
from eulerlab.intraday import cross_section as cs
from eulerlab.intraday import india_five_screen as india_five
from eulerlab.intraday import india_papers as ip
from eulerlab.intraday import research_screen as rs
from eulerlab.paths import data_path

OUT = data_path("derived/cash_events.json")
PARTS = data_path("derived/cash_events_parts")
BATCH = 40

BURST_FROM, BURST_LAST = 30, 295
"""09:45 to 14:10."""
BURST_WINDOW = 30
STOCK_BURST = 0.03
INDEX_BURST = 0.01
VOLUME_MULTIPLE = 3.0
NORM_DAYS = 14
DAY_START = 5
"""09:20."""
TURN_FIRST_DAYS = 3
CLOSE = time(15, 30)


def burst(day: ip.Day, depth: float, volume_norm: float | None = None) -> five.Fill | None:
    """The first close `depth` below the previous 30 minutes' highest close, bought."""
    for m in range(BURST_FROM, min(BURST_LAST, day.last) + 1):
        if day.open_[m] is None:
            continue
        top = max(day.close[m - BURST_WINDOW : m])
        if day.close[m] > (1.0 - depth) * top:
            continue
        if volume_norm is not None:
            recent = sum(day.volume[m - BURST_WINDOW + 1 : m + 1])
            if recent < VOLUME_MULTIPLE * volume_norm:
                continue
        entry, leave = day.fill_at(m + 1), day.fill_at(cs.EXIT)
        if entry is None or leave is None or entry[0] >= leave[0]:
            return None
        return five.Fill(m, 1, entry[0], entry[1], leave[0], leave[1])
    return None


def extract(_symbol: str, days: Sequence[ip.Day]) -> dict[date, five.Fill]:
    """H-0051: each stock-day's first down-burst on heavy volume."""
    out: dict[date, five.Fill] = {}
    for index, day in enumerate(days):
        before = cs.previous_close(days, index)
        if before is None or before < five.MIN_PRICE or index < NORM_DAYS:
            continue
        daily = [sum(d.volume) for d in days[index - NORM_DAYS : index]]
        norm = sum(daily) / NORM_DAYS / ip.MINUTES * BURST_WINDOW
        if norm <= 0:
            continue
        found = burst(day, STOCK_BURST, norm)
        if found is not None:
            out[day.day] = found
    return out


def pre_holiday_days(sessions: Sequence[date]) -> list[date]:
    """Sessions whose next weekday is not a session, inside the calendar's span."""
    known = set(sessions)
    last = max(sessions)
    out = []
    for day in sorted(sessions):
        nxt = day + timedelta(days=1)
        while nxt.weekday() >= 5:
            nxt += timedelta(days=1)
        if nxt <= last and nxt not in known:
            out.append(day)
    return out


def turn_of_month_days(sessions: Sequence[date]) -> list[date]:
    """The last session of each month and the first three of the next."""
    by_month: dict[tuple[int, int], list[date]] = defaultdict(list)
    for day in sorted(sessions):
        by_month[(day.year, day.month)].append(day)
    months = sorted(by_month)
    out: set[date] = set()
    for i, month in enumerate(months):
        if i > 0:
            out.update(by_month[month][:TURN_FIRST_DAYS])
        if i < len(months) - 1:
            out.add(by_month[month][-1])
    return sorted(out)


def results_evenings(
    rows: Sequence[Mapping[str, Any]], sessions: Sequence[date]
) -> dict[str, set[date]]:
    """{symbol: sessions whose evening (15:30 or later) brought its results}."""
    trading = set(sessions)
    out: dict[str, set[date]] = defaultdict(set)
    for row in rows:
        known = datetime.fromisoformat(str(row["knowledge_time"]))
        day = known.date()
        if day not in trading or known.time() < CLOSE:
            continue
        if any(start <= day <= end for start, end in announcements.INCOMPLETE):
            continue
        out[str(row["symbol"])].add(day)
    return dict(out)


def day_trade(day: ip.Day) -> five.Fill | None:
    entry, leave = day.fill_at(DAY_START), day.fill_at(cs.EXIT)
    if entry is None or leave is None or entry[0] >= leave[0]:
        return None
    return five.Fill(DAY_START, 1, entry[0], entry[1], leave[0], leave[1])


# --- evaluation ----------------------------------------------------------------------


def _book(
    run_id: str, trades: list[cs.Trade], sessions: Sequence[date], capital: float, **params: Any
) -> dict[str, Any]:
    run = cs.report(
        run_id,
        trades,
        sessions,
        params={"slippage_bps_per_side": cs.SLIPPAGE_BPS, **params},
        capital=capital,
    )
    return five._halves(run)


def evaluate_bursts(
    marks: Mapping[str, Mapping[date, five.Fill]], sessions: Sequence[date]
) -> dict[str, Any]:
    by_day: dict[date, list[tuple[int, str, five.Fill]]] = defaultdict(list)
    for symbol, days in marks.items():
        for day, fill in days.items():
            by_day[day].append((fill.minute, symbol, fill))
    trades = []
    for day, found in by_day.items():
        found.sort(key=lambda item: (item[0], item[1]))
        for _, symbol, fill in found[: five.MAX_OPEN]:
            trade = five._trade(symbol, day, fill, 1, five.TRADE)
            if trade:
                trades.append(trade)
    return _book("nse_drift_burst_reversal", trades, sessions, five.TRADE * five.MAX_OPEN)


def evaluate_etf_days(
    run_id: str, etf: Sequence[ip.Day], chosen: set[date], sessions: Sequence[date]
) -> dict[str, Any]:
    trades = []
    for day in etf:
        if day.day not in chosen:
            continue
        fill = day_trade(day)
        if fill is not None:
            trade = five._trade(five.ETF, day.day, fill, 1, five.ETF_CAPITAL)
            if trade:
                trades.append(trade)
    run = _book(run_id, trades, sessions, five.ETF_CAPITAL)
    run["event_days"] = len(chosen & set(sessions))
    return run


def evaluate_results(
    marks: Mapping[str, Mapping[date, Any]],
    evenings: Mapping[str, set[date]],
    sessions: Sequence[date],
) -> dict[str, Any]:
    by_day: dict[date, list[tuple[str, Any]]] = defaultdict(list)
    for symbol, days in evenings.items():
        mine = marks.get(symbol, {})
        for day in days:
            mark = mine.get(day)
            if mark is not None:
                by_day[day].append((symbol, mark))
    trades = []
    for day, found in by_day.items():
        found.sort(key=lambda item: item[0])
        for symbol, mark in found[: five.MAX_OPEN]:
            fill = five.Fill(
                DAY_START, 1, mark.entry_minute, mark.entry, mark.exit_minute, mark.exit
            )
            trade = five._trade(symbol, day, fill, 1, five.TRADE)
            if trade:
                trades.append(trade)
    run = _book("nse_results_day_premium", trades, sessions, five.TRADE * five.MAX_OPEN)
    run["event_days"] = len(by_day)
    return run


def evaluate_index_burst(
    index: Sequence[ip.Day], etf: Sequence[ip.Day], sessions: Sequence[date]
) -> dict[str, Any]:
    by_day = {d.day: d for d in etf}
    trades = []
    for day in index:
        traded = by_day.get(day.day)
        if traded is None:
            continue
        signal = burst(day, INDEX_BURST)
        if signal is None:
            continue
        entry, leave = traded.fill_at(signal.minute + 1), traded.fill_at(cs.EXIT)
        if entry is None or leave is None or entry[0] >= leave[0]:
            continue
        fill = five.Fill(signal.minute, 1, entry[0], entry[1], leave[0], leave[1])
        trade = five._trade(five.ETF, day.day, fill, 1, five.ETF_CAPITAL)
        if trade:
            trades.append(trade)
    return _book("nifty_drift_burst_niftybees", trades, sessions, five.ETF_CAPITAL)


# --- running -------------------------------------------------------------------------


def extract_batch(symbols: list[str], part: Path) -> None:
    found, sessions = cs.scan(symbols, {"marks": extract})
    part.parent.mkdir(parents=True, exist_ok=True)
    tmp = part.with_suffix(".partial")
    tmp.write_bytes(pickle.dumps({"marks": found["marks"], "sessions": sessions}))
    tmp.replace(part)


def run(output: Path = OUT) -> dict[str, Any]:
    symbols = cs.universe()
    batches = [symbols[i : i + BATCH] for i in range(0, len(symbols), BATCH)]
    for number, batch in enumerate(batches):
        part = PARTS / f"{number:03d}.pkl"
        if part.exists():
            continue
        command = [
            sys.executable,
            "-m",
            "eulerlab.intraday.cash_events_screen",
            "--part",
            str(part),
        ]
        subprocess.run([*command, "--batch", *batch], check=True)
        print(f"  batch {number + 1}/{len(batches)} done", file=sys.stderr, flush=True)
    bursts: dict[str, Any] = {}
    sessions: set[date] = set()
    for number in range(len(batches)):
        loaded = pickle.loads((PARTS / f"{number:03d}.pkl").read_bytes())
        sessions.update(loaded["sessions"])
        bursts.update(loaded["marks"])
    window = sorted(d for d in sessions if d <= cs.DATA_END)
    overnight: dict[str, Any] = {}
    for symbol in symbols:
        cached = india_five._cached(symbol)
        if cached.exists():
            overnight[symbol] = pickle.loads(cached.read_bytes())["marks"]["overnight"]
    index = five.load_index()
    etf = rs.load_days(five.ETF, cache=False)
    etf_window = sorted(d.day for d in etf if d.day <= cs.DATA_END)
    index_window = sorted({d.day for d in index} & set(etf_window))
    holidays = set(pre_holiday_days(window))
    turns = set(turn_of_month_days(window))
    evenings = results_evenings(announcements.load(), window)
    runs = [
        {"hypothesis": "H-0051", **evaluate_bursts(bursts, window)},
        {
            "hypothesis": "H-0052",
            **evaluate_etf_days("niftybees_pre_holiday", etf, holidays, etf_window),
        },
        {
            "hypothesis": "H-0053",
            **evaluate_etf_days("niftybees_turn_of_month", etf, turns, etf_window),
        },
        {"hypothesis": "H-0054", **evaluate_results(overnight, evenings, window)},
        {"hypothesis": "H-0055", **evaluate_index_burst(index, etf, index_window)},
    ]
    result = {
        "research": "docs/RESEARCH/156-five-more-cash-intraday-rules.md",
        "universe": len(symbols),
        "pre_holiday_days": sorted(d.isoformat() for d in holidays),
        "spent_trials": 0,
        "runs": runs,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=1), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(prog="cash-events")
    parser.add_argument("--output", type=Path, default=OUT)
    parser.add_argument("--batch", nargs="+", help=argparse.SUPPRESS)
    parser.add_argument("--part", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.batch:
        # Through the module, not `__main__`, so the pickled classes can be read by others.
        importlib.import_module("eulerlab.intraday.cash_events_screen").extract_batch(
            args.batch, args.part
        )
        return 0
    result = run(args.output)
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
