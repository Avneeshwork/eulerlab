"""The skeptic agent: tries to prove a good-looking result is fake, before the gate sees it.

It reads a stored backtest report's daily equity curve and runs attacks that
need no re-run and spend no trial:

| attack | the question | how |
|---|---|---|
| one lucky year | does it survive without its best calendar year? | Sharpe with that year removed |
| a few lucky days | how much of the gain is the best 1% of days? | share of total log return |
| Indian stress windows | what did it do when the market broke? | return inside each dated window |
| cost shock | what if costs were 2x, or STT rose? | turnover-based charge, if the report holds turnover |
| t-statistic | is the mean daily return distinguishable from zero? | t = mean / (sd / sqrt n) |
| drawdown length | how long was the longest time under water? | sessions from peak to recovery |

The model, when it has budget, reads the numbers and writes the five ways the
result could still be fake that these numbers cannot rule out (lookahead,
survivorship, a data error, crowding, regime). It changes nothing: the report
is read, never written, and the gate's own stress tests (`validation/stress.py`,
run by `make validate`) remain the ones that count.
"""

from __future__ import annotations

import json
import math
import statistics
from collections import defaultdict
from datetime import UTC, date, datetime
from itertools import pairwise
from pathlib import Path
from typing import Any

from eulerlab.agents.runtime import Context, Item, WorkerResult, untrusted
from eulerlab.paths import data_path

WORKSPACES = data_path("workspaces")
TRADING_DAYS = 252

STRESS_WINDOWS: tuple[tuple[str, str, str], ...] = (
    ("Demonetisation", "2016-11-08", "2016-12-30"),
    ("IL&FS default and NBFC sell-off", "2018-09-14", "2018-10-31"),
    ("COVID crash", "2020-02-20", "2020-03-31"),
    ("COVID rebound", "2020-04-01", "2020-06-30"),
    ("Rate-hike sell-off", "2022-01-10", "2022-06-30"),
    ("Hindenburg report on Adani", "2023-01-24", "2023-02-28"),
    ("Election result day", "2024-06-04", "2024-06-04"),
    ("Small-cap correction", "2024-09-27", "2025-03-31"),
)
"""Dated windows where Indian equities broke or turned. The dates are when each
event became public; the windows end where the first move settled. ASSUMPTION
A-067: chosen by hand, not from a source, and listed so they can be argued with."""


def find_report(ctx: Context) -> Path | None:
    raw = str(ctx.args.get("report") or "").strip()
    if raw:
        path = Path(raw)
        return path if path.is_file() and path.suffix == ".json" else None
    strategy = str(ctx.args.get("strategy") or "").strip()
    if not strategy or "/" in strategy or ".." in strategy:
        return None
    found = sorted(WORKSPACES.glob(f"*/reports/{strategy}/*.json"), key=lambda p: p.stat().st_mtime)
    return found[-1] if found else None


def targets(root: Path | None = None) -> list[dict[str, str]]:
    """Every strategy with a stored report, newest report each, sorted by name.

    This is the list the page offers to attack. Reading it spends no trial.
    """
    newest: dict[str, Path] = {}
    for path in (root or WORKSPACES).glob("*/reports/*/*.json"):
        name = path.parent.name
        if name not in newest or path.stat().st_mtime > newest[name].stat().st_mtime:
            newest[name] = path
    return [
        {
            "strategy": name,
            "report": str(path),
            "at": datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(timespec="seconds"),
        }
        for name, path in sorted(newest.items())
    ]


def curve(report: dict[str, Any]) -> tuple[list[date], list[float]]:
    equity = report.get("equity") or {}
    days = [date.fromisoformat(d) for d in equity.get("days") or []]
    values = [float(v) for v in equity.get("values") or []]
    n = min(len(days), len(values))
    return days[:n], values[:n]


def returns(values: list[float]) -> list[float]:
    return [b / a - 1.0 for a, b in pairwise(values) if a > 0]


def sharpe(rets: list[float]) -> float | None:
    if len(rets) < 20:
        return None
    sd = statistics.pstdev(rets)
    return statistics.fmean(rets) / sd * math.sqrt(TRADING_DAYS) if sd > 0 else None


