"""`make india-papers` — backtest every Indian-equity paper strategy, the same way.

Each strategy in `backtest.india_papers` runs through `/api/run/batch` — the
engine, result store and report every other strategy uses — over one common
window, Tier B, after Indian costs, in the default workspace, so the results
appear on the Strategies page and in the Research Library. A summary lands in
`data/derived/india_papers.json`.

These are screening runs: like every batch from the workbench they spend no
trial in the ledger (T-3321). Nineteen configurations tested here and one kept
would be a selection the noise bar never saw; the summary says so.
"""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Sequence
from itertools import pairwise
from pathlib import Path
from typing import Any

OUT = Path("data/derived/india_papers.json")
START, END = "2016-01-01", "2026-09-30"


def run_one(strategy_id: str, *, start: str, end: str, tier: str) -> dict[str, Any]:
    from eulerlab.api import server
    from eulerlab.api.requests import BatchRunRequest
    from eulerlab.backtest.india_papers import BY_ID

    spec = BY_ID[strategy_id]
    # The API abandons a job after 15 minutes so the workbench never hangs on
    # one. This is an offline research run: a rule replayed daily over the
    # whole panel for ten years (india_bb_rsi) needs longer, and is allowed it.
    server.JOB_TIMEOUT_SECONDS = 4 * 3600
    began = time.monotonic()
    job = server.run_batch(
        BatchRunRequest(
            strategies=[strategy_id],
            days=3000,
            tier="B" if tier == "B" else "A",
            universe=spec.universe,
            instruments=list(spec.instruments),
            start=start,
            end=end,
            use_cache=False,
        )
    )
    if not job.get("ok"):
        return {"id": strategy_id, "error": str(job.get("error"))}
    while True:
        status = server.job_status(str(job["job"]))
        if status.get("status") in ("done", "failed"):
            break
        time.sleep(2)
    item = (status.get("result") or {}).get("results", [{}])[0]
    result = item.get("result") or {}
    return {
        "id": strategy_id,
        "paper": spec.paper,
        "title": spec.title,
        "universe": spec.universe if not spec.instruments else ",".join(spec.instruments),
        "seconds": round(time.monotonic() - began),
        "error": item.get("error") or status.get("error") or "",
        **{
            k: result.get(k)
            for k in ("sharpe", "total_return", "max_drawdown", "fills", "costs", "days")
        },
    }


def benchmark(start: str, end: str) -> dict[str, Any]:
    """NIFTYBEES bought and held over the same window, before costs."""
    from eulerlab.backtest.india_papers import INDEX_ETF
    from eulerlab.features.panel import PANEL_PATH

    closes: list[tuple[str, float]] = []
    marker = f'"s": "{INDEX_ETF}"'
    with PANEL_PATH.open(encoding="utf-8") as handle:
        for line in handle:
            if marker in line:
                row = json.loads(line)
                if start <= row["d"] <= end:
                    closes.append((row["d"], float(row["c"])))
    closes.sort()
    if len(closes) < 2:
        return {}
    # Raw closes: NIFTYBEES split 10:1 in 2019, so the ratio is taken per
    # segment and chained rather than first to last.
    total = 1.0
    for (_, a), (_, b) in pairwise(closes):
        ratio = b / a
        total *= 10 * ratio if ratio < 0.2 else ratio
    return {"symbol": INDEX_ETF, "total_return": round(total - 1.0, 6)}


def main(argv: Sequence[str] | None = None) -> int:
    from eulerlab.backtest.india_papers import STRATEGIES

    parser = argparse.ArgumentParser(prog="india-papers")
    parser.add_argument("--only", default="", help="comma-separated strategy ids")
    parser.add_argument("--from", dest="start", default=START)
    parser.add_argument("--to", dest="end", default=END)
    parser.add_argument("--tier", default="B")
    args = parser.parse_args(argv)

    wanted = {x for x in args.only.split(",") if x}
    rows = []
    for spec in STRATEGIES:
        if wanted and spec.id not in wanted:
            continue
        print(f"running {spec.id}...", flush=True)
        rows.append(run_one(spec.id, start=args.start, end=args.end, tier=args.tier))
        r = rows[-1]
        print(
            f"  sharpe={r.get('sharpe')} return={r.get('total_return')} "
            f"drawdown={r.get('max_drawdown')} fills={r.get('fills')} {r.get('error') or ''}",
            flush=True,
        )

    previous: dict[str, Any] = {}
    if OUT.exists() and wanted:
        previous = {r["id"]: r for r in json.loads(OUT.read_text(encoding="utf-8")).get("runs", [])}
    merged = {**previous, **{r["id"]: r for r in rows}}
    out = {
        "window": [args.start, args.end],
        "tier": args.tier,
        "benchmark": benchmark(args.start, args.end),
        "spent_trials": 0,
        "note": "Screening runs: none of these is in the trial ledger.",
        "runs": list(merged.values()),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"written to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
