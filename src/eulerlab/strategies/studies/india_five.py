"""Research 112: five Indian intraday rules over every F&O stock, in one pass.

`make india-five-intraday` writes `data/derived/india_five_intraday.json`; the
five strategy cards in `strategies/studies.py` read their run from it. Each
rule is fixed before it is run and none is tuned on the result. Minute files
after the research window's end are never opened.
"""

from __future__ import annotations

import argparse
import json
import pickle
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

from eulerlab.ingest import nse_earnings_announcements as announcements
from eulerlab.intraday import cross_section as cs
from eulerlab.paths import data_path
from eulerlab.strategies.studies import delivery_spike as delivery
from eulerlab.strategies.studies import earnings_reaction as earnings
from eulerlab.strategies.studies import expiry_pinning as pinning
from eulerlab.strategies.studies import nr7_breakout as nr7
from eulerlab.strategies.studies import overnight_reversal as overnight

OUT = data_path("derived/india_five_intraday.json")
START = date(2021, 8, 19)
"""The first day of the minute archive."""


CACHE = data_path("derived/india_five_cache")
"""One file per stock: what each screen extracted from it, and its sessions.
Written as each stock finishes, so a run that dies resumes where it stopped
and downloads nothing twice. Delete the folder after changing an extractor."""

BATCH = 40
"""Stocks per child process. One process over all 416 was killed for memory on
2026-10-17 (exit 137) after the last stock loaded: loading minute files left
1.25 GB resident per 20 stocks that the process never gave back. A fresh
process per batch hands it back."""

SCREENS = ("overnight", "pinning", "earnings", "nr7", "delivery")


def _cached(symbol: str) -> Path:
    return CACHE / f"{symbol}.pkl"


def extract_batch(symbols: list[str], *, root: Path | None = None) -> None:
    """Load each stock once, run every screen's extractor, save the result."""
    pins = pinning.context(symbols, START, cs.DATA_END)
    known = earnings.events(announcements.load())
    held = delivery.context(symbols, date(2021, 6, 1), cs.DATA_END)
    extractors = {
        "overnight": overnight.extract,
        "pinning": pinning.extractor(pins),
        "earnings": earnings.extractor(known),
        "nr7": nr7.extract,
        "delivery": delivery.extractor(held),
    }
    marks, sessions = cs.scan(symbols, extractors, root=root)
    CACHE.mkdir(parents=True, exist_ok=True)
    for symbol in symbols:
        payload = {
            "marks": {name: per[symbol] for name, per in marks.items()},
            # The batch's sessions: the union over all stocks is what evaluation needs.
            "sessions": sessions,
        }
        part = _cached(symbol).with_suffix(".partial")
        part.write_bytes(pickle.dumps(payload))
        part.replace(_cached(symbol))


def _extract_all(symbols: list[str], root: Path | None) -> None:
    """Every stock not yet cached, `BATCH` at a time, each batch its own process."""
    todo = [s for s in symbols if not _cached(s).exists()]
    started = time.monotonic()
    print(f"  {len(symbols) - len(todo)} of {len(symbols)} stocks already done", file=sys.stderr)
    for first in range(0, len(todo), BATCH):
        batch = todo[first : first + BATCH]
        command = [
            sys.executable,
            "-m",
            "eulerlab.strategies.studies.india_five",
            "--batch",
            *batch,
        ]
        if root is not None:
            command += ["--root", str(root)]
        finished = subprocess.run(command, check=False)
        done = len(symbols) - sum(1 for s in symbols if not _cached(s).exists())
        print(
            f"  batch ending {batch[-1]}: exit {finished.returncode}; "
            f"{done}/{len(symbols)} stocks done, {time.monotonic() - started:.0f}s",
            file=sys.stderr,
        )
    missing = [s for s in symbols if not _cached(s).exists()]
    if missing:
        # Said, never dropped: a stock left out would change every screen's result.
        msg = f"{len(missing)} stocks failed to load ({', '.join(missing[:10])}…); run again to retry them"
        raise RuntimeError(msg)


