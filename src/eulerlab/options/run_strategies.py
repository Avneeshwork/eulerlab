"""`make options-strategies` — run research 070's two strategies and report.

Reads `data/derived/nifty_options.jsonl` (`make nifty-options`), the Nifty 50
close and the real monthly expiries. Writes `data/derived/options_strategies.json`.
Screening runs: no trial is recorded in the ledger.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from eulerlab.options import nifty_history
from eulerlab.options import strategies as st

OUT = Path("data/derived/options_strategies.json")
CAPITAL = 1_000_000.0
SPLIT = date(2024, 1, 1)


def main() -> int:
    raw = nifty_history.load()
    days = st.load_days(raw, st.load_spot())
    expiries = st.monthly_expiries()
    print(f"{len(days)} days, {days[0].day} to {days[-1].day}")
    runs = [
        *(st.short_strangle(days, expiries, leg=k, capital=CAPITAL) for k in (1, 2, 3)),
        st.covered_call_daily(days, expiries, capital=CAPITAL),
        st.covered_call_monthly(days, expiries, capital=CAPITAL),
        st.buy_and_hold_future(days, expiries, capital=CAPITAL),
    ]
    out: dict[str, Any] = {
        "window": [days[0].day.isoformat(), days[-1].day.isoformat()],
        "capital": CAPITAL,
        "split": SPLIT.isoformat(),
        "spent_trials": 0,
        "runs": [],
    }
    print(
        f"{'strategy':<30}{'n':>5}{'sharpe':>8}{'total':>10}{'cagr':>8}{'maxdd':>8}{'win':>6}"
        f"{'worst':>8} | {'IS sh':>6}{'HO sh':>7}{'HO cagr':>8}"
    )
    for r in runs:
        whole, before, after = r.stats(), r.stats(end=SPLIT), r.stats(start=SPLIT)
        out["runs"].append(
            {
                "name": r.name,
                "whole": whole,
                "before_2024": before,
                "from_2024": after,
                "skipped": len(r.skipped),
                "skipped_examples": r.skipped[:5],
                "periods": [
                    [
                        p.start.isoformat(),
                        p.end.isoformat(),
                        round(p.ret, 5),
                        round(p.costs, 2),
                        p.note,
                    ]
                    for p in r.periods
                ],
            }
        )
        print(
            f"{r.name:<30}{whole.get('periods', 0):>5}{whole.get('sharpe', 0):>8.2f}"
            f"{whole.get('total_return', 0):>10.1%}{whole.get('cagr', 0):>8.1%}"
            f"{whole.get('max_drawdown', 0):>8.1%}{whole.get('win_rate', 0):>6.0%}"
            f"{whole.get('worst_period', 0):>8.1%} | {before.get('sharpe', 0):>6.2f}"
            f"{after.get('sharpe', 0):>7.2f}{after.get('cagr', 0):>8.1%}  skipped {len(r.skipped)}"
        )
    OUT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"written to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
