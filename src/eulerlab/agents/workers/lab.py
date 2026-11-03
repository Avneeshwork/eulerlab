"""The idea lab: many ideas a day, a memory of what each showed, and a handoff to research (ADR-089, ADR-111).

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

import math
import os
import statistics
import time
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from eulerlab.agents import doctor
from eulerlab.agents.runtime import Context, Item, WorkerResult, ist_day, outputs
from eulerlab.features import formula
from eulerlab.research import idea_generator, idea_memory
from eulerlab.research.idea_memory import Experience, Source

DEFAULT_IDEAS = 30
DEFAULT_DRAFTS = 10
DEFAULT_MINUTES = 90
DEFAULT_MODEL_IDEAS = 6


def _floor(card_path: Path) -> float:
    """The card's liquidity floor: the lowest `min_turnover` across its configurations."""
    spec = yaml.safe_load(card_path.read_text(encoding="utf-8")) or {}
    floors = [float(c.get("min_turnover") or 0) for c in spec.get("configurations") or []]
    return min(floors, default=0.0)


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


_NIFTY: list[dict[date, float]] = []


def nifty() -> dict[date, float]:
    """NIFTYBEES daily returns, read once per process; empty when the panel lacks it."""
    if not _NIFTY:
        try:
            from eulerlab.research.strategy_map import nifty_returns

            _NIFTY.append(nifty_returns())
        except (OSError, ValueError):
            _NIFTY.append({})
    return _NIFTY[0]


def excess_sharpe(days: list[str], values: list[float], market: dict[date, float]) -> float | None:
    """Annualised Sharpe of the daily return over Nifty, on the days both have.

    A long-only top-30 book earns the market's return too, so a positive Sharpe
    alone says little: before 2026-11-01 that was the lab's whole survival test.
    None when Nifty is not held or fewer than 250 days overlap.
    """
    diffs: list[float] = []
    for i in range(1, len(values)):
        d = date.fromisoformat(days[i])
        if d in market and values[i - 1] > 0:
            diffs.append(values[i] / values[i - 1] - 1.0 - market[d])
    if len(diffs) < 250:
        return None
    sd = statistics.pstdev(diffs)
    return round(statistics.fmean(diffs) / sd * math.sqrt(252), 3) if sd > 0 else None


LOCK = "lab.running"
"""Under the agents' root. Held while a lab run is testing."""
STALE_HOURS = 4
"""A lock older than this is from a run that died without cleaning up, and is taken over."""


def run(ctx: Context) -> WorkerResult:
    """One lab run at a time (2026-11-01: two overlapping runs tested the same idea twice,
    spending its trials twice). A second run says so and stops."""
    lock = ctx.root / LOCK
    ctx.root.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        try:
            age = time.time() - lock.stat().st_mtime
        except FileNotFoundError:  # the other run finished between the two calls
            age = STALE_HOURS * 3600.0
        if age < STALE_HOURS * 3600:
            started = lock.read_text(encoding="utf-8").strip() or "earlier"
            return WorkerResult(
                f"another idea lab run is testing (started {started}); this one stopped "
                "so no idea is tested, and no trial spent, twice",
                status="skipped",
            )
        lock.unlink(missing_ok=True)
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(ctx.now.isoformat(timespec="seconds"))
    try:
        return _run(ctx)
    finally:
        lock.unlink(missing_ok=True)


def _run(ctx: Context) -> WorkerResult:
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
    families = idea_generator.load_families()
    everything = idea_memory.load(ctx.root)
    tested_before = already_tested(ctx, everything)
    memory = idea_memory.usable(everything, families.min_turnover)
    max_drafts = option("max_cards", DEFAULT_DRAFTS)
    deadline = time.monotonic() + 60 * option("max_minutes", DEFAULT_MINUTES)

    # What to test: research drafts first (they carry a paper), then the lab's own ideas.
    queue: list[tuple[Path, str, Source, str]] = []
    missing: set[str] = set()
    unbuildable: list[dict[str, Any]] = []
    for card_path in candidates(ctx):
        if str(card_path) in tested_before:
            continue
        unknown = [f for f in _card_features(card_path) if not formula.is_known(f)]
        missing.update(unknown)
        if unknown:
            # For the engineering agent: the named signals the library lacks (ADR-127).
            # Recorded here, where the card is skipped (HISTORY #67: it was recorded
            # only at a later step these cards never reach, so none was handed on).
            unbuildable.append(
                {
                    "card": str(card_path),
                    "features": [f for f in unknown if not f.startswith(formula.PREFIX)],
                    "source": "research",
                }
            )
        if unknown or not _card_features(card_path):
            # Not buildable: listed once in the feedback, never given a slot (2026-11-01:
            # unbuildable drafts were re-noted every run and could crowd out real ones).
            continue
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
            # For the engineering agent: the named signals the library lacks (ADR-127).
            unbuildable.append(
                {
                    "card": str(card_path),
                    "features": [
                        f
                        for f in _card_features(card_path)
                        if not f.startswith(formula.PREFIX) and not formula.is_known(f)
                    ],
                    "source": source,
                }
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
            excess = excess_sharpe(bt.days, bt.values, nifty())
            beats = excess is None or excess > 0
            if bt.robust_sharpe > doctor.SUSPECT_SHARPE:
                # Too good to be true for a long-only daily rule: the doctor flags it for
                # investigation, and it is not called a survivor (ADR-113).
                critical = [*critical, f"robust Sharpe {bt.robust_sharpe:.1f} is too high to trust"]
            ok = bt.robust_sharpe > 0 and not critical and beats
            survivors += ok
            row = {
                "label": bt.label,
                "robust_sharpe": bt.robust_sharpe,
                "excess_sharpe_vs_nifty": excess,
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
                excess_sharpe=best["excess_sharpe_vs_nifty"] if best else None,
                survived=bool(survivors),
                critical=best["critical"] if best else [],
                trials=found.trials_spent,
                stopped=found.stopped,
                min_turnover=_floor(card_path),
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
            "Approve this to send it to the gate: it is registered in hypotheses/, validated and "
            "gated, and the verdict shows under Gate runs (ADR-116). The gate's noise bar already "
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

    memory = idea_memory.usable(idea_memory.load(ctx.root), families.min_turnover)
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
            "unbuildable": unbuildable,
            "results": results,
            "allowance": allowance.per_week,
            "planned": [i.feature for i in plan.ideas],
            "feedback": fb.model_dump(),
        },
    )
