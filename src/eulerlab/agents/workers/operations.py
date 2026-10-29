"""The operations agent: is every job finishing in time, and are costs what the model says?

**Latency, as deadlines.** The strategies this data supports trade at the
close or overnight, so the edge is not microseconds; what matters is that each
step finishes with room to spare. For each step in
`data/derived/timings.jsonl` it reports the median, the 95th percentile and
the latest time, flags a step whose latest run used more than `warn_share` of
its deadline (`options.deadlines`, in seconds), and flags one getting slower:
the median of its last five runs above 1.5 times the median of the twenty
before.

**Costs against reality.** Every cost rate is still sourced secondarily
(T-906). It reports the contract-note check (`costs/check.check_contract_notes`)
on every run, so "costs unverified" stays in front of the operator until real
notes match to the paisa.

**The paper books' own health**: a book that halted, or whose state carries
warnings, is listed with the reason the runner wrote.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import timedelta
from typing import Any

from eulerlab import timings
from eulerlab.agents.runtime import Context, Item, WorkerResult


def _quantile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


def step_report(
    rows: list[dict[str, Any]], deadlines: dict[str, float], warn_share: float
) -> tuple[list[dict[str, Any]], list[Item]]:
    by_job: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_job[str(row.get("job"))].append(row)
    report: list[dict[str, Any]] = []
    items: list[Item] = []
    for job, runs in sorted(by_job.items()):
        runs.sort(key=lambda r: str(r.get("finished", "")))
        seconds = [float(r.get("seconds", 0.0)) for r in runs if r.get("ok", True)]
        failures = sum(1 for r in runs if not r.get("ok", True))
        if not seconds:
            report.append({"job": job, "runs": len(runs), "failures": failures})
            continue
        latest = seconds[-1]
        entry: dict[str, Any] = {
            "job": job,
            "runs": len(runs),
            "failures": failures,
            "median": round(statistics.median(seconds), 1),
            "p95": round(_quantile(seconds, 0.95), 1),
            "latest": round(latest, 1),
        }
        deadline = deadlines.get(job)
        if deadline:
            entry["deadline"] = deadline
            entry["margin"] = round(1 - latest / deadline, 3)
            if latest > deadline:
                items.append(
                    Item(
                        kind="alert",
                        title=f"{job} missed its deadline: {latest:.0f}s of {deadline:.0f}s",
                        severity="critical",
                    )
                )
            elif latest > warn_share * deadline:
                items.append(
                    Item(
                        kind="alert",
                        title=f"{job} used {latest / deadline:.0%} of its deadline",
                        severity="warn",
                    )
                )
        if len(seconds) >= 25:
            recent = statistics.median(seconds[-5:])
            before = statistics.median(seconds[-25:-5])
            if before > 0 and recent > 1.5 * before:
                entry["slowing"] = round(recent / before, 2)
                items.append(
                    Item(
                        kind="finding",
                        title=f"{job} is getting slower: {before:.0f}s to {recent:.0f}s",
                        severity="warn",
                    )
                )
        report.append(entry)
    return report, items


def run(ctx: Context) -> WorkerResult:
    from eulerlab.costs import check as cost_check
    from eulerlab.deploy import deployments

    deadlines = {str(k): float(v) for k, v in (ctx.options.get("deadlines") or {}).items()}
    warn_share = float(ctx.options.get("warn_share", 0.8))
    ctx.step("Reading 60 days of job timings against their deadlines")
    rows = timings.read(since=ctx.now - timedelta(days=60))
    report, items = step_report(rows, deadlines, warn_share)

    ctx.step("Checking the cost model against contract notes, then each deployment")
    notes = cost_check.check_contract_notes()
    items.append(
        Item(
            kind="finding",
            title=f"cost model vs contract notes: {notes.status}",
            body=notes.detail,
            severity="info" if notes.status == "PASS" else "critical" if notes.failed else "warn",
            ref="make check-costs",
        )
    )

    for d in deployments.all_deployments():
        current = deployments.read_state(d) or {}
        if d.status != "active":
            items.append(
                Item(
                    kind="alert",
                    title=f"{d.strategy_id} ({d.mode}) is {d.status}",
                    body=d.status_reason,
                    severity="warn",
                )
            )
        for warning in list(current.get("warnings") or [])[:3]:
            items.append(
                Item(
                    kind="finding", title=f"{d.strategy_id}: {str(warning)[:150]}", severity="info"
                )
            )

    slow = sum(1 for i in items if i.kind == "alert")
    return WorkerResult(
        f"{len(report)} timed steps over 60 days; {slow} alerts",
        items,
        data={"steps": report},
    )
