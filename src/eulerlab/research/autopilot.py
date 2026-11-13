"""The research autopilot: the manual loop of research 166-176, run every evening (ADR-150).

    1. write    the autopilot agent writes about ten cards as engine specs, half
                intraday and half swing (`agents/workers/autopilot.py`; Claude
                first, then Groq, then fixed rules)
    2. register each card is committed to git before any number is computed:
                the pre-registration. If the commit fails, nothing is screened.
    3. screen   every new card in one pass of `intraday/rule_engine.py`
                (research 173's frame); no trial is spent, as in the manual batches
    4. check    the engine's bias checks; a card with any flag is not gated
    5. gate     `make validate` then `make gate` for each clean survivor, unchanged
                code, while the week's allowance of ledger entries lasts
                (`gate_entries_per_week`); survivors over the allowance wait for
                next week's run, oldest first
    6. keep     PROMOTE or PAPER: a stored library report and a paper deployment
                (paper only, never live money)
    7. write up a research note listing every card, pass or fail; the cards' result
                lines; one commit; one summary in the inbox and on Telegram

What it never does: edit `gates.py` or `mandate.yaml`, read a holdout, tune a
card after its screen, trade live money, or push to GitHub. The operator
approved this loop on 2026-11-07 ("go"); the allowance is theirs to change in
`config/agents/autopilot.yaml`.

It runs as the `autopilot` agent's run (`runtime.run(..., worker=pipeline)`),
so its output, model budget, doctor check and inbox items are the agents'
usual ones. `make agents-autopilot` runs it; `make agent NAME=autopilot`
stops after step 1.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import subprocess
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, timedelta
from functools import partial
from pathlib import Path
from typing import Any

import yaml

from eulerlab import constitution, jobrun
from eulerlab.agents import runtime
from eulerlab.agents.runtime import Context, Item, WorkerResult
from eulerlab.agents.workers import autopilot as writer
from eulerlab.intraday import rule_engine
from eulerlab.research import experiments
from eulerlab.validation import firewall

NAME = "autopilot"
HYPOTHESES = Path("hypotheses")
RESEARCH = Path("docs/RESEARCH")
DEFAULT_ENTRIES_PER_WEEK = 10
ENTRIES_PER_GATE = 2
"""`make validate` and `make gate` each append one ledger entry."""


Git = Callable[[Sequence[str]], tuple[int, str]]


def git(args: Sequence[str]) -> tuple[int, str]:
    done = subprocess.run(["git", *args], capture_output=True, text=True, check=False)
    return done.returncode, (done.stdout + done.stderr).strip()


def commit(paths: Sequence[str], message: str, run_git: Git = git) -> tuple[bool, str]:
    """Commit exactly `paths`; anything else staged in the folder stays staged."""
    code, out = run_git(["add", "--", *paths])
    if code:
        return False, out
    code, out = run_git(["commit", "--only", "-m", message, "--", *paths])
    return code == 0, out


# --- the allowance -----------------------------------------------------------------------


def gate_log(root: Path) -> Path:
    return root / NAME / "gates.jsonl"


def entries_this_week(root: Path, now: datetime) -> int:
    path = gate_log(root)
    if not path.exists():
        return 0
    since = now - timedelta(days=7)
    used = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if datetime.fromisoformat(row["at"]) >= since:
            used += int(row.get("entries", ENTRIES_PER_GATE))
    return used


def gated_already(root: Path) -> set[str]:
    path = gate_log(root)
    if not path.exists():
        return set()
    return {json.loads(line)["hypothesis"] for line in path.read_text().splitlines() if line}


def waiting(root: Path) -> list[str]:
    """Clean survivors of earlier runs not yet gated, oldest first."""
    done = gated_already(root)
    out: list[str] = []
    for output in reversed(runtime.outputs(NAME, root, limit=50)):
        for h in output.data.get("survivors") or []:
            if h not in done and h not in out:
                out.append(h)
    return out


# --- the gate ----------------------------------------------------------------------------

VERDICTS = {0: "PROMOTE", 3: "PAPER", 1: "KILL"}


def gate_one(hypothesis: str, out_dir: Path) -> dict[str, Any]:
    """`make validate H=...` then `make gate H=...`, in-process, output kept in the run folder."""
    from eulerlab import gate_run
    from eulerlab.validation import run as validate

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = validate.main(["--hypothesis", hypothesis])
        verdict = "VALIDATE FAILED"
        if code == 0:
            verdict = VERDICTS.get(gate_run.main(["--hypothesis", hypothesis]), "KILL")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"gate-{hypothesis}.txt").write_text(buffer.getvalue(), encoding="utf-8")
    return {"hypothesis": hypothesis, "verdict": verdict, "entries": 2 if code == 0 else 1}


def gate_settled(hypothesis: str, since: date) -> dict[str, Any] | None:
    """What the trial ledger says a gate step did, for a run that died before noting it.

    None when the ledger has no entry for the card since `since`: nothing was
    spent and the step may run. A validation with no gate verdict after it is
    reported as it is, with the one entry it used; the card is not gated again
    on its own, and a dead letter asks for a look.
    """
    from eulerlab.validation import ledger

    mine = [
        e
        for e in ledger.read()
        if e.subject == hypothesis and e.logged_at[:10] >= since.isoformat()
    ]
    if not mine:
        return None
    for entry in reversed(mine):
        if entry.kind == "gate":
            verdict = str(entry.outcome.get("verdict", "KILL"))
            return {"hypothesis": hypothesis, "verdict": verdict, "entries": len(mine)}
    jobrun.dead_letter(
        NAME,
        f"gate:{hypothesis}",
        "the run died after validation and before the gate; the ledger has the validation only",
    )
    return {"hypothesis": hypothesis, "verdict": "VALIDATE ONLY", "entries": len(mine)}


def keep(hypothesis: str) -> dict[str, str]:
    """A stored library report and a paper deployment for a PROMOTE or PAPER card."""
    from eulerlab.deploy import ladder
    from eulerlab.research import library_reports

    done: dict[str, str] = {}
    try:
        library_reports.add_recommended([library_reports.store_one(hypothesis)])
        done["report"] = "stored"
    except Exception as exc:  # a report failure must not lose the verdict
        done["report"] = f"failed: {type(exc).__name__}: {exc}"[:200]
    try:
        done["paper"] = ladder.start_paper(hypothesis, datetime.now(UTC).date())
    except constitution.NotAllowed as exc:
        done["paper"] = f"not deployed: {exc}"
    return done


# --- one bet or a new one -------------------------------------------------------------

SAME_BET = 0.5
"""Correlation of daily net returns at which a rule is called the same bet as a pass.
ASSUMPTION: A-122 — chosen by hand on 2026-11-08, after the first batch's three
passes all moved with H-0161."""


def correlation(a: dict[date, float], b: dict[date, float]) -> float | None:
    days = sorted(set(a) & set(b))
    if len(days) < 60:
        return None
    x, y = [a[d] for d in days], [b[d] for d in days]
    mx, my = sum(x) / len(x), sum(y) / len(y)
    sx = sum((v - mx) ** 2 for v in x) ** 0.5
    sy = sum((v - my) ** 2 for v in y) ** 0.5
    if not sx or not sy:
        return None
    return float(sum((p - mx) * (q - my) for p, q in zip(x, y, strict=True)) / (sx * sy))


def peers(engine: rule_engine.Engine, root: Path) -> dict[str, dict[date, float]]:
    """Daily net returns of every daily-bar stock rule that passed the gate.

    H-0161 and H-0162 are research 173's own code; H-0168 and every engine card the
    autopilot gated PROMOTE or PAPER run through the engine.
    """
    from eulerlab.intraday import daily_universe_screen as du

    data = engine.data
    out: dict[str, dict[date, float]] = {}
    window = [d for d in data.sessions if rule_engine.FIRST <= d <= data.end]
    out["H-0161"] = rule_engine.daily(
        du.h0161_trades(data.panel, data.sessions, data.liquid, data.delivery), window
    )
    swings = du.h0162_positions(data.panel, data.sessions, data.liquid, data.promoters)
    out["H-0162"] = rule_engine.daily([p for s in swings for p in s.pieces()], window)
    passed = {"H-0168"}
    path = gate_log(root)
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if row.get("verdict") in ("PROMOTE", "PAPER"):
                passed.add(row["hypothesis"])
    for h in sorted(passed):
        spec = rule_engine.card_spec(h) or rule_engine.reference_specs().get(h)
        if spec is not None:
            out[h] = rule_engine.daily(engine.pieces(spec), engine.window(spec))
    return out


def same_bet(
    engine: rule_engine.Engine,
    screens: dict[str, dict[str, Any]],
    known: dict[str, dict[date, float]],
) -> None:
    """Flag each clean rule that moves with a pass, or with a better clean rule tonight."""
    taken = dict(known)
    order = sorted(
        (h for h, s in screens.items() if s["clean"]),
        key=lambda h: -(screens[h]["net"]["sharpe"] or 0.0),
    )
    for h in order:
        spec = rule_engine.card_spec(h)
        assert spec is not None
        mine = rule_engine.daily(engine.pieces(spec), engine.window(spec))
        found = [(c, p) for p, r in taken.items() if (c := correlation(mine, r)) is not None]
        worst = max(found, default=(None, ""))
        flag = worst[0] is not None and worst[0] >= SAME_BET
        screens[h]["checks"].append(
            {
                "check": "a new bet",
                "value": round(worst[0], 3) if worst[0] is not None else None,
                "with": worst[1],
                "flag": flag,
                "why": f"daily returns correlate {SAME_BET} or more with a pass",
            }
        )
        if flag:
            screens[h]["clean"] = False
        else:
            taken[h] = mine


# --- the experiment store and the firewall (ADR-172) -----------------------------------


def family_of(spec: rule_engine.Rule) -> str:
    """Kind and the signals the rule conditions on: one cell of the coverage map."""
    if isinstance(spec, rule_engine.RuleSpec):
        return f"{spec.kind}:{'+'.join(sorted({c.signal for c in spec.when}))}"
    return f"{spec.kind}:{'+'.join(getattr(spec, 'complexity', {}).get('fields', []))}"


def remember(
    hypothesis: str,
    spec: rule_engine.Rule,
    screen: dict[str, Any],
    daily: dict[date, float],
    end: date,
    now: datetime,
) -> None:
    """Record the screen with its daily returns, and put the firewall's numbers on it.

    The others are read before this rule is added, so it is judged against the
    search that came before it. Information only: nothing here changes `clean`.
    """
    others = experiments.universe(skip=[spec.fingerprint()])
    found = firewall.assess(daily, spec.fingerprint(), others)
    screen["firewall"] = found.as_dict()
    experiments.record(
        purpose="screen",
        hypothesis=hypothesis,
        fingerprint=spec.fingerprint(),
        family=family_of(spec),
        first=spec.first,
        end=end,
        metrics={
            "count": screen.get("count"),
            "net_sharpe": (screen.get("net") or {}).get("sharpe"),
            "passes_screen": screen.get("passes_screen"),
            "clean": screen.get("clean"),
            **found.as_dict(),
        },
        daily=daily,
        asked_by=NAME,
        now=now,
    )


# --- the write-up ------------------------------------------------------------------------


def result_line(screen: dict[str, Any], gate: dict[str, Any] | None, day: date) -> str:
    per = screen["per_bps"]
    flags = [
        c["check"] + (f" (moves with {c['with']}, {c['value']})" if c.get("with") else "")
        for c in screen["checks"]
        if c["flag"]
    ]
    text = (
        f"Autopilot screen {day.isoformat()}: {screen['count']} "
        f"{'trades' if screen['kind'] == 'intraday' else 'positions'} "
        f"{screen['first']} to {rule_engine.END}; net {per.get('net_mean')} bps each; net Sharpe "
        f"{screen['net']['sharpe']}, halves {screen['halves']['first']['sharpe']} / "
        f"{screen['halves']['second']['sharpe']}, {screen['net_at_2x_costs']['sharpe']} at 2x "
        f"costs. "
    )
    if flags:
        text += f"Flagged: {', '.join(flags)}. "
    if not screen["passes_screen"]:
        text += "Screen fail; not gated."
    elif flags:
        text += "Not gated (bias check)."
    elif gate is None:
        text += "Clean survivor; waiting for the week's gate allowance."
    else:
        text += f"Gate: {gate['verdict']}."
    return text


def set_result(hypothesis: str, line: str, root: Path = HYPOTHESES) -> None:
    path = root / f"{hypothesis}.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw["result"] = line
    path.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True, width=100))


def next_note(day: date, root: Path = RESEARCH) -> Path:
    numbers = [int(p.name[:3]) for p in root.glob("[0-9][0-9][0-9]-*.md")]
    return root / f"{max(numbers, default=0) + 1:03d}-autopilot-{day.isoformat()}.md"


def note(
    path: Path,
    day: date,
    cards: Sequence[dict[str, Any]],
    screens: dict[str, dict[str, Any]],
    gates: dict[str, dict[str, Any]],
    kept: dict[str, dict[str, str]],
    model: str,
    dropped: Sequence[str],
) -> str:
    number = path.name[:3]
    lines = [
        f"# {number} — Research autopilot, {day.isoformat()}",
        "",
        f"**Question.** The nightly autopilot's batch (ADR-150): {len(cards)} rules written by "
        f"{model or 'fixed rules'}, pre-registered and committed before any run, screened in "
        "research 173's frame, gated only when clean.",
        "",
        "| Card | Kind | Rule | Count | Net bps | Net Sharpe | Halves | 2x costs | Flags | Verdict |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for c in cards:
        h, s = c["id"], screens.get(c["id"])
        if s is None:
            lines.append(f"| {h} | {c['kind']} | {c['rule']} | | | | | | | not screened |")
            continue
        flags = (
            ", ".join(
                x["check"] + (f" ({x['with']} {x['value']})" if x.get("with") else "")
                for x in s["checks"]
                if x["flag"]
            )
            or "none"
        )
        verdict = (
            gates[h]["verdict"]
            if h in gates
            else (
                "survivor, waiting"
                if s["clean"]
                else "screen fail"
                if not s["passes_screen"]
                else "flagged"
            )
        )
        lines.append(
            f"| {h} | {s['kind']} | {s['rule']} | {s['count']} | {s['per_bps'].get('net_mean')} | "
            f"{s['net']['sharpe']} | {s['halves']['first']['sharpe']} / "
            f"{s['halves']['second']['sharpe']} | {s['net_at_2x_costs']['sharpe']} | {flags} | "
            f"{verdict} |"
        )
    older = [h for h in gates if h not in {c["id"] for c in cards}]
    if older:
        lines += [
            "",
            "Earlier survivors gated tonight: "
            + ", ".join(f"{h} {gates[h]['verdict']}" for h in older)
            + ".",
        ]
    walls = {h: s["firewall"] for h, s in screens.items() if s.get("firewall")}
    if walls:
        lines += [
            "",
            "**After the search** (ADR-172, information only). Rules tried so far, the "
            "families they form, the Sharpe the best family of noise would show, the chance "
            "this rule's Sharpe is not noise, and whether it kept half its pre-2024 Sharpe "
            "on 2024 onwards.",
            "",
            "| Card | Rules tried | Families | Noise bar | Deflated Sharpe | Holds on selection |",
            "|---|---|---|---|---|---|",
        ]
        said = {True: "yes", False: "no", None: "too short to say"}
        lines += [
            f"| {h} | {w['rules_tried']} | {w['families']} | {w['noise_bar']} | "
            f"{w['deflated_sharpe']} | {said[w['holds_on_selection']]} |"
            for h, w in walls.items()
        ]
    if kept:
        lines += ["", "**Kept.**"]
        lines += [f"- {h}: report {v.get('report')}; {v.get('paper')}" for h, v in kept.items()]
    if dropped:
        lines += ["", "**Written but dropped before registration** (invalid or a repeat):"]
        lines += [f"- {d}" for d in dropped[:20]]
    lines += [
        "",
        "**Sources.** No web source: the rules come from the library papers named in each "
        "card's `rationale` and `source.paper`. Screen code: `intraday/rule_engine.py`.",
        "",
        "**Confidence.** A screen is one look at 2016-2024 (2021-07 on for deals and results). "
        "Every card here adds to the search the simple gate does not correct for.",
    ]
    text = "\n".join(lines) + "\n"
    path.write_text(text, encoding="utf-8")
    return text


# --- the loop ----------------------------------------------------------------------------


def pipeline(
    ctx: Context, *, run_git: Git = git, data: rule_engine.Data | None = None
) -> WorkerResult:
    day = ctx.now.date()
    rules = constitution.load()
    constitution.require("register_hypothesis", who="the autopilot")
    # Every step's result is kept (ADR-174): a run killed here resumes below, and
    # nothing already written, screened or gated is done a second time.
    job = jobrun.open(
        NAME, day.isoformat(), ledger_used=lambda: entries_this_week(ctx.root, ctx.now)
    )
    found = job.do("write", lambda: writer.write_cards(ctx))
    cards = found["cards"]
    ids = [c["id"] for c in cards]
    if ids and "register" not in job.done:
        ok, out = commit(
            [c["path"] for c in cards],
            f"docs(research): pre-register {ids[0]} to {ids[-1]}, autopilot batch {day} (ADR-150)",
            run_git,
        )
        if not ok:
            return WorkerResult(
                f"{len(ids)} card(s) written but the pre-registration commit failed; nothing "
                f"screened: {out[:200]}",
                status="failed",
                data={"cards": cards},
            )
        job.do("register", lambda: ids)
        ctx.step(f"Pre-registered {len(ids)} card(s) in one commit")
    queue = waiting(ctx.root)
    if not ids and not queue:
        job.finish("no new cards and no survivors waiting")
        return WorkerResult("no new cards and no survivors waiting", data={"cards": []})

    engines: list[rule_engine.Engine] = []

    def engine() -> rule_engine.Engine:
        if not engines:
            engines.append(rule_engine.Engine(data or rule_engine.Data()))
        return engines[0]

    def screen_one(hypothesis: str) -> dict[str, Any]:
        spec = rule_engine.card_spec(hypothesis)
        assert spec is not None
        if engine().data.end > rules.periods.backtest_end:
            msg = f"the screen's data ends {engine().data.end}, inside the forward test"
            raise experiments.SealedPeriod(msg)
        out = engine().screen(spec)
        returns = engine().returns.pop(spec.fingerprint(), None)
        if returns:
            remember(hypothesis, spec, out, returns, engine().data.end, ctx.now)
        return out

    def compare(found: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        same_bet(engine(), found, peers(engine(), ctx.root))
        return found

    screens: dict[str, dict[str, Any]] = {}
    for c in cards:
        if f"screen:{c['id']}" not in job.done:
            ctx.step(f"Screening {c['id']}: {c['rule'][:150]}")
        screens[c["id"]] = job.do(f"screen:{c['id']}", partial(screen_one, c["id"]))
    if any(s["clean"] for s in screens.values()):
        if "same_bet" not in job.done:
            ctx.step("Checking each clean rule against the bets already passed")
        screens = job.do("same_bet", lambda: compare(screens))
    survivors = [h for h in ids if screens[h]["clean"]]

    allowance = min(
        int(ctx.options.get("gate_entries_per_week", DEFAULT_ENTRIES_PER_WEEK)),
        rules.caps.gate_entries_per_week,
    )
    if rules.actions["use_ledger_entry"] != "act":
        ctx.notes.append("the constitution does not let the autopilot gate; survivors wait")
        allowance = 0
    gates: dict[str, dict[str, Any]] = {}
    kept: dict[str, dict[str, str]] = {}

    def note_gate(result: dict[str, Any]) -> bool:
        log = gate_log(ctx.root)
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as handle:
            row = {"at": ctx.now.astimezone(UTC).isoformat(timespec="seconds"), **result}
            handle.write(json.dumps(row) + "\n")
        spec = rule_engine.card_spec(result["hypothesis"])
        if spec is not None:
            experiments.record(
                purpose="gate",
                hypothesis=result["hypothesis"],
                fingerprint=spec.fingerprint(),
                family=family_of(spec),
                first=spec.first,
                end=min(rule_engine.END, rules.periods.backtest_end),
                metrics={"verdict": result["verdict"], "entries": result["entries"]},
                asked_by=NAME,
                now=ctx.now,
            )
        return True

    for h in [*queue, *survivors]:
        step = f"gate:{h}"
        if step not in job.done:
            used = entries_this_week(ctx.root, ctx.now)
            if used + ENTRIES_PER_GATE > allowance:
                ctx.notes.append(f"week's gate allowance used ({used} of {allowance}); {h} waits")
                continue
            ctx.step(f"Gating {h} (validate, then gate)")
        try:
            result = job.do(
                step,
                partial(gate_one, h, ctx.out_dir),
                cost=jobrun.Cost(ledger_entries=ENTRIES_PER_GATE),
                once=True,
                settle=partial(gate_settled, h, day),
            )
        except jobrun.Refused as exc:
            ctx.notes.append(f"{h} waits: {exc}")
            continue
        gates[h] = result
        job.do(f"gate-noted:{h}", partial(note_gate, result))
        if result["verdict"] in ("PROMOTE", "PAPER"):
            kept[h] = job.do(f"keep:{h}", partial(keep, h))

    def write_up() -> str:
        for h, s in screens.items():
            set_result(h, result_line(s, gates.get(h), day))
        for h, g in gates.items():
            if h not in screens:
                path = HYPOTHESES / f"{h}.yaml"
                raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                set_result(
                    h, f"{raw.get('result', '')} Gate {day.isoformat()}: {g['verdict']}.".strip()
                )
        path = next_note(day)
        note(path, day, cards, screens, gates, kept, found.get("model", ""), found["dropped"])
        return str(path)

    note_path = Path(job.do("note", write_up))
    touched = [str(note_path), *[f"hypotheses/{h}.yaml" for h in {*screens, *gates}]]
    ok, out = commit(
        touched, f"docs(research): autopilot results {day} (research {note_path.name[:3]})", run_git
    )
    if not ok:
        ctx.notes.append(f"results written but not committed: {out[:200]}")
    if job.replayed:
        ctx.notes.append(f"resumed {job.id}: {len(job.replayed)} finished step(s) not repeated")

    items = _items(cards, screens, gates, kept, note_path)
    summary = (
        f"{len(ids)} card(s) written and screened ({sum(s['passes_screen'] for s in screens.values())} "
        f"passed the screen, {len(survivors)} clean); gated {len(gates)}: "
        + (", ".join(f"{h} {g['verdict']}" for h, g in gates.items()) or "none")
        + f"; research {note_path.name[:3]}"
    )
    _tell(summary, kept)
    job.finish(summary)
    return WorkerResult(
        summary,
        items=items,
        data={
            "cards": cards,
            "survivors": survivors,
            "gates": list(gates.values()),
            "kept": kept,
            "note": str(note_path),
            "dropped": found["dropped"],
            "net_sharpe": {h: s["net"]["sharpe"] for h, s in screens.items()},
        },
    )


def _items(
    cards: Sequence[dict[str, Any]],
    screens: dict[str, dict[str, Any]],
    gates: dict[str, dict[str, Any]],
    kept: dict[str, dict[str, str]],
    note_path: Path,
) -> list[Item]:
    items = [
        Item(
            kind="finding",
            title=f"Autopilot: {len(cards)} rules screened, {len(gates)} gated"[:200],
            body=note_path.read_text(encoding="utf-8")[:6000],
            ref=str(note_path),
        )
    ]
    for h, v in kept.items():
        items.append(
            Item(
                kind="finding",
                title=f"{h} {gates[h]['verdict']}: paper book and library report"[:200],
                body=f"{screens.get(h, {}).get('rule', '')}\n{v.get('report')}; {v.get('paper')}. "
                "Live money stays your decision.",
                severity="warn",
                needs_approval=True,
                ref=f"hypotheses/{h}.yaml",
            )
        )
    return items


def _tell(summary: str, kept: dict[str, dict[str, str]]) -> None:
    from eulerlab import notify

    if not notify.configured():
        return
    text = "Research autopilot: " + summary
    if kept:
        text += "\nPassed: " + ", ".join(kept) + " (paper books started; live money is yours)."
    with contextlib.suppress(Exception):
        notify.send(text)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agents-autopilot", description=__doc__)
    parser.parse_args(argv)
    output = runtime.run(NAME, worker=pipeline)
    print(f"{output.status}: {output.summary}")
    return 0 if output.status in ("ok", "skipped") else 1


if __name__ == "__main__":
    raise SystemExit(main())