def run_all(
    *, limit: int = 0, root: Path | None = None, output: Path = OUT, cached_only: bool = False
) -> dict[str, Any]:
    """Extract every stock in batches, then evaluate the five screens one by one.

    Each screen's result is written as soon as it is done, so one that fails
    leaves the others' results, and its error, in the output.
    """
    symbols = cs.universe()
    if limit:
        symbols = symbols[:limit]
    left_out: list[str] = []
    if cached_only:
        # The stocks already extracted, nothing downloaded. Their absence is
        # recorded in the output: a screen on fewer stocks is a different run.
        left_out = [s for s in symbols if not _cached(s).exists()]
        symbols = [s for s in symbols if _cached(s).exists()]
    else:
        _extract_all(symbols, root)

    marks: dict[str, dict[str, Any]] = {name: {} for name in SCREENS}
    sessions: set[date] = set()
    for symbol in symbols:
        loaded = pickle.loads(_cached(symbol).read_bytes())
        sessions.update(loaded["sessions"])
        for name in SCREENS:
            marks[name][symbol] = loaded["marks"][name]
    window = sorted(day for day in sessions if day <= cs.DATA_END)
    known = earnings.events(announcements.load())
    result: dict[str, Any] = {
        "source": "Kite NSE one-minute OHLCV for every stock with minute files; "
        "files crossing the research window's end are excluded",
        "research": "docs/RESEARCH/112-five-indian-intraday-rules-on-fo-stocks.md",
        "universe": len(symbols),
        "left_out": left_out,
        "survivorship": "stocks with minute files today; names that left F&O before "
        "2021 are absent, and so are their losses",
        "window": [window[0].isoformat(), window[-1].isoformat()] if window else [],
        "expiries_with_open_interest": len(pinning.context(symbols, START, cs.DATA_END)),
        "earnings_events_in_hours": sum(len(v) for v in known.values()),
        "spent_trials": 0,
        "runs": [],
        "failed": [],
    }
    evaluators: dict[str, Callable[[Any, list[date]], dict[str, Any]]] = {
        "overnight": overnight.evaluate,
        "pinning": pinning.evaluate,
        "earnings": earnings.evaluate,
        "nr7": nr7.evaluate,
        "delivery": delivery.evaluate,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    for name in SCREENS:
        try:
            run = evaluators[name](marks[name], window)
        except Exception as exc:  # one screen's fault must not lose the other four
            result["failed"].append({"screen": name, "error": f"{type(exc).__name__}: {exc}"})
            print(f"{name}: FAILED {type(exc).__name__}: {exc}", file=sys.stderr)
        else:
            result["runs"].append(run)
            _print(run)
        output.write_text(json.dumps(result, indent=1), encoding="utf-8")
    return result


def _print(run: dict[str, Any]) -> None:
    gross, net = run["gross"], run["net"]
    print(
        f"{run['id']}: {run['trades']} trades; gross {gross['total_return']:+.2%} "
        f"(Sharpe {gross['sharpe']}), net {net['total_return']:+.2%} "
        f"(Sharpe {net['sharpe']}); {run['per_trade_bps']['gross_mean']} bps gross a trade",
        flush=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(prog="india-five-intraday")
    parser.add_argument("--limit", type=int, default=0, help="first N symbols only (a smoke run)")
    parser.add_argument("--output", type=Path, default=OUT)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--batch", nargs="+", help=argparse.SUPPRESS)
    parser.add_argument(
        "--cached-only",
        action="store_true",
        help="evaluate the stocks already extracted; download nothing",
    )
    args = parser.parse_args()
    if args.batch:
        extract_batch(args.batch, root=args.root)
        return 0
    result = run_all(
        limit=args.limit, root=args.root, output=args.output, cached_only=args.cached_only
    )
    if result["left_out"]:
        print(f"{len(result['left_out'])} stocks left out: not yet extracted", file=sys.stderr)
    print(f"wrote {args.output}; {len(result['runs'])} of {len(SCREENS)} screens ran")
    return 1 if result["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
