"""The idea lab: test the research agent's drafts within the weekly trial allowance (ADR-089).

    research agent's drafts (or card=<path>)
        -> skip repeats, drafts waiting for data, cards with no buildable configuration
        -> agent_trials.test_card: IC screen per feature, then a Tier A backtest per configuration
           (trials logged first; the panel cut at the card's holdout)
        -> skeptic's attacks on each backtest
        -> the operator's inbox: survivors, with the command that would take one to the gate

Cheapest first, and it stops when the week's allowance cannot cover the next
whole card. It does not change a card, tune a parameter, run the gate, or read
the holdout. A survivor is a candidate for the operator, not a result.

It reads the whole price panel, so it is run from the command line
(`make agent NAME=lab`) or the Sunday batch, never from the web page, which
would hold a second copy of the panel in the API's memory.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from eulerlab.agents.runtime import Context, Item, WorkerResult, latest_output


def candidates(ctx: Context) -> list[Path]:
    given = str(ctx.args.get("card") or "").strip()
    if given:
        path = Path(given)
        return [path / "card.yaml" if path.is_dir() else path]
    research = latest_output("research", ctx.root)
    if research is None:
        return []
    out: list[Path] = []
    for item in research.items:
        if item.kind != "draft" or not item.ref:
            continue
        if item.data.get("repeat_of") or item.data.get("needs_data"):
            continue
        card = Path(item.ref) / "card.yaml"
        if card.exists():
            out.append(card)
    return out


def already_tested(ctx: Context) -> set[str]:
    from eulerlab.agents.runtime import outputs

    seen: set[str] = set()
    for output in outputs(ctx.name, ctx.root, limit=50):
        seen.update(str(c) for c in output.data.get("tested", []))
    return seen


def _report(bt: Any) -> dict[str, Any]:
    return {"equity": {"days": bt.days, "values": bt.values}, "summary": {"costs": bt.costs}}


def run(ctx: Context) -> WorkerResult:
    from eulerlab.agents.workers import skeptic
    from eulerlab.quality import contract
    from eulerlab.research import agent_trials, codegen

    allowance = agent_trials.load_allowance()
    left = agent_trials.left_this_week(allowance, ctx.now)
    if left == 0:
        return WorkerResult(
            f"this week's {allowance.per_week} agent trials are spent; nothing tested",
            status="skipped",
        )
    try:
        contract.guard(["Price panel"], log=ctx.notes.append)
    except contract.LowGrade as exc:
        return WorkerResult(str(exc).splitlines()[0], status="refused")

    tested_before = already_tested(ctx)
    limit = int(ctx.args.get("max_cards") or ctx.options.get("max_cards") or 3)
    items: list[Item] = []
    tested: list[str] = []
    results: list[dict[str, Any]] = []
    for card_path in candidates(ctx):
        if len(tested) >= limit:
            break
        if str(card_path) in tested_before:
            continue
        try:
            cost, _, _ = agent_trials.cost_of(card_path)
        except (codegen.UnknownPrimitive, OSError, ValueError) as exc:
            ctx.notes.append(
                f"{card_path.parent.name}: not buildable from the library: {str(exc)[:160]}"
            )
            continue
        ctx.step(
            f"Testing {card_path.parent.name}: IC screen first, then a backtest only if it passes"
        )
        try:
            found = agent_trials.test_card(card_path, allowance=allowance, now=ctx.now)
        except agent_trials.OverAllowance as exc:
            ctx.notes.append(str(exc))
            if cost > allowance.per_week:
                continue
            break
        tested.append(str(card_path))
        summary: dict[str, Any] = {
            "card": found.card,
            "path": str(card_path),
            "trials": found.trials_spent,
            "window": found.research_window,
            "screens": [s.__dict__ for s in found.screens],
            "stopped": found.stopped,
            "backtests": [],
        }
        survivors = 0
        for bt in found.backtests:
            days = [date.fromisoformat(d) for d in bt.days]
            attacked = skeptic.attacks(days, bt.values, _report(bt))
            verdicts = skeptic.verdicts(attacked)
            critical = [v.title for v in verdicts if v.severity == "critical"]
            ok = bt.robust_sharpe > 0 and not critical
            survivors += ok
            summary["backtests"].append(
                {
                    "label": bt.label,
                    "robust_sharpe": bt.robust_sharpe,
                    "annualised": bt.annualised,
                    "max_drawdown": bt.max_drawdown,
                    "critical": critical,
                    "survived": ok,
                }
            )
        results.append(summary)
        ctx.write(
            f"{found.card}.json", {**summary, "curves": [_report(b) for b in found.backtests]}
        )
        lines = [f"research window: {found.research_window}", f"trials spent: {found.trials_spent}"]
        lines += [
            f"IC {s.feature}: {s.mean_ic:+.4f} (t {s.t_stat:.2f}, {s.periods} periods) "
            + ("passed" if s.passed else "failed")
            for s in found.screens
        ]
        for b in summary["backtests"]:
            lines.append(
                f"{b['label']}: robust Sharpe {b['robust_sharpe']:.2f}, {b['annualised']:+.1%} a year, "
                f"max drawdown {b['max_drawdown']:.1%}"
                + (f"; skeptic: {'; '.join(b['critical'])}" if b["critical"] else "")
            )
        if survivors:
            lines.append(
                "Before the gate: approve the draft (make paper-agent-approve DRAFT=...), register it, "
                "then make gate H=<id>. The gate's noise bar already includes these trials."
            )
        items.append(
            Item(
                kind="finding",
                title=(
                    f"{found.card}: {survivors} configuration(s) survived"
                    if survivors
                    else f"{found.card}: {found.stopped or 'no configuration survived'}"
                )[:200],
                body="\n".join(lines),
                severity="warn" if survivors else "info",
                needs_approval=bool(survivors),
                ref=str(card_path),
                data={"card": found.card, "survivors": survivors, "trials": found.trials_spent},
            )
        )
    spent = sum(r["trials"] for r in results)
    return WorkerResult(
        f"{len(results)} card(s) tested, {spent} trial(s) spent, "
        f"{agent_trials.left_this_week(allowance, ctx.now)} left this week; "
        f"{sum(i.data.get('survivors', 0) for i in items)} survivor(s) for you",
        items,
        data={"tested": tested, "results": results, "allowance": allowance.per_week},
    )
