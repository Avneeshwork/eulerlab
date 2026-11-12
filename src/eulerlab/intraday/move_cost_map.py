"""How far NSE stocks move in a few minutes, against what a round trip costs (research 154).

A minute-level scalp can only pay if the move it catches is larger than the
round trip: 12.24 bps for ₹1 lakh of a cash stock intraday with slippage,
14.5 bps on research 112's smaller trades. This
measures, for every stock with Kite minute bars and for NIFTYBEES, the
absolute close-to-close move over 1, 3, 5, 15 and 30 minutes, in each
half-hour of the session, and the share of those moves larger than the cost.
It is descriptive: no rule, no trade, no trial. Window 2021-08-20 to
2024-11-29; no file past the cutoff is opened.

`make move-cost-map` writes `data/derived/move_cost_map.json`.
"""

from __future__ import annotations

import argparse
import json
import pickle
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from eulerlab.intraday import cross_section as cs
from eulerlab.intraday import india_papers as ip
from eulerlab.paths import data_path

OUT = data_path("derived/move_cost_map.json")
PARTS = data_path("derived/move_cost_map_parts")
"""One file per batch of stocks, so a run that dies resumes. Loading minute files
leaks memory a process never gives back (india_five_screen.BATCH), so each batch
is its own process."""
BATCH = 40
HORIZONS = (1, 3, 5, 15, 30)
BUCKET = 30
"""Half-hours after 09:15: bucket 0 is 09:15-09:45, bucket 12 is 15:15-15:30."""
BUCKETS = 13
COST_BPS = 14.5
"""Research 112's average cash-stock round trip with slippage; a ₹1 lakh trade pays 12.24."""
TIERS = ((0, 50, "top 50 by turnover"), (50, 150, "51-150"), (150, 10_000, "the rest"))


@dataclass
class Moves:
    """Running sums for one stock: [horizon][bucket]."""

    count: np.ndarray = field(default_factory=lambda: np.zeros((len(HORIZONS), BUCKETS)))
    total: np.ndarray = field(default_factory=lambda: np.zeros((len(HORIZONS), BUCKETS)))
    beyond: np.ndarray = field(default_factory=lambda: np.zeros((len(HORIZONS), BUCKETS)))
    turnover: list[float] = field(default_factory=list)


def measure(days: Sequence[ip.Day]) -> Moves:
    """Absolute h-minute moves from each traded minute, by half-hour of the start."""
    moves = Moves()
    for day in days:
        close = np.asarray(day.close[: day.last + 1], dtype=float)
        traded = np.array([o is not None for o in day.open_[: day.last + 1]])
        volume = np.asarray(day.volume[: day.last + 1], dtype=float)
        moves.turnover.append(float((close * volume).sum()))
        if close.size < 2 or close.min() < ip.MIN_PRICE:
            continue
        for i, h in enumerate(HORIZONS):
            if close.size <= h:
                continue
            start = np.arange(close.size - h)
            keep = traded[start] & traded[start + h]
            size = np.abs(close[start + h] / close[start] - 1.0) * 10_000
            bucket = np.minimum(start // BUCKET, BUCKETS - 1)
            np.add.at(moves.count[i], bucket[keep], 1)
            np.add.at(moves.total[i], bucket[keep], size[keep])
            np.add.at(moves.beyond[i], bucket[keep], size[keep] > COST_BPS)
    return moves


def summary(per_stock: Mapping[str, Moves]) -> dict[str, Any]:
    """By turnover tier: mean absolute move (bps) and share beyond cost, per horizon and half-hour."""
    ranked = sorted(
        per_stock,
        key=lambda s: -float(np.median(per_stock[s].turnover)) if per_stock[s].turnover else 0.0,
    )
    tiers: dict[str, Any] = {}
    for low, high, name in TIERS:
        chosen = ranked[low:high]
        if not chosen:
            continue
        count = np.sum([per_stock[s].count for s in chosen], axis=0)
        total = np.sum([per_stock[s].total for s in chosen], axis=0)
        beyond = np.sum([per_stock[s].beyond for s in chosen], axis=0)
        with np.errstate(invalid="ignore", divide="ignore"):
            mean = np.where(count > 0, total / count, np.nan)
            share = np.where(count > 0, beyond / count, np.nan)
        tiers[name] = {
            "stocks": len(chosen),
            "mean_abs_bps": {
                str(h): [round(float(x), 1) for x in mean[i]] for i, h in enumerate(HORIZONS)
            },
            "share_beyond_cost": {
                str(h): [round(float(x), 3) for x in share[i]] for i, h in enumerate(HORIZONS)
            },
            "all_day_mean_abs_bps": {
                str(h): round(float(total[i].sum() / count[i].sum()), 1)
                for i, h in enumerate(HORIZONS)
                if count[i].sum()
            },
        }
    return tiers


def measure_batch(symbols: list[str], part: Path) -> None:
    found, sessions = cs.scan(symbols, {"moves": lambda _s, days: measure(days)})
    part.parent.mkdir(parents=True, exist_ok=True)
    tmp = part.with_suffix(".partial")
    tmp.write_bytes(pickle.dumps({"moves": found["moves"], "sessions": sessions}))
    tmp.replace(part)


def run(output: Path = OUT) -> dict[str, Any]:
    symbols = [*cs.universe(), "NIFTYBEES"]
    batches = [symbols[i : i + BATCH] for i in range(0, len(symbols), BATCH)]
    for number, batch in enumerate(batches):
        part = PARTS / f"{number:03d}.pkl"
        if part.exists():
            continue
        command = [sys.executable, "-m", "eulerlab.intraday.move_cost_map", "--part", str(part)]
        subprocess.run([*command, "--batch", *batch], check=True)
        print(f"  batch {number + 1}/{len(batches)} done", file=sys.stderr, flush=True)
    moves: dict[str, Moves] = {}
    sessions: set[Any] = set()
    for number in range(len(batches)):
        loaded = pickle.loads((PARTS / f"{number:03d}.pkl").read_bytes())
        moves.update(loaded["moves"])
        sessions.update(loaded["sessions"])
    ordered = sorted(sessions)
    etf = moves.pop("NIFTYBEES", None)
    result = {
        "research": "docs/RESEARCH/154-minute-scalping-india.md",
        "window": [ordered[0].isoformat(), ordered[-1].isoformat()] if ordered else [],
        "cost_bps": COST_BPS,
        "horizons_minutes": list(HORIZONS),
        "buckets": "half-hours from 09:15; the last is 15:15-15:30",
        "stocks": len(moves),
        "tiers": summary(moves),
        "niftybees": summary({"NIFTYBEES": etf}) if etf else {},
        "spent_trials": 0,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=1), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(prog="move-cost-map")
    parser.add_argument("--output", type=Path, default=OUT)
    parser.add_argument("--batch", nargs="+", help=argparse.SUPPRESS)
    parser.add_argument("--part", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.batch:
        measure_batch(args.batch, args.part)
        return 0
    result = run(args.output)
    for name, tier in result["tiers"].items():
        print(f"{name} ({tier['stocks']} stocks): mean |move| bps {tier['all_day_mean_abs_bps']}")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
