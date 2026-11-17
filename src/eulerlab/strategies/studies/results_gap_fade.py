"""Fade the opening gap on the morning after results (research 153, H-0040).

Liu, Hope and Hu (2023) find that in China the overnight period carries the
reaction to earnings and the next session trades against it; Lou, Polk and
Skouras (2019) find overnight and intraday returns pull opposite ways. Fixed
rule: when a stock's results reach NSE after one session's close and before
the next open, and the move from the prior close to the 09:19 close is at
least 2% either way, trade against it at the 09:20 open, flat at 15:10.

No minute file is opened here. The india-five cache already holds, for every
stock and session, the 09:19 move and the 09:20 and 15:10 fills
(`overnight_reversal_screen.Mark`); this screen picks the results mornings
from it. `make results-gap-fade` writes `data/derived/results_gap_fade.json`.
"""

from __future__ import annotations

import argparse
import bisect
import json
import pickle
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

from eulerlab.ingest import nse_earnings_announcements as announcements
from eulerlab.intraday import cross_section as cs
from eulerlab.paths import data_path
from eulerlab.strategies.studies import india_five as five
from eulerlab.strategies.studies import overnight_reversal as overnight

RUN_ID = "nse_results_gap_fade"
OUT = data_path("derived/results_gap_fade.json")
THRESHOLD = 0.02
MAX_OPEN = 10
"""At most ten positions a day, ₹1 lakh each, as in the in-hours results screen."""

OPEN = time(9, 15)
CLOSE = time(15, 30)


def mornings(
    rows: Sequence[Mapping[str, Any]], sessions: Sequence[date]
) -> dict[str, dict[date, datetime]]:
    """{symbol: {session: first disclosure}} for results that arrived while the market was shut.

    A disclosure belongs to the first session that opens after it. One made
    during a session's hours is not a morning event and is skipped.
    """
    ordered = sorted(sessions)
    trading = set(ordered)
    out: dict[str, dict[date, datetime]] = defaultdict(dict)
    for row in rows:
        known = datetime.fromisoformat(str(row["knowledge_time"]))
        clock = known.time()
        if known.date() in trading and OPEN <= clock < CLOSE:
            continue
        index = bisect.bisect_left(ordered, known.date())
        if index < len(ordered) and ordered[index] == known.date() and clock >= CLOSE:
            index += 1
        if index >= len(ordered):
            continue
        day = ordered[index]
        if any(start <= day <= end for start, end in announcements.INCOMPLETE):
            continue
        symbol = str(row["symbol"])
        first = out[symbol].get(day)
        out[symbol][day] = known if first is None or known < first else first
    return dict(out)


def evaluate(
    marks: Mapping[str, Mapping[date, overnight.Mark]],
    known: Mapping[str, Mapping[date, datetime]],
    sessions: Sequence[date],
) -> dict[str, Any]:
    by_day: dict[date, list[tuple[datetime, str, overnight.Mark]]] = defaultdict(list)
    for symbol, days in known.items():
        mine = marks.get(symbol, {})
        for day, disclosed in days.items():
            found = mine.get(day)
            if found is not None and abs(found.overnight) >= THRESHOLD:
                by_day[day].append((disclosed, symbol, found))
    trades = []
    each = cs.CAPITAL / MAX_OPEN
    for day, found_today in by_day.items():
        found_today.sort(key=lambda item: (item[0], item[1]))
        for _, symbol, found in found_today[:MAX_OPEN]:
            quantity = cs.sized(each, found.entry)
            if quantity:
                trades.append(
                    cs.Trade(
                        symbol,
                        day,
                        -1 if found.overnight > 0 else 1,
                        quantity,
                        found.entry_minute,
                        found.entry,
                        found.exit_minute,
                        found.exit,
                        "time_exit",
                    )
                )
    return cs.report(
        RUN_ID,
        trades,
        sessions,
        params={
            "event": "first NSE disclosure of results after the prior close, before 09:15",
            "signal": "prior close to 09:19 close",
            "threshold": THRESHOLD,
            "entry": "09:20 open, against the gap",
            "exit": "15:10",
            "sizing": f"₹{each:,.0f} a trade, at most {MAX_OPEN} a day, earliest disclosure first",
            "excluded": "2022-07-01 to 2022-12-31 (results not labelled)",
            "slippage_bps_per_side": cs.SLIPPAGE_BPS,
        },
    )


def run(output: Path = OUT) -> dict[str, Any]:
    """Evaluate from the india-five cache; refuses to run on a partial one."""
    symbols = cs.universe()
    missing = [s for s in symbols if not five._cached(s).exists()]
    if missing:
        msg = f"{len(missing)} stocks not in the india-five cache; run `make india-five-intraday`"
        raise RuntimeError(msg)
    marks: dict[str, Any] = {}
    sessions: set[date] = set()
    for symbol in symbols:
        loaded = pickle.loads(five._cached(symbol).read_bytes())
        sessions.update(loaded["sessions"])
        marks[symbol] = loaded["marks"]["overnight"]
    window = sorted(day for day in sessions if day <= cs.DATA_END)
    known = mornings(announcements.load(), window)
    result = evaluate(marks, known, window)
    result.update(
        {
            "research": "docs/RESEARCH/153-day-trading-candidates-india.md",
            "hypothesis": "H-0040",
            "universe": len(symbols),
            "results_mornings": sum(len(v) for v in known.values()),
            "spent_trials": 0,
        }
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=1), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(prog="results-gap-fade")
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
    result = run(args.output)
    five._print(result)
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
