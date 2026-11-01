"""The idea lab: many ideas a day, a memory of what each showed, and a handoff to research (ADR-089, ADR-110).

    every research draft not yet tested (all recent runs, not only the latest)
    + its own ideas: formula cards from config/idea_families.yaml, planned from
      its memory (flips, window variants, combinations, then fresh templates
      by Thompson sampling), plus a few the model proposes if it has budget
        -> agent_trials.test_card: IC screen per feature, then a Tier A backtest
           (trials logged first; the panel read once and cut at the card's holdout)
        -> skeptic's attacks on each backtest
        -> memory: one experience per card (research/idea_memory.py)
        -> the operator's inbox: survivors, with the command that takes one to the gate
        -> feedback for the research agent: families working and dead, features
           drafts asked for that the library lacks, topics to search next

Until 2026-11-01 it read only the research agent's latest run, had no ideas of
its own and no memory, and its first run tested nothing (HISTORY). It does not
change a card after writing it, tune a parameter after a result, run the gate
or read the holdout. A survivor is a candidate for the operator, not a result.

It reads the whole price panel, so it runs from the command line
(`make agent NAME=lab`) or the daily batch (`make agents-ideas`), never from
the web page, which would hold a second copy of the panel in the API's memory.
"""

from __future__ import annotations

import time
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from eulerlab.agents.runtime import Context, Item, WorkerResult, ist_day, outputs
from eulerlab.features import formula
from eulerlab.research import idea_generator, idea_memory
from eulerlab.research.idea_memory import Experience, Source

DEFAULT_IDEAS = 30
DEFAULT_DRAFTS = 10
DEFAULT_MINUTES = 90
DEFAULT_MODEL_IDEAS = 6


def _card_features(card_path: Path) -> list[str]:
    spec = yaml.safe_load(card_path.read_text(encoding="utf-8")) or {}
    return sorted(
        {str(c.get("feature")) for c in spec.get("configurations") or [] if c.get("feature")}
    )


def candidates(ctx: Context) -> list[Path]:
    """Every research draft card from recent runs that is not a repeat, newest run first.

    A draft marked as waiting for data is still a candidate: whether the lab can
    build it is decided by the library (`cost_of`), not by words in its abstract.
    """
    given = str(ctx.args.get("card") or "").strip()
    if given:
        path = Path(given)
        return [path / "card.yaml" if path.is_dir() else path]
    out: list[Path] = []
    for research in outputs("research", ctx.root, limit=50):
        if research.status != "ok":
            continue
        for item in research.items:
            if item.kind != "draft" or not item.ref or item.data.get("repeat_of"):
                continue
            card = Path(item.ref) / "card.yaml"
            if card.exists() and card not in out:
                out.append(card)
    return out


def already_tested(ctx: Context, memory: list[Experience] | None = None) -> set[str]:
    seen: set[str] = set()
    for output in outputs(ctx.name, ctx.root, limit=50):
        seen.update(str(c) for c in output.data.get("tested", []))
    for e in memory if memory is not None else idea_memory.load(ctx.root):
        if e.path:
            seen.add(e.path)
    return seen


def _report(bt: Any) -> dict[str, Any]:
    return {"equity": {"days": bt.days, "values": bt.values}, "summary": {"costs": bt.costs}}


def _model_ideas(
    ctx: Context,
    families: idea_generator.Families,
    taken: set[str],
    lessons_text: str,
    count: int,
) -> list[idea_generator.Idea]:
    """A few formulas from the model, each parsed by the formula language. Never fatal."""
    if count <= 0 or not ctx.can_ask():
        return []
    system, user = idea_generator.model_prompt(families, taken, lessons_text, count=count)
    try:
        answer = ctx.ask(system, user)
    except Exception as exc:  # a provider outage must not stop the day's tests
        ctx.notes.append(f"no model ideas today: {type(exc).__name__}: {str(exc)[:160]}")
        return []
    found = idea_generator.proposals(answer, families, taken, limit=count)
    ctx.notes.append(f"the model proposed {len(found)} usable formula(s)")
    return found


