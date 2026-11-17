"""Minute-level scalps on NSE stocks (research 154, H-0042 and H-0043).

Two rules, fixed before they were run, on Kite one-minute bars to 2024-11-29.
Every trade enters at the next minute's open, leaves 15 minutes later (or at
15:10, whichever is first) and pays cash-intraday charges plus 2 bps a side.

- **H-0042 shock fade (stocks).** A one-minute close-to-close move of 1% or
  more, on volume at least five times the mean of the 30 minutes before it,
  from 09:45: trade against it. Grant, Wolf and Yu (2005) and Fung, Mok and Lam
  (2000) find large moves in index futures reverse within the day.
- **H-0043 round-number cross (stocks).** The first one-minute close from 09:20
  that crosses a round level (multiples of ₹100 for a stock priced
  ₹1,000-10,000 at the prior close, ₹10 for ₹100-1,000): trade in the
  crossing's direction. Osler (2003) finds stop orders cluster just past round
  numbers, so a crossing runs on.

No index rule: NIFTYBEES moves 8.3 bps in 15 minutes on average
(`move_cost_map`) against a 7.99 bps round trip at ₹10 lakh, so a call would
have to be right about 98% of the time. ₹1 lakh a trade, at most one trade a stock a day and ten a day,
earliest signal first. `make minute-scalps` writes
`data/derived/minute_scalps.json`.
"""

from __future__ import annotations

import argparse
import json
import math
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

OUT = data_path("derived/minute_scalps.json")
PARTS = data_path("derived/minute_scalps_parts")
BATCH = 40
HOLD = 15
MAX_OPEN = 10

SHOCK = 0.01
VOLUME_MULTIPLE = 5.0
LOOKBACK = 30
SHOCK_FROM = 30
"""09:45: the 30 minutes before a shock must be in the session."""

CROSS_FROM = 5
"""09:20: a level crossed in the opening gap is not a crossing."""


@dataclass(frozen=True)
class Signal:
    minute: int
    direction: int
    entry_minute: int
    entry: float
    exit_minute: int
    exit: float


def _trade(day: ip.Day, minute: int, direction: int) -> Signal | None:
    entry = day.fill_at(minute + 1)
    if entry is None or entry[0] >= cs.EXIT:
        return None
    leave = day.fill_at(min(entry[0] + HOLD, cs.EXIT))
    if leave is None or leave[0] <= entry[0]:
        return None
    return Signal(minute, direction, entry[0], entry[1], leave[0], leave[1])


def shock(day: ip.Day) -> Signal | None:
    """H-0042: the first one-minute shock on heavy volume, faded."""
    for m in range(SHOCK_FROM, min(day.last, cs.EXIT)):
        if day.open_[m] is None or day.open_[m - 1] is None:
            continue
        move = day.close[m] / day.close[m - 1] - 1.0
        if abs(move) < SHOCK:
            continue
        before = day.volume[m - LOOKBACK : m]
        mean = sum(before) / LOOKBACK
        if mean > 0 and day.volume[m] >= VOLUME_MULTIPLE * mean:
            return _trade(day, m, -1 if move > 0 else 1)
    return None


def step_for(price: float) -> float | None:
    """The round level for a stock at `price`: ₹100 for 1,000-10,000, ₹10 for 100-1,000."""
    if 1_000 <= price < 10_000:
        return 100.0
    if 100 <= price < 1_000:
        return 10.0
    return None


def first_cross(day: ip.Day, step: float) -> tuple[int, int] | None:
    """(minute, direction) of the first close from 09:20 on the other side of a multiple of `step`."""
    for m in range(CROSS_FROM, min(day.last, cs.EXIT)):
        if day.open_[m] is None:
            continue
        before, now = day.close[m - 1], day.close[m]
        if math.floor(before / step) != math.floor(now / step):
            return m, 1 if now > before else -1
    return None


