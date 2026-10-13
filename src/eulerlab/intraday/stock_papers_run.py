"""`make stock-intraday` — run research 078's two stock rules and report.

Both run on the `UNIVERSE_SIZE` largest companies that have minute history,
chosen by today's market value: a list fixed with hindsight, which flatters
any long-only result and is stated in the output.

Each setting is run gross, and after NSE charges plus slippage, on the whole
history and on each side of 2024. Writes
`data/derived/stock_intraday_papers.json`.

Screening runs of published settings: no trial is recorded in the ledger.
"""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any

from eulerlab.intraday import india_papers as ip
from eulerlab.intraday import india_papers_run as base
from eulerlab.intraday import session_papers as sp
from eulerlab.intraday import stock_papers as stp

OUT = Path("data/derived/stock_intraday_papers.json")
REVERSAL_SETTINGS = ((5, False), (5, True), (10, False), (10, True))
"""(groups, long only). Quintiles are the paper's main table; deciles and the
losers alone are its own robustness cases. All four are reported together."""
CONTINUATION_GROUPS = 10


def reversal_rule(groups: int, long_only: bool) -> str:
    cut = {5: "quintiles", 10: "deciles"}[groups]
    side = "losers only" if long_only else "losers against winners"
    return f"end-of-day reversal, {cut}, {side}, 14:40-15:10"


CONTINUATION_RULE = "opening half-hour repeats, deciles, 09:16-09:45"


def marks_for(symbols: Sequence[str]) -> dict[str, dict[date, stp.StockMarks]]:
    """Every stock reduced to its marks, one stock in memory at a time."""
    base.fetch_missing(symbols)
    out: dict[str, dict[date, stp.StockMarks]] = {}
    started = time.monotonic()
    for number, symbol in enumerate(symbols, start=1):
        out[symbol] = stp.stock_marks(ip.load(symbol))
        if number % 10 == 0:
            print(
                f"  read {number} of {len(symbols)} stocks, {time.monotonic() - started:.0f}s",
                flush=True,
            )
    return out


def runs_for(universe: dict[str, dict[date, stp.StockMarks]]) -> list[dict[str, Any]]:
    calendar = sorted({day for marks in universe.values() for day in marks})
    stocks = len(universe)
    settings: list[tuple[str, str, dict[date, dict[str, ip.Signal]], int, int]] = []
    for groups, long_only in REVERSAL_SETTINGS:
        settings.append(
            (
                "baltussen-2025",
                reversal_rule(groups, long_only),
                stp.end_of_day_reversal_signals(universe, groups=groups, long_only=long_only),
                stp.slots(stocks, groups, long_only=long_only),
                1 if long_only else 2,
            )
        )
    settings.append(
        (
            "heston-2010",
            CONTINUATION_RULE,
            stp.same_time_signals(universe, groups=CONTINUATION_GROUPS),
            stp.slots(stocks, CONTINUATION_GROUPS),
            2,
        )
    )
    out: list[dict[str, Any]] = []
    for source, rule, signals, slots, sides in settings:
        build = base._pooled(rule, calendar, signals, slots)
        out.append(
            {
                "source": source,
                "rule": rule,
                "instrument": f"{stocks} largest stocks, {slots} slots",
                # The papers' own measure: the average spread a day, no costs.
                "spread": stp.spread(build(sp.no_cost, 0.0), sides=sides),
                **base.measured(build, ip.stock_cost, ip.STOCK_SLIPPAGE_BPS),
            }
        )
    return out


def show_spreads(runs: Sequence[dict[str, Any]]) -> None:
    print(f"\n{'rule':<60}{'spread bps a day':>18}{'t':>8}   (no costs)")
    for run in runs:
        found = run["spread"]
        print(f"{run['rule'][:59]:<60}{found['bps_a_day'] or 0:>18.2f}{found['t'] or 0:>8.2f}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="stock-intraday")
    parser.add_argument("--stocks", type=int, default=base.UNIVERSE_SIZE)
    args = parser.parse_args(argv)

    symbols = base.universe(args.stocks)
    print(f"{len(symbols)} largest stocks with minute history, by today's market value")
    universe = marks_for(symbols)
    calendar = sorted({day for marks in universe.values() for day in marks})
    runs = runs_for(universe)
    show_spreads(runs)
    base.show(runs)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(
            {
                "research": "docs/RESEARCH/078-two-us-stock-rules-on-indian-stocks.md",
                "window": [calendar[0].isoformat(), calendar[-1].isoformat()],
                "split": base.SPLIT.isoformat(),
                "universe": symbols,
                "universe_note": "chosen by today's market value: survivorship bias",
                "slippage_bps_per_side": {"stocks": ip.STOCK_SLIPPAGE_BPS},
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
