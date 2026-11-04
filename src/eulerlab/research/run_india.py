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
GITHUB_OUT = Path("data/derived/github_daily.json")
EVIDENCE_OUT = Path("data/derived/evidence_daily.json")
EVENTS_OUT = Path("data/derived/events_daily.json")
SCREENER_OUT = Path("data/derived/screener_models.json")
START, END = "2016-01-01", "2026-09-30"


def run_one(strategy_id: str, *, start: str, end: str, tier: str) -> dict[str, Any]:
    from eulerlab.api import server
    from eulerlab.api.requests import BatchRunRequest
    from eulerlab.backtest import (
        events_daily,
        evidence_daily,
        github_daily,
        india_papers,
        screener_models,
    )

    spec = {
        **india_papers.BY_ID,
        **screener_models.BY_ID,
        **github_daily.BY_ID,
        **evidence_daily.BY_ID,
        **events_daily.BY_ID,
    }[strategy_id]
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
    from eulerlab.backtest import (
        events_daily,
        evidence_daily,
        github_daily,
        india_papers,
        screener_models,
    )

    parser = argparse.ArgumentParser(prog="india-papers")
    parser.add_argument("--only", default="", help="comma-separated strategy ids")
    parser.add_argument(
        "--set",
        choices=("papers", "github", "evidence", "events", "screener"),
        default="papers",
        help="papers: backtest.india_papers; github / evidence: research 113's batches",
    )
    parser.add_argument("--from", dest="start", default=None)
    parser.add_argument("--to", dest="end", default=None)
    parser.add_argument("--tier", default="B")
    args = parser.parse_args(argv)
    STRATEGIES = {
        "papers": india_papers.STRATEGIES,
        "github": github_daily.STRATEGIES,
        "evidence": evidence_daily.STRATEGIES,
        "events": events_daily.STRATEGIES,
        "screener": screener_models.STRATEGIES,
    }[args.set]
    out_path = {
        "papers": OUT,
        "github": GITHUB_OUT,
        "evidence": EVIDENCE_OUT,
        "events": EVENTS_OUT,
        "screener": SCREENER_OUT,
    }[args.set]
    # The event strategies' data covers 2021-07 to 2024 only (`events_daily`).
    window = events_daily.EVENTS_WINDOW if args.set == "events" else (START, END)
    args.start = args.start or window[0]
    args.end = args.end or window[1]

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
    if out_path.exists() and wanted:
        previous = {
            r["id"]: r for r in json.loads(out_path.read_text(encoding="utf-8")).get("runs", [])
        }
    merged = {**previous, **{r["id"]: r for r in rows}}
    out = {
        "window": [args.start, args.end],
        "tier": args.tier,
        "benchmark": benchmark(args.start, args.end),
        "spent_trials": 0,
        "note": "Screening runs: none of these is in the trial ledger.",
        "runs": list(merged.values()),
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"written to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