def stock_extract(_symbol: str, days: Sequence[ip.Day]) -> dict[str, dict[date, Signal]]:
    out: dict[str, dict[date, Signal]] = {"shock": {}, "cross": {}}
    for index, day in enumerate(days):
        before = cs.previous_close(days, index)
        if before is None or before < cs.MIN_PRICE:
            continue
        found = shock(day)
        if found is not None:
            out["shock"][day.day] = found
        step = step_for(before)
        crossed = first_cross(day, step) if step else None
        if crossed is not None:
            signal = _trade(day, *crossed)
            if signal is not None:
                out["cross"][day.day] = signal
    return out


def evaluate_stocks(
    run_id: str, marks: Mapping[str, Mapping[date, Signal]], sessions: Sequence[date]
) -> dict[str, Any]:
    by_day: dict[date, list[tuple[int, str, Signal]]] = defaultdict(list)
    for symbol, days in marks.items():
        for day, signal in days.items():
            by_day[day].append((signal.minute, symbol, signal))
    trades = []
    each = cs.CAPITAL / MAX_OPEN
    for day, found in by_day.items():
        found.sort(key=lambda item: (item[0], item[1]))
        for _, symbol, signal in found[:MAX_OPEN]:
            quantity = cs.sized(each, signal.entry)
            if quantity:
                trades.append(_as_trade(symbol, day, signal, quantity))
    return _with_halves(
        cs.report(run_id, trades, sessions, params=_params(f"₹{each:,.0f} a trade, ten a day"))
    )


def _as_trade(symbol: str, day: date, signal: Signal, quantity: int) -> cs.Trade:
    return cs.Trade(
        symbol,
        day,
        signal.direction,
        quantity,
        signal.entry_minute,
        signal.entry,
        signal.exit_minute,
        signal.exit,
        "time_exit",
    )


def _params(sizing: str) -> dict[str, Any]:
    return {
        "entry": "next minute's open",
        "exit": f"{HOLD} minutes later or 15:10",
        "sizing": sizing,
        "slippage_bps_per_side": cs.SLIPPAGE_BPS,
    }


def _with_halves(run: dict[str, Any]) -> dict[str, Any]:
    """Net Sharpe and return before 2024 and in 2024, from the daily series."""
    from eulerlab.intraday import screen_common as sc

    daily = [(date.fromisoformat(d), r) for d, r in run["daily"]]
    run["net_halves"] = {
        "before_2024": sc.daily_stats([r for d, r in daily if d.year < 2024]),
        "2024": sc.daily_stats([r for d, r in daily if d.year >= 2024]),
    }
    run.pop("daily", None)
    return run


def measure_batch(symbols: list[str], part: Path) -> None:
    found, sessions = cs.scan(symbols, {"marks": stock_extract})
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
            "eulerlab.strategies.studies.minute_scalp",
            "--part",
            str(part),
        ]
        subprocess.run([*command, "--batch", *batch], check=True)
        print(f"  batch {number + 1}/{len(batches)} done", file=sys.stderr, flush=True)
    marks: dict[str, dict[str, dict[date, Signal]]] = {"shock": {}, "cross": {}}
    sessions: set[date] = set()
    for number in range(len(batches)):
        loaded = pickle.loads((PARTS / f"{number:03d}.pkl").read_bytes())
        sessions.update(loaded["sessions"])
        for symbol, found in loaded["marks"].items():
            for name in marks:
                marks[name][symbol] = found[name]
    window = sorted(d for d in sessions if d <= cs.DATA_END)
    result = {
        "research": "docs/RESEARCH/154-minute-scalping-india.md",
        "universe": len(symbols),
        "spent_trials": 0,
        "runs": [
            {
                "hypothesis": "H-0042",
                **evaluate_stocks("nse_minute_shock_fade", marks["shock"], window),
            },
            {
                "hypothesis": "H-0043",
                **evaluate_stocks("nse_round_number_cross", marks["cross"], window),
            },
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=1), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(prog="minute-scalps")
    parser.add_argument("--output", type=Path, default=OUT)
    parser.add_argument("--batch", nargs="+", help=argparse.SUPPRESS)
    parser.add_argument("--part", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.batch:
        measure_batch(args.batch, args.part)
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
