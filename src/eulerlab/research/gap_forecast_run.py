"""`make gap-forecast` — Mukherjee & Mandal (2025) on this project's data.

Reads the Nifty 50 and India VIX from `index_history.jsonl` and the Nifty
future from `nifty_futures.jsonl` (`make market-history`). Writes
`data/derived/gap_forecast.json`. Research 072 reads it.

Calculations, not engine runs: no trial is recorded in the ledger.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import date
from itertools import pairwise
from pathlib import Path
from typing import Any

from eulerlab.research import gap_forecast as gf
from eulerlab.research.session_studies import futures_legs

OUT = Path("data/derived/gap_forecast.json")
PAPER_END = date(2025, 6, 30)
"""The paper's sample ends June 2025. Ours starts in 2015, not 2010."""
SPLIT = date(2024, 1, 1)

PAPER: dict[str, tuple[int, int]] = {
    "VIX up -> gap down": (1834, 670),
    "VIX down -> gap up": (1960, 1346),
    "GREEN -> gap up": (1791, 1257),
    "RED -> gap down": (2011, 753),
    "GREEN & VIX down -> gap up": (1163, 810),
    "RED & VIX up -> gap down": (1208, 481),
}
"""(count, success) from the paper's Tables 5-7, 2010 to June 2025, 3,802 days."""


def load_days() -> list[gf.Day]:
    """Every session with a Nifty 50 and an India VIX open and close."""
    from eulerlab.market_history import INDEX_HISTORY, _stored_days

    raw = []
    for day in sorted(_stored_days(INDEX_HISTORY), key=lambda d: str(d["d"])):
        nifty, vix = day["indices"].get("Nifty 50"), day["indices"].get("India VIX")
        if nifty and vix and all(nifty.get(k) for k in "oc") and all(vix.get(k) for k in "oc"):
            raw.append(
                gf.Day(
                    date.fromisoformat(day["d"]),
                    float(nifty["o"]),
                    float(nifty["c"]),
                    float(vix["o"]),
                    float(vix["c"]),
                )
            )
    out = raw[:1]
    for before, today in pairwise(raw):
        out.append(
            gf.Day(
                today.day,
                today.open,
                today.close,
                today.vix_open,
                today.vix_close,
                before.vix_close,
            )
        )
    return out


def run() -> dict[str, Any]:
    days, legs = load_days(), futures_legs()
    last = days[-1].day
    out: dict[str, Any] = {
        "window": [days[0].day.isoformat(), last.isoformat()],
        "paper_window": ["2010-01-01", PAPER_END.isoformat()],
        "split": SPLIT.isoformat(),
        "spent_trials": 0,
        "vix_definitions_agree": gf.agreement(days),
        "paper": {
            k: {"count": n, "success": s, "rate": round(s / n, 4)} for k, (n, s) in PAPER.items()
        },
        "tables": {
            "to_paper_end": gf.tables(days, end=PAPER_END),
            "all": gf.tables(days),
            "all_close_to_close_vix": gf.tables(days, definition=gf.VixChange.CLOSE_TO_CLOSE),
        },
        "trades": [],
    }
    cases: list[tuple[gf.Model | None, str]] = [(None, "long")]
    cases += [(model, side) for model in gf.Model for side in ("both", "long", "short")]
    for model, side in cases:
        whole = gf.trade(model, days, legs, side=side)
        out["trades"].append(
            {
                **whole,
                "net_before_2024": gf.trade(model, days, legs, side=side, end=date(2023, 12, 31))[
                    "net"
                ],
                "net_from_2024": gf.trade(model, days, legs, side=side, start=SPLIT)["net"],
            }
        )
    return out


def main(argv: Sequence[str] | None = None) -> int:
    argparse.ArgumentParser(prog="gap-forecast").parse_args(argv)
    out = run()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1), encoding="utf-8")

    agree = out["vix_definitions_agree"]
    print(f"Nifty 50 and India VIX, {out['window'][0]} to {out['window'][1]}")
    print(
        f"VIX close-minus-open and close-minus-previous-close agree on {agree['same']} days, "
        f"differ on {agree['differ']}"
    )
    for name, title in (("to_paper_end", "to June 2025 (the paper's end)"), ("all", "all days")):
        block = out["tables"][name]
        print(f"\n{title}: {block['days']} days, gap up on any day {block['gap_up_any_day']:.1%}")
        print(
            f"  {'signal':<30}{'count':>6}{'right':>7}{'rate':>8}{'paper':>8}{'base':>8}{'lift':>8}{'z':>7}"
        )
        for model in gf.Model:
            for row in block[model.value]["rows"]:
                paper = out["paper"][row["signal"]]["rate"]
                print(
                    f"  {row['signal']:<30}{row['count']:>6}{row['success']:>7}{row['rate']:>8.1%}"
                    f"{paper:>8.1%}{row['base_rate']:>8.1%}{row['lift']:>+8.1%}{row['z']:>7.2f}"
                )
            print(
                f"  {'  ' + model.value + ' accuracy':<30}{block[model.value]['signalling_days']:>6}"
                f"{block[model.value]['success']:>7}{block[model.value]['accuracy']:>8.1%}"
                f"{'':>8}{block[model.value]['always_predict_up']:>8.1%}"
            )
    print("\nTraded on the Nifty future, close to next open, all days")
    print(
        f"  {'model':<12}{'side':<7}{'nights':>7}{'right':>8}{'gross':>9}{'net':>9}"
        f"{'net Sh':>8}{'maxDD':>8} | {'<2024':>7}{'2024+':>7}"
    )
    for t in out["trades"]:
        print(
            f"  {t['model']:<12}{t['side']:<7}{t['nights']:>7}{t['future_gapped_as_predicted']:>8.1%}"
            f"{t['gross']['total_return']:>9.1%}{t['net']['total_return']:>9.1%}"
            f"{t['net']['sharpe']:>8.2f}{t['net']['max_drawdown']:>8.1%} | "
            f"{t['net_before_2024']['sharpe']:>7.2f}{t['net_from_2024']['sharpe']:>7.2f}"
        )
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