def run(ctx: Context) -> WorkerResult:
    from eulerlab.agents.workers import skeptic
    from eulerlab.features import panel
    from eulerlab.quality import contract
    from eulerlab.research import agent_trials, codegen, scout

    allowance = agent_trials.load_allowance()
    if agent_trials.left_this_week(allowance, ctx.now) == 0:
        return WorkerResult(
            f"this week's {allowance.per_week} agent trials are spent; nothing tested",
            status="skipped",
        )
    try:
        contract.guard(["Price panel"], log=ctx.notes.append)
    except contract.LowGrade as exc:
        return WorkerResult(str(exc).splitlines()[0], status="refused")

    def option(key: str, default: int) -> int:
        """A command-line value, else the definition's, else the default. 0 is a value."""
        for source in (ctx.args, ctx.options):
            value = source.get(key)
            if value is not None and str(value).strip() != "":
                return int(value)
        return default

    day = date.fromisoformat(ist_day(ctx.now))
    memory = idea_memory.load(ctx.root)
    families = idea_generator.load_families()
    tested_before = already_tested(ctx, memory)
    max_drafts = option("max_cards", DEFAULT_DRAFTS)
    deadline = time.monotonic() + 60 * option("max_minutes", DEFAULT_MINUTES)

    # What to test: research drafts first (they carry a paper), then the lab's own ideas.
    queue: list[tuple[Path, str, Source, str]] = []
    missing: set[str] = set()
    for card_path in candidates(ctx):
        if str(card_path) in tested_before:
            continue
        unknown = [f for f in _card_features(card_path) if not formula.is_known(f)]
        missing.update(unknown)
        if len([q for q in queue if q[2] == "research"]) < max_drafts:
            queue.append((card_path, "research", "research", ""))
    plan = idea_generator.Plan()
    if not ctx.args.get("card"):
        n = option("max_ideas", DEFAULT_IDEAS)
        plan = idea_generator.plan(families, memory, n=n, day=day, min_t=allowance.min_t)
        taken = idea_memory.tested_features(memory) | {i.feature for i in plan.ideas}
        lessons_text = idea_memory.guidance(
            idea_memory.feedback(memory, {k: f.search for k, f in families.families.items()})
        )
        plan.ideas += _model_ideas(
            ctx, families, taken, lessons_text, option("model_ideas", DEFAULT_MODEL_IDEAS)
        )
        written = idea_generator.write_cards(
            plan.ideas,
            families,
            day=day,
            holdout_starts=scout.HOLDOUT_START,
            folder=idea_generator.FOLDER,
        )
        queue += [(path, idea.family, idea.source, idea.parent) for idea, path in written]
        ctx.step(
            f"{len(queue)} card(s) queued: {len(queue) - len(written)} research draft(s), "
            f"{len(written)} of the lab's own ideas"
        )

    rows_cache: list[Any] = []

    def read_rows() -> list[Any]:
        """The panel, read once for the whole run rather than once per card."""
        if not rows_cache:
            rows_cache.append(panel.read_panel())
        return list(rows_cache[0])

    items: list[Item] = []
    tested: list[str] = []
    results: list[dict[str, Any]] = []
    digest: list[str] = []
    out_of_time = 0
    for card_path, family, source, parent in queue:
        if time.monotonic() > deadline:
            out_of_time += 1
            continue
        try:
            cost, features, _ = agent_trials.cost_of(card_path)
        except (codegen.UnknownPrimitive, OSError, ValueError) as exc:
            ctx.notes.append(
                f"{card_path.parent.name}: not buildable from the library: {str(exc)[:160]}"
            )
            continue
        ctx.step(f"Testing {card_path.parent.name}: IC screen first, backtest only if it passes")
        try:
            found = agent_trials.test_card(
                card_path, allowance=allowance, now=ctx.now, read_rows=read_rows
            )
        except agent_trials.OverAllowance as exc:
            ctx.notes.append(str(exc))
            if allowance.per_week is not None and cost > allowance.per_week:
                continue
            break
        tested.append(str(card_path))
        summary: dict[str, Any] = {
            "card": found.card,
            "path": str(card_path),
            "family": family,
            "source": source,
            "trials": found.trials_spent,
            "window": found.research_window,
            "screens": [s.__dict__ for s in found.screens],
            "stopped": found.stopped,
            "backtests": [],
        }
        survivors = 0
        best: dict[str, Any] | None = None
        for bt in found.backtests:
            days = [date.fromisoformat(d) for d in bt.days]
            attacked = skeptic.attacks(days, bt.values, _report(bt))
            verdicts = skeptic.verdicts(attacked)
            critical = [v.title for v in verdicts if v.severity == "critical"]
            ok = bt.robust_sharpe > 0 and not critical
            survivors += ok
            row = {
                "label": bt.label,
                "robust_sharpe": bt.robust_sharpe,
                "annualised": bt.annualised,
                "max_drawdown": bt.max_drawdown,
                "critical": critical,
                "survived": ok,
            }
            summary["backtests"].append(row)
            if best is None or bt.robust_sharpe > best["robust_sharpe"]:
                best = row
        results.append(summary)
        idea_memory.append(
            ctx.root,
            Experience(
                at=ctx.now.isoformat(timespec="seconds"),
                day=day.isoformat(),
                card=found.card,
                path=str(card_path),
                family=family,
                source=source,
                parent=parent,
                features=features,
                ic={s.feature: s.mean_ic for s in found.screens},
                t={s.feature: s.t_stat for s in found.screens},
                screened_in=found.screened_in,
                robust_sharpe=best["robust_sharpe"] if best else None,
                annualised=best["annualised"] if best else None,
                max_drawdown=best["max_drawdown"] if best else None,
                survived=bool(survivors),
                critical=best["critical"] if best else [],
                trials=found.trials_spent,
                stopped=found.stopped,
            ),
        )
        ctx.write(
            f"{found.card}.json", {**summary, "curves": [_report(b) for b in found.backtests]}
        )
        ic_text = ", ".join(f"IC {s.mean_ic:+.3f} (t {s.t_stat:.1f})" for s in found.screens)
        digest.append(
            f"{'SURVIVED' if survivors else ('passed screen' if found.screened_in else 'screened out')}"
            f" · {family} · {', '.join(features)[:90]} · {ic_text}"
            + (f" · robust Sharpe {best['robust_sharpe']:.2f}" if best else "")
        )
        if not survivors:
            continue
        lines = [
            f"family: {family} ({source})",
            f"research window: {found.research_window}",
            f"trials spent: {found.trials_spent}",
        ]
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
        lines.append(
            "Before the gate: approve the draft (make paper-agent-approve DRAFT=...) or copy the card "
            "into hypotheses/, register it, then make gate H=<id>. The gate's noise bar already "
            "includes these trials."
        )
        items.append(
            Item(
                kind="finding",
                title=f"{found.card}: {survivors} configuration(s) survived"[:200],
                body="\n".join(lines),
                severity="warn",
                needs_approval=True,
                ref=str(card_path),
                data={
                    "card": found.card,
                    "family": family,
                    "survivors": survivors,
                    "trials": found.trials_spent,
                },
            )
        )

    memory = idea_memory.load(ctx.root)
    fb = idea_memory.feedback(
        memory, {k: f.search for k, f in families.families.items()}, missing_features=missing
    )
    spent = sum(r["trials"] for r in results)
    passed = sum(1 for r in results if r["screens"] and all(s["passed"] for s in r["screens"]))
    survived = sum(i.data.get("survivors", 0) for i in items)
    if out_of_time:
        ctx.notes.append(
            f"{out_of_time} card(s) left for tomorrow: the run reached its {option('max_minutes', DEFAULT_MINUTES)}-minute limit"
        )
    if results:
        items.append(
            Item(
                kind="finding",
                title=f"Today's lab: {len(results)} tested, {passed} passed the IC screen, {survived} survived"[
                    :200
                ],
                body="\n".join(
                    [
                        *digest,
                        "",
                        "What the lab has learned so far:",
                        *[f"- {x}" for x in fb.lessons],
                    ]
                ),
                data={"tested": len(results), "passed": passed, "survived": survived},
            )
        )
    if fb.missing_features:
        items.append(
            Item(
                kind="proposal",
                title=f"Drafts asked for {len(fb.missing_features)} feature(s) the library lacks"[
                    :200
                ],
                body=(
                    "Research drafts named these, so they could not be tested: "
                    + ", ".join(fb.missing_features)
                    + ". Each needs a formula or a new tested primitive (codegen.py)."
                ),
                data={"features": fb.missing_features},
            )
        )
    return WorkerResult(
        f"{len(results)} card(s) tested, {spent} trial(s) spent, "
        + (
            f"{agent_trials.left_this_week(allowance, ctx.now)} left this week; "
            if allowance.per_week is not None
            else "no weekly limit; "
        )
        + f"{passed} passed the IC screen; {survived} survivor(s) for you",
        items,
        data={
            "tested": tested,
            "results": results,
            "allowance": allowance.per_week,
            "planned": [i.feature for i in plan.ideas],
            "feedback": fb.model_dump(),
        },
    )
