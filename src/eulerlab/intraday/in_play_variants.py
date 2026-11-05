"""The in-play ORB restricted to fewer, stronger trades (research 155, H-0050).

H-0045 earned 6.32 bps a trade against a 12.24 bps round trip. Fewer trades
help only if the trades kept earn more, so eight filters fixed in H-0050
(top 5 or 10 a day; relative opening volume at least 2 or 3; entry by 10:15 or
any time) are run on 2021-08-20 to 2023-12-31. The one with the best net
Sharpe there is the only one run on 2024. The bar it must clear in 2024 is the
expected best Sharpe of nine worthless variants (H-0045 and these eight).

No minute file is opened: `cash_five_screen` stored every stock-day's
relative volume and breakout trade. `make in-play-variants` writes
`data/derived/in_play_variants.json`.
"""

from __future__ import annotations

import argparse
import itertools
import json
import pickle
import statistics
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any

from eulerlab.intraday import cash_five_screen as five
from eulerlab.intraday import cross_section as cs
from eulerlab.validation.statistics import expected_max_sharpe

OUT = Path("data/derived/in_play_variants.json")
SELECTION_END = date(2023, 12, 31)
TOP_N = (5, 10)
MIN_RELATIVE_VOLUME = (2.0, 3.0)
LATEST_ENTRY = (60, cs.EXIT - 1)
"""10:15, or any minute before the 15:10 exit."""
TRIALS = 9
"""H-0045 and the eight variants."""


def trades(
    marks: Mapping[str, Mapping[date, five.InPlay]],
    *,
    top_n: int,
    min_relative_volume: float,
    latest_entry: int,
    days: set[date],
) -> list[cs.Trade]:
    by_day: dict[date, list[tuple[float, str, five.InPlay]]] = defaultdict(list)
    for symbol, found in marks.items():
        for day, mark in found.items():
            if day in days and mark.relative_volume >= min_relative_volume:
                by_day[day].append((mark.relative_volume, symbol, mark))
    out = []
    for day, today in by_day.items():
        today.sort(key=lambda item: (-item[0], item[1]))
        for _, symbol, mark in today[:top_n]:
            fill = mark.fill
            if fill is None or fill.entry_minute > latest_entry:
                continue
            quantity = cs.sized(five.TRADE, fill.entry)
            if quantity:
                out.append(
                    cs.Trade(
                        symbol,
                        day,
                        fill.direction,
                        quantity,
                        fill.entry_minute,
                        fill.entry,
                        fill.exit_minute,
                        fill.exit,
                        fill.reason,
                    )
                )
    return out


def _run(
    name: str,
    marks: Mapping[str, Mapping[date, five.InPlay]],
    sessions: Sequence[date],
    top_n: int,
    rv: float,
    latest: int,
) -> dict[str, Any]:
    book = trades(
        marks, top_n=top_n, min_relative_volume=rv, latest_entry=latest, days=set(sessions)
    )
    run = cs.report(
        name,
        book,
        sessions,
        params={"top_n": top_n, "min_relative_volume": rv, "latest_entry_minute": latest},
        capital=five.TRADE * top_n,
    )
    run.pop("daily", None)
    run.pop("trade_log", None)
    return run


class _Parts(pickle.Unpickler):
    """Parts written before 2026-11-05 20:30 name their classes `__main__` (the batch
    ran as a script); they are `cash_five_screen`'s."""

    def find_class(self, module: str, name: str) -> Any:
        if module == "__main__":
            module = five.__name__
        return super().find_class(module, name)


def run(output: Path = OUT) -> dict[str, Any]:
    marks: dict[str, Any] = {}
    sessions: set[date] = set()
    for part in sorted(five.PARTS.glob("*.pkl")):
        with part.open("rb") as handle:
            loaded = _Parts(handle).load()
        sessions.update(loaded["sessions"])
        for symbol, found in loaded["marks"].items():
            marks[symbol] = found["in_play"]
    if not marks:
        msg = "no cash-five parts: run `make cash-five` first"
        raise RuntimeError(msg)
    window = sorted(d for d in sessions if d <= cs.DATA_END)
    selection = [d for d in window if d <= SELECTION_END]
    test = [d for d in window if d > SELECTION_END]
    variants = []
    for top_n, rv, latest in itertools.product(TOP_N, MIN_RELATIVE_VOLUME, LATEST_ENTRY):
        name = f"top{top_n}_rv{rv:g}_by{'1015' if latest == 60 else 'any'}"
        variants.append(_run(name, marks, selection, top_n, rv, latest))
    sharpes = [v["net"]["sharpe"] for v in variants]
    chosen = max(variants, key=lambda v: (v["net"]["sharpe"], -v["trades"]))
    params = chosen["params"]
    tested = _run(
        chosen["id"],
        marks,
        test,
        params["top_n"],
        params["min_relative_volume"],
        params["latest_entry_minute"],
    )
    bar = expected_max_sharpe(TRIALS, variance_of_sharpes=statistics.pvariance(sharpes))
    passed = tested["net"]["sharpe"] > bar and tested["per_trade_bps"]["net_mean"] > 0
    result = {
        "hypothesis": "H-0050",
        "research": "docs/RESEARCH/155-five-cash-intraday-rules.md",
        "selection_window": [selection[0].isoformat(), selection[-1].isoformat()],
        "test_window": [test[0].isoformat(), test[-1].isoformat()],
        "variants_on_selection": [
            {
                "id": v["id"],
                "trades": v["trades"],
                "per_trade_bps": v["per_trade_bps"],
                "net_sharpe": v["net"]["sharpe"],
                "net_return": v["net"]["total_return"],
            }
            for v in variants
        ],
        "chosen": chosen["id"],
        "test": tested,
        "bar_sharpe": round(bar, 3),
        "passed": passed,
        "spent_trials": 0,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=1), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(prog="in-play-variants")
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
    result = run(args.output)
    for v in result["variants_on_selection"]:
        print(
            f"{v['id']}: {v['trades']} trades, {v['per_trade_bps']['gross_mean']} gross, "
            f"{v['per_trade_bps']['net_mean']} net bps a trade, net Sharpe {v['net_sharpe']}"
        )
    test = result["test"]
    print(
        f"chosen {result['chosen']} -> 2024: {test['trades']} trades, "
        f"{test['per_trade_bps']['net_mean']} net bps a trade, net Sharpe {test['net']['sharpe']} "
        f"(bar {result['bar_sharpe']}); passed: {result['passed']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
