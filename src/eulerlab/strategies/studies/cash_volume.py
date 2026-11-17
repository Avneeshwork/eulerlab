"""Five cash rules on intraday persistence, volume and attention (research 157).

Pre-registered as H-0056 to H-0060 before any run; Kite one-minute bars to
2024-11-29; stocks ₹1 lakh a trade, NIFTYBEES ₹10 lakh, 1x, cash-intraday
charges plus 2 bps a side.

- **H-0056 intraday persistence.** Lou, Polk and Skouras (2019): rank stocks
  each morning by their mean 09:20-15:10 return over the previous 20
  sessions; long the top decile and short the bottom, 09:20 to 15:10.
- **H-0057 quiet volume shock.** Gervais, Kaniel and Mingelgrin (2001): at
  10:15, first-hour volume at least 3x its 14-session norm and a move under
  0.5% from the prior close; buy the ten highest ratios at 10:16, sell 15:10.
- **H-0058 attention at +5%.** Seasholes and Wu (2007): the first minute from
  09:30 a stock closes 5% above the prior close; buy the next open, sell 15:10.
- **H-0059 big day split by volume.** Parthasarathy (2019): yesterday moved 4%
  or more close to close; fade it if yesterday's volume was under its
  14-session mean, follow it if at least twice; 09:20 to 15:10.
- **H-0060** the same for a 1.5% Nifty day, traded in NIFTYBEES (fade under
  the mean, follow at or above it).

`make cash-volume` writes `data/derived/cash_volume.json`.
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
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from eulerlab.intraday import cross_section as cs
from eulerlab.intraday import india_papers as ip
from eulerlab.paths import data_path
from eulerlab.strategies.studies import cash_five as five
from eulerlab.strategies.studies import research as rs

OUT = data_path("derived/cash_volume.json")
PARTS = data_path("derived/cash_volume_parts")
BATCH = 40

DAY_START = 5
"""09:20."""
LOOKBACK = 20
MIN_NAMES = 100
NORM_DAYS = 14

FIRST_HOUR = 60
"""09:15-10:14 are minutes 0-59; the entry is the 10:16 open."""
VOLUME_SHOCK = 3.0
QUIET = 0.005

ATTENTION = 0.05
ATTENTION_FROM = 15
"""09:30."""

BIG_STOCK = 0.04
BIG_INDEX = 0.015
LIGHT = 1.0
HEAVY = 2.0


@dataclass(frozen=True)
class Mark:
    """One stock-day: every input the five rules need."""

    persistence: float | None
    day_fill: five.Fill | None
    volume_ratio: float | None
    morning_move: float | None
    shock_fill: five.Fill | None
    attention_fill: five.Fill | None
    big_move: float | None
    big_volume_ratio: float | None


def _fill(
    day: ip.Day, start: int, direction: int = 1, signal: int | None = None
) -> five.Fill | None:
    entry, leave = day.fill_at(start), day.fill_at(cs.EXIT)
    if entry is None or leave is None or entry[0] >= leave[0]:
        return None
    return five.Fill(
        start if signal is None else signal, direction, entry[0], entry[1], leave[0], leave[1]
    )


def attention(day: ip.Day, before: float) -> five.Fill | None:
    level = (1.0 + ATTENTION) * before
    opened = next((o for o in day.open_ if o is not None), None)
    if opened is None or opened >= level:
        return None
    for m in range(ATTENTION_FROM, min(day.last, cs.EXIT)):
        if day.open_[m] is not None and day.close[m] >= level:
            return _fill(day, m + 1, signal=m)
    return None


def extract(_symbol: str, days: Sequence[ip.Day]) -> dict[date, Mark]:
    out: dict[date, Mark] = {}
    returns: list[float | None] = []
    for index, day in enumerate(days):
        today = _fill(day, DAY_START)
        returns.append(today.exit / today.entry - 1.0 if today else None)
        before = cs.previous_close(days, index)
        if before is None or before < five.MIN_PRICE:
            continue
        past = [r for r in returns[max(0, index - LOOKBACK) : index] if r is not None]
        persistence = sum(past) / LOOKBACK if index >= LOOKBACK and len(past) == LOOKBACK else None
        ratio = move = shock = None
        big_move = big_ratio = None
        if index >= NORM_DAYS:
            hours = [sum(d.volume[:FIRST_HOUR]) for d in days[index - NORM_DAYS : index]]
            norm = sum(hours) / NORM_DAYS
            if norm > 0:
                ratio = sum(day.volume[:FIRST_HOUR]) / norm
                move = day.close[FIRST_HOUR - 1] / before - 1.0
                if ratio >= VOLUME_SHOCK and abs(move) < QUIET:
                    shock = _fill(day, FIRST_HOUR + 1)
        if index >= NORM_DAYS + 2:
            yesterday, earlier = days[index - 1], days[index - 2]
            if (day.day - yesterday.day).days <= 7 and (yesterday.day - earlier.day).days <= 7:
                big_move = yesterday.close[yesterday.last] / earlier.close[earlier.last] - 1.0
                daily = [sum(d.volume) for d in days[index - 1 - NORM_DAYS : index - 1]]
                mean = sum(daily) / NORM_DAYS
                big_ratio = sum(yesterday.volume) / mean if mean > 0 else None
        out[day.day] = Mark(
            persistence, today, ratio, move, shock, attention(day, before), big_move, big_ratio
        )
    return out


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


def _by_day(marks: Mapping[str, Mapping[date, Mark]]) -> dict[date, list[tuple[str, Mark]]]:
    out: dict[date, list[tuple[str, Mark]]] = defaultdict(list)
    for symbol, days in marks.items():
        for day, mark in days.items():
            out[day].append((symbol, mark))
    return out


def evaluate_persistence(
    marks: Mapping[str, Mapping[date, Mark]], sessions: Sequence[date]
) -> dict[str, Any]:
    trades, widest = [], 0
    for day, found in _by_day(marks).items():
        ranked = sorted(
            (
                (m.persistence, s, m.day_fill)
                for s, m in found
                if m.persistence is not None and m.day_fill
            ),
            key=lambda item: (item[0], item[1]),
        )
        if len(ranked) < MIN_NAMES:
            continue
        decile = len(ranked) // 10
        widest = max(widest, decile)
        for direction, chosen in ((1, ranked[-decile:]), (-1, ranked[:decile])):
            for _, symbol, fill in chosen:
                trade = five._trade(symbol, day, fill, direction, five.TRADE) if fill else None
                if trade:
                    trades.append(trade)
    return _book(
        "nse_intraday_return_persistence",
        trades,
        sessions,
        five.TRADE * 2 * max(widest, 1),
        book="top decile long, bottom decile short, ₹1 lakh each",
    )


def evaluate_shock(
    marks: Mapping[str, Mapping[date, Mark]], sessions: Sequence[date]
) -> dict[str, Any]:
    trades = []
    for day, found in _by_day(marks).items():
        chosen = sorted(
            ((m.volume_ratio or 0.0, s, m.shock_fill) for s, m in found if m.shock_fill),
            key=lambda item: (-item[0], item[1]),
        )[: five.MAX_OPEN]
        for _, symbol, fill in chosen:
            trade = five._trade(symbol, day, fill, 1, five.TRADE) if fill else None
            if trade:
                trades.append(trade)
    return _book("nse_quiet_volume_shock", trades, sessions, five.TRADE * five.MAX_OPEN)


def evaluate_attention(
    marks: Mapping[str, Mapping[date, Mark]], sessions: Sequence[date]
) -> dict[str, Any]:
    trades = []
    for day, found in _by_day(marks).items():
        chosen = sorted(
            ((m.attention_fill.minute, s, m.attention_fill) for s, m in found if m.attention_fill),
            key=lambda item: (item[0], item[1]),
        )[: five.MAX_OPEN]
        for _, symbol, fill in chosen:
            trade = five._trade(symbol, day, fill, 1, five.TRADE)
            if trade:
                trades.append(trade)
    return _book("nse_attention_five_percent", trades, sessions, five.TRADE * five.MAX_OPEN)


def split_direction(move: float, ratio: float, *, heavy: float, light: float) -> int:
    """-1 fade, +1 follow, as a sign on the trade; 0 for no trade."""
    sign = 1 if move > 0 else -1
    if ratio < light:
        return -sign
    if ratio >= heavy:
        return sign
    return 0


def evaluate_big_days(
    marks: Mapping[str, Mapping[date, Mark]], sessions: Sequence[date]
) -> dict[str, Any]:
    trades = []
    for day, found in _by_day(marks).items():
        chosen = []
        for symbol, m in found:
            if m.big_move is None or m.big_volume_ratio is None or m.day_fill is None:
                continue
            if abs(m.big_move) < BIG_STOCK:
                continue
            direction = split_direction(m.big_move, m.big_volume_ratio, heavy=HEAVY, light=LIGHT)
            if direction:
                chosen.append((-abs(m.big_move), symbol, direction, m.day_fill))
        chosen.sort(key=lambda item: (item[0], item[1]))
        for _, symbol, direction, fill in chosen[: five.MAX_OPEN]:
            trade = five._trade(symbol, day, fill, direction, five.TRADE)
            if trade:
                trades.append(trade)
    return _book("nse_big_day_volume_split", trades, sessions, five.TRADE * five.MAX_OPEN)


def evaluate_index(
    index: Sequence[ip.Day], etf: Sequence[ip.Day], sessions: Sequence[date]
) -> dict[str, Any]:
    closes = {d.day: d.close[d.last] for d in index}
    trades = []
    for i in range(NORM_DAYS + 2, len(etf)):
        day, yesterday, earlier = etf[i], etf[i - 1], etf[i - 2]
        if yesterday.day not in closes or earlier.day not in closes:
            continue
        move = closes[yesterday.day] / closes[earlier.day] - 1.0
        if abs(move) < BIG_INDEX:
            continue
        daily = [sum(d.volume) for d in etf[i - 1 - NORM_DAYS : i - 1]]
        mean = sum(daily) / NORM_DAYS
        if mean <= 0:
            continue
        direction = split_direction(move, sum(yesterday.volume) / mean, heavy=LIGHT, light=LIGHT)
        fill = _fill(day, DAY_START)
        if fill is not None:
            trade = five._trade(five.ETF, day.day, fill, direction, five.ETF_CAPITAL)
            if trade:
                trades.append(trade)
    return _book("nifty_big_day_volume_split_niftybees", trades, sessions, five.ETF_CAPITAL)


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
            "eulerlab.strategies.studies.cash_volume",
            "--part",
            str(part),
        ]
        subprocess.run([*command, "--batch", *batch], check=True)
        print(f"  batch {number + 1}/{len(batches)} done", file=sys.stderr, flush=True)
    marks: dict[str, Any] = {}
    sessions: set[date] = set()
    for number in range(len(batches)):
        loaded = pickle.loads((PARTS / f"{number:03d}.pkl").read_bytes())
        sessions.update(loaded["sessions"])
        marks.update(loaded["marks"])
    window = sorted(d for d in sessions if d <= cs.DATA_END)
    index = five.load_index()
    etf = rs.load_days(five.ETF, cache=False)
    index_window = sorted({d.day for d in index} & {d.day for d in etf})
    runs = [
        {"hypothesis": "H-0056", **evaluate_persistence(marks, window)},
        {"hypothesis": "H-0057", **evaluate_shock(marks, window)},
        {"hypothesis": "H-0058", **evaluate_attention(marks, window)},
        {"hypothesis": "H-0059", **evaluate_big_days(marks, window)},
        {"hypothesis": "H-0060", **evaluate_index(index, etf, index_window)},
    ]
    result = {
        "research": "docs/RESEARCH/157-five-volume-and-attention-rules.md",
        "universe": len(symbols),
        "spent_trials": 0,
        "runs": runs,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=1), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(prog="cash-volume")
    parser.add_argument("--output", type=Path, default=OUT)
    parser.add_argument("--batch", nargs="+", help=argparse.SUPPRESS)
    parser.add_argument("--part", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.batch:
        # Through the module, not `__main__`, so the pickled classes can be read by others.
        importlib.import_module("eulerlab.strategies.studies.cash_volume").extract_batch(
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