def attacks(days: list[date], values: list[float], report: dict[str, Any]) -> dict[str, Any]:
    rets = returns(values)
    rdays = days[1:]
    out: dict[str, Any] = {"sessions": len(rets), "sharpe": sharpe(rets)}
    if len(rets) < 20:
        out["error"] = "fewer than 20 daily returns; nothing to attack"
        return out

    by_year: dict[int, list[float]] = defaultdict(list)
    for d, r in zip(rdays, rets, strict=False):
        by_year[d.year].append(r)
    year_return = {y: math.prod(1 + r for r in rs) - 1 for y, rs in by_year.items()}
    best_year = max(year_return, key=lambda y: year_return[y])
    without = [r for d, r in zip(rdays, rets, strict=False) if d.year != best_year]
    out["by_year"] = {str(y): round(v, 4) for y, v in sorted(year_return.items())}
    out["best_year"] = best_year
    out["sharpe_without_best_year"] = sharpe(without)

    logs = sorted((math.log1p(r) for r in rets), reverse=True)
    total = sum(logs)
    top = logs[: max(1, len(logs) // 100)]
    out["best_1pct_days_share"] = round(sum(top) / total, 3) if total > 0 else None
    out["total_log_return"] = round(total, 4)

    sd = statistics.pstdev(rets)
    out["t_stat"] = (
        round(statistics.fmean(rets) / (sd / math.sqrt(len(rets))), 2) if sd > 0 else None
    )

    windows = []
    for name, start, end in STRESS_WINDOWS:
        lo, hi = date.fromisoformat(start), date.fromisoformat(end)
        inside = [r for d, r in zip(rdays, rets, strict=False) if lo <= d <= hi]
        if inside:
            windows.append(
                {
                    "name": name,
                    "from": start,
                    "to": end,
                    "return": round(math.prod(1 + r for r in inside) - 1, 4),
                    "sessions": len(inside),
                }
            )
    out["stress_windows"] = windows

    peak, under, longest = values[0], 0, 0
    for v in values:
        if v >= peak:
            peak, under = v, 0
        else:
            under += 1
            longest = max(longest, under)
    out["longest_underwater_sessions"] = longest

    summary = report.get("summary") or report.get("metrics") or {}
    costs = summary.get("costs") if isinstance(summary, dict) else None
    start_equity = values[0]
    if isinstance(costs, int | float) and start_equity > 0:
        years = len(rets) / TRADING_DAYS
        drag = costs / start_equity / max(years, 1e-9)
        mean_annual = statistics.fmean(rets) * TRADING_DAYS
        out["cost_drag_per_year"] = round(drag, 4)
        out["return_at_2x_costs"] = round(mean_annual - drag, 4)
    return out


def verdicts(found: dict[str, Any]) -> list[Item]:
    items: list[Item] = []
    base = found.get("sharpe")
    without = found.get("sharpe_without_best_year")
    if isinstance(base, float) and isinstance(without, float) and base > 0 and without < 0.5 * base:
        items.append(
            Item(
                kind="finding",
                title=f"one year carries it: Sharpe {base:.2f}, {without:.2f} without {found['best_year']}",
                severity="critical",
            )
        )
    share = found.get("best_1pct_days_share")
    if isinstance(share, float) and share > 0.5:
        items.append(
            Item(
                kind="finding",
                title=f"the best 1% of days make {share:.0%} of the gain",
                severity="critical" if share > 1 else "warn",
            )
        )
    t = found.get("t_stat")
    if isinstance(t, float) and t < 3.0:
        items.append(
            Item(
                kind="finding",
                title=f"t-statistic {t:.2f}, under the mandate's 3.0",
                severity="warn",
            )
        )
    for w in found.get("stress_windows", []):
        if w["return"] < -0.15:
            items.append(
                Item(
                    kind="finding",
                    title=f"{w['name']}: {w['return']:.1%} in {w['sessions']} sessions",
                    severity="warn",
                )
            )
    if isinstance(found.get("return_at_2x_costs"), float) and found["return_at_2x_costs"] <= 0:
        items.append(
            Item(
                kind="finding",
                title="at twice the costs the mean annual return is gone",
                severity="critical",
            )
        )
    if found.get("longest_underwater_sessions", 0) > TRADING_DAYS * 2:
        items.append(
            Item(
                kind="finding",
                title=f"under water for {found['longest_underwater_sessions']} sessions at its longest",
                severity="warn",
            )
        )
    return items


def attack_all(ctx: Context) -> WorkerResult:
    """Numbers-only attacks on every stored result, worst first. No model request is spent."""
    rows = targets()
    if not rows:
        return WorkerResult(
            "No stored backtest results to attack yet. Run a backtest from the Strategies page first.",
            status="refused",
        )
    ctx.step(f"Attacking all {len(rows)} stored results, numbers only, no model")
    scored: list[tuple[int, int, str, list[Item]]] = []
    unread = 0
    for row in rows:
        try:
            report = json.loads(Path(row["report"]).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            unread += 1
            continue
        days, values = curve(report)
        found = attacks(days, values, report)
        if "error" in found:
            unread += 1
            continue
        found_items = verdicts(found)
        critical = sum(1 for i in found_items if i.severity == "critical")
        warn = sum(1 for i in found_items if i.severity == "warn")
        scored.append((critical, warn, row["strategy"], found_items))
    scored.sort(key=lambda r: (-r[0], -r[1], r[2]))
    items = [
        Item(
            kind="finding",
            title=(
                f"{name}: {critical} critical, {warn} warning{'s' if warn != 1 else ''}"
                if critical or warn
                else f"{name}: survived every attack"
            ),
            body="; ".join(i.title for i in found) or "no attack found a weakness in the numbers",
            severity="critical" if critical else "warn" if warn else "info",
            ref=f"strategy={name}",
        )
        for critical, warn, name, found in scored
    ]
    bad = sum(1 for r in scored if r[0])
    shaky = sum(1 for r in scored if not r[0] and r[1])
    summary = (
        f"Checked {len(scored)} stored results: {bad} have a problem that could make the result fake, "
        f"{shaky} have warnings, {len(scored) - bad - shaky} survived every attack"
        + (f"; {unread} too short or unreadable" if unread else "")
        + ". Pick one to get its full review."
    )
    return WorkerResult(summary, items, data={"checked": len(scored), "unread": unread})


def run(ctx: Context) -> WorkerResult:
    named = str(ctx.args.get("strategy") or "").strip()
    if not str(ctx.args.get("report") or "").strip() and named in ("", "all"):
        return attack_all(ctx)
    path = find_report(ctx)
    if path is None:
        return WorkerResult(
            f"No stored result for {named or 'that report'}. Pick one from the list on the card.",
            status="refused",
        )
    ctx.step(
        f"Attacking {path.parent.name}: best year and days removed, stress windows, t-stat, twice the costs"
    )
    report = json.loads(path.read_text(encoding="utf-8"))
    days, values = curve(report)
    found = attacks(days, values, report)
    if "error" in found:
        return WorkerResult(found["error"], status="refused", data=found)
    items = verdicts(found)
    if ctx.can_ask():
        try:
            text = ctx.ask(
                "You are a skeptical reviewer of one backtest. From the numbers given, list the five "
                "most likely ways the result could still be fake that these numbers cannot rule out "
                "(for example lookahead, survivorship, a data error, crowding, a regime that will not "
                "return, costs or capacity). One line each, specific to these numbers. No praise.",
                untrusted("attacks", json.dumps(found, default=str)),
            )
            items.append(Item(kind="review", title="five ways this could still be fake", body=text))
        except Exception as exc:
            ctx.notes.append(f"no model review: {type(exc).__name__}: {str(exc)[:120]}")
    ctx.write("attacks.json", found)
    base = found.get("sharpe")
    return WorkerResult(
        f"{path.parent.name}: Sharpe {base:.2f}; "
        f"{len([i for i in items if i.severity == 'critical'])} attacks found a problem that could make it fake"
        if isinstance(base, float)
        else f"{path.parent.name}: attacked",
        items,
        data={"report": str(path), "attacks": found},
    )
