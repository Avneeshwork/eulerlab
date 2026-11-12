"""`make india-intraday` — run research 076's five rules and report.

The three index rules run on NIFTYBEES. The two stock rules run on the
`UNIVERSE_SIZE` largest companies that have minute history, chosen by today's
market value: a list fixed with hindsight, which flatters any long-only
result and is stated in the output.

Each rule is run gross, and after NSE charges plus slippage,
on the whole history and on each side of 2024. Writes
`data/derived/india_intraday_papers.json`.

Screening runs of published settings: no trial is recorded in the ledger.
"""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path
from typing import Any

from eulerlab.intraday import india_papers as ip
from eulerlab.intraday import session_papers as sp
from eulerlab.intraday.session_papers_run import official_closes
from eulerlab.paths import data_path

OUT = data_path("derived/india_intraday_papers.json")
INDEX = "NIFTYBEES"
SPLIT = date(2024, 1, 1)
UNIVERSE_SIZE = 100
ORB_SIZES = (5, 15, 30)
ORB_SURGES = (1.2, 1.5)
ORB_HOLDS = (2, 3, 5)
"""Every setting the abstract of Wang and Gangwar lists: 18 in all."""

Build = Callable[[sp.CostFn, float], sp.Result]


def universe(size: int = UNIVERSE_SIZE, root: Path = ip.MINUTE_ROOT) -> list[str]:
    """The largest companies by market value that have a minute folder."""
    from eulerlab.features import company as digest

    held = {p.name for p in root.iterdir() if p.is_dir()}
    ranked = sorted(
        (c for c in digest.load_digest().values() if c.symbol in held and c.market_cap),
        key=lambda c: (-(c.market_cap or 0), c.symbol),
    )
    return [c.symbol for c in ranked[:size]]


def measured(build: Build, cost: sp.CostFn, slippage: float) -> dict[str, Any]:
    """One rule gross and net, whole and split at 2024."""
    gross = build(sp.no_cost, 0.0)
    net = build(cost, slippage)
    return {
        "gross": gross.stats(),
        "gross_before_2024": gross.stats(end=SPLIT),
        "gross_from_2024": gross.stats(start=SPLIT),
        "net": net.stats(),
        "net_before_2024": net.stats(end=SPLIT),
        "net_from_2024": net.stats(start=SPLIT),
        "skipped": len(net.skipped),
        "daily": [[d.isoformat(), round(r, 6)] for d, r in net.days],
    }


def index_rules(days: Sequence[ip.Day], official: dict[date, float]) -> list[dict[str, Any]]:
    def late(window_end: int) -> Build:
        return lambda cost, slip: ip.late_orb(
            days, window_end=window_end, cost=cost, slippage_bps=slip
        )

    rules: list[tuple[str, str, Build]] = [
        ("rao-2026", "range 09:15-10:15, 3-minute close, stop at the range", late(60)),
        ("rao-2026", "range 09:15-11:15, 3-minute close, stop at the range", late(120)),
        (
            "doraigari-2026",
            "range 09:15-09:45, stop at the range, 2R target, out 14:30",
            lambda cost, slip: ip.orb_two_r(days, cost=cost, slippage_bps=slip),
        ),
        (
            "indian-intraday-momentum-2024",
            "previous close to 15:00 decides 15:00-15:24",
            lambda cost, slip: ip.rest_of_day(days, official, cost=cost, slippage_bps=slip),
        ),
    ]
    return [
        {
            "source": source,
            "rule": rule,
            "instrument": INDEX,
            **measured(build, sp.nse_intraday_cost, sp.SLIPPAGE_BPS),
        }
        for source, rule, build in rules
    ]


FETCH_THREADS = 8


def fetch_missing(symbols: Sequence[str]) -> int:
    """Download every minute file of `symbols` that is not on this machine.

    One at a time takes 1.3 s a file and there are about sixty a stock. The
    files are landed as `landing_reader.read` lands them, so a second run
    downloads nothing.
    """
    from concurrent.futures import ThreadPoolExecutor

    from eulerlab.ingest import landing_reader

    missing = [
        path
        for symbol in symbols
        for path in ip.archive_files(symbol)
        if not landing_reader.is_local(path)
    ]
    if missing:
        print(f"fetching {len(missing):,} minute files from the bucket", flush=True)
        with ThreadPoolExecutor(FETCH_THREADS) as pool:
            for done, _ in enumerate(pool.map(landing_reader.read, missing), start=1):
                if done % 500 == 0:
                    print(f"  {done:,} of {len(missing):,}", flush=True)
    return len(missing)


def _pooled(
    rule: str,
    calendar: Sequence[date],
    signals: dict[date, dict[str, ip.Signal]],
    slots: int,
) -> Build:
    def build(cost: sp.CostFn, slip: float) -> sp.Result:
        return ip.portfolio(rule, calendar, signals, slots=slots, cost=cost, slippage_bps=slip)

    return build


def stock_rules(symbols: Sequence[str]) -> list[dict[str, Any]]:
    """The two stock rules, reading one stock at a time."""
    fetch_missing(symbols)
    orb: dict[tuple[int, float, int], dict[date, dict[str, ip.Signal]]] = {
        (size, surge, hold): {} for size in ORB_SIZES for surge in ORB_SURGES for hold in ORB_HOLDS
    }
    marks: dict[str, dict[date, ip.Marks]] = {}
    calendar: set[date] = set()
    started = time.monotonic()
    for number, symbol in enumerate(symbols, start=1):
        days = ip.load(symbol)
        calendar.update(d.day for d in days)
        marks[symbol] = ip.reversal_marks(days)
        for (size, surge, hold), found in orb.items():
            signals = ip.orb_volume_signals(days, size=size, surge=surge, hold=hold)
            for day, signal in signals.items():
                found.setdefault(day, {})[symbol] = signal
        if number % 10 == 0:
            print(
                f"  read {number} of {len(symbols)} stocks, {time.monotonic() - started:.0f}s",
                flush=True,
            )
    ordered = sorted(calendar)

    out: list[dict[str, Any]] = []
    for (size, surge, hold), found in orb.items():
        rule = f"{size}-minute range, volume {surge}x, hold {hold} bars"
        out.append(
            {
                "source": "wang-gangwar-2025",
                "rule": rule,
                "instrument": f"{len(symbols)} largest stocks, equal slots",
                **measured(
                    _pooled(rule, ordered, found, len(symbols)),
                    ip.stock_cost,
                    ip.STOCK_SLIPPAGE_BPS,
                ),
            }
        )
    for event in ip.REVERSAL_EVENTS:
        for hold in ip.REVERSAL_HOLDS:
            picked = ip.extreme_reversal_signals(marks, event=event, hold_ticks=hold)
            rule = f"fade 3 up and 3 down at the {event}, hold {hold * ip.TICK} minutes"
            out.append(
                {
                    "source": "tripathi-aggarwal-2015",
                    "rule": rule,
                    "instrument": f"{len(symbols)} largest stocks, 6 slots",
                    **measured(
                        _pooled(rule, ordered, picked, 2 * ip.EXTREMES),
                        ip.stock_cost,
                        ip.STOCK_SLIPPAGE_BPS,
                    ),
                }
            )
    return out


def show(runs: Sequence[dict[str, Any]]) -> None:
    header = (
        f"{'rule':<60}{'trades':>8}{'gross':>7}{'net':>7}{'net tot':>9}{'maxDD':>8}"
        f"{'hit':>5}{'g bps':>7}{'n bps':>7} | {'<2024':>6}{'2024+':>6}"
    )
    print("\n" + header + "\n" + "-" * len(header))
    for run in runs:
        gross, net = run["gross"], run["net"]
        print(
            f"{run['rule'][:59]:<60}{net.get('trades', 0):>8}"
            f"{gross.get('sharpe') or 0:>7.2f}{net.get('sharpe') or 0:>7.2f}"
            f"{net.get('total_return', 0):>9.1%}{net.get('max_drawdown', 0):>8.1%}"
            f"{net.get('hit_rate') or 0:>5.0%}"
            f"{gross.get('gross_bps_per_trade') or 0:>7.1f}{net.get('net_bps_per_trade') or 0:>7.1f}"
            f" | {run['net_before_2024'].get('sharpe') or 0:>6.2f}"
            f"{run['net_from_2024'].get('sharpe') or 0:>6.2f}"
        )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="india-intraday")
    parser.add_argument("--stocks", type=int, default=UNIVERSE_SIZE)
    parser.add_argument("--index-only", action="store_true")
    args = parser.parse_args(argv)

    days = ip.load(INDEX)
    print(f"{INDEX}: {len(days)} normal sessions {days[0].day} to {days[-1].day}")
    runs = index_rules(days, official_closes(INDEX))
    symbols: list[str] = []
    if not args.index_only:
        symbols = universe(args.stocks)
        print(f"{len(symbols)} largest stocks with minute history, by today's market value")
        runs += stock_rules(symbols)
    show(runs)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(
            {
                "research": "docs/RESEARCH/076-five-indian-intraday-rules.md",
                "index": INDEX,
                "window": [days[0].day.isoformat(), days[-1].day.isoformat()],
                "split": SPLIT.isoformat(),
                "universe": symbols,
                "universe_note": "chosen by today's market value: survivorship bias",
                "slippage_bps_per_side": {
                    "index": sp.SLIPPAGE_BPS,
                    "stocks": ip.STOCK_SLIPPAGE_BPS,
                },
                "spent_trials": 0,
                "runs": runs,
            },
            indent=1,
        ),
        encoding="utf-8",
    )
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
