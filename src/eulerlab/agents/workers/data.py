"""The data agent: is the data there, dated, and correct — and if not, what fixes it.

One pass, in this order, cheapest first:

1. **Grade every dataset** against the quality contract (`quality/contract.py`)
   and save the grades for the knowledge agent and the control room.
2. **Freshness** from the Data coverage table: anything behind, stale or
   missing, with the fix the table names.
3. **Last night's feed**: any step that failed in the last day
   (`data/derived/timings.jsonl`). A parse error is called out as a possible
   change of format at the source, because that is what a renamed column or
   a new file layout looks like from here.
4. **Scheduled jobs**: any launchd job whose last run failed.
5. **Data requests** from other agents (the research agent's "this idea needs
   data we do not hold"): matched against the register. Known and graded →
   answered; unknown → a proposal in the operator's inbox, because acquiring a
   new source is the operator's decision.
6. **Optional**, off unless switched on in its definition: re-run the allowed
   feed steps for stale datasets (`agents/jobs.py`), and download a few files
   back from B2 to prove the backup restores (`quality/restore_check.py`).

No model is needed for any of this, and none is used.
"""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Any

from eulerlab import timings
from eulerlab.agents import jobs
from eulerlab.agents.runtime import Context, Item, WorkerResult, latest_output
from eulerlab.quality import contract

CHECK_WORDS = {
    "registered": "Not in the list of known sources",
    "provenance": "Where it comes from is not written down",
    "fingerprint": "No downloaded files on record to check",
    "sense": "The numbers failed a sanity check (duplicates, empty or missing days)",
    "quarantine": "A file is held back as suspect",
    "built from": "It is built from a dataset that is not good enough",
    "point in time": "The source cannot say when each value became known",
}
"""Each quality check, said as the problem a trader would see."""

FORMAT_HINTS = ("KeyError", "column", "parse", "Unexpected", "JSONDecodeError", "header")


def _coverage_rows() -> list[Any]:
    from eulerlab.ingest import coverage

    return list(coverage.table())


def _jobs_text() -> str:
    from eulerlab import telegram_words

    return telegram_words.jobs()


def run(ctx: Context) -> WorkerResult:
    items: list[Item] = []
    ctx.step("Reading data coverage and grading every dataset")
    rows = _coverage_rows()
    grades = contract.grade_all(coverage=lambda: rows)
    contract.save(grades)
    ctx.step(f"Graded {len(grades)} datasets; checking freshness and last night's jobs")

    for g in grades:
        if g.usable and g.grade in "AB":
            continue
        problem = next(
            (
                f"{CHECK_WORDS.get(c.name, c.name)} ({c.detail})."
                for c in g.checks
                if c.state == "fail"
            ),
            "",
        )
        items.append(
            Item(
                kind="finding",
                title=f"{g.name} is grade {g.grade}",
                body=problem or "below its minimum grade",
                severity="critical" if g.critical else "warn",
                ref="make data-quality",
                data={"grade": g.grade, "min": g.min_grade},
            )
        )

    stale: list[Any] = []
    for row in rows:
        if row.status in ("stale", "missing") or (row.status == "behind" and row.behind > 1):
            stale.append(row)
            items.append(
                Item(
                    kind="alert",
                    title=f"{row.name} is {row.status}",
                    body=f"last {row.last or 'never'}, should reach {row.expected}. Fix: {row.fix}",
                    severity="warn",
                    ref=row.fix,
                )
            )

    since = ctx.now - timedelta(days=1)
    for step in timings.read(since=since):
        if step.get("ok", True):
            continue
        detail = str(step.get("detail", ""))
        hint = any(h in detail for h in FORMAT_HINTS)
        items.append(
            Item(
                kind="alert",
                title=f"{step.get('job')} failed",
                body=(
                    detail
                    + (
                        " — this looks like the source changed its format; read the file before re-running."
                        if hint
                        else ""
                    )
                ),
                severity="critical" if hint else "warn",
            )
        )

    try:
        listed = _jobs_text()
    except Exception as exc:  # launchd may not exist (a Linux box); say so, do not fail
        listed = f"could not list jobs: {type(exc).__name__}"
    items.extend(
        Item(kind="alert", title=line.split(":")[0] + " job failed", body=line, severity="warn")
        for line in listed.splitlines()
        if "FAILED" in line
    )

    answers = _answer_requests(ctx, grades)
    items.extend(answers)

    reran: list[str] = []
    if ctx.options.get("auto_rerun") and stale:
        steps: list[str] = []
        for row in stale:
            steps.extend(s for s in row.steps if s not in steps)
        result = jobs.rerun(steps)
        reran = list(result.steps)
        items.append(
            Item(
                kind="finding",
                title=f"re-ran {', '.join(result.steps) or 'nothing'}",
                body=result.detail,
                severity="info" if result.ok else "warn",
            )
        )

    restored = int(ctx.options.get("restore_sample", 0) or 0)
    if restored:
        from eulerlab.quality import restore_check

        try:
            checked = restore_check.check(restored, day=ctx.now.date())
        except Exception as exc:
            checked = []
            items.append(
                Item(
                    kind="alert",
                    title="restore check could not run",
                    body=f"{type(exc).__name__}: {exc}",
                    severity="warn",
                )
            )
        bad = [c for c in checked if not c.ok]
        if checked:
            items.append(
                Item(
                    kind="finding" if not bad else "alert",
                    title=f"restored {len(checked)} file(s) from B2: {len(checked) - len(bad)} match",
                    body="; ".join(f"{c.path}: {c.detail}" for c in bad)
                    or "every byte matched the manifest",
                    severity="critical" if bad else "info",
                )
            )

    counts = {k: sum(1 for g in grades if g.grade == k) for k in "ABCD"}
    asked = str(ctx.args.get("dataset") or "").strip()
    answer = next((i for i in answers if asked and asked[:200].lower() in i.title.lower()), None)
    blocked = [g.name for g in grades if g.critical and not g.usable]
    summary = (
        (f"{answer.title}. " if answer is not None else "")
        + f"{len(grades)} datasets graded: {counts['A'] + counts['B']} clean (A or B), "
        f"{counts['C']} usable with a failed check (C), {counts['D']} not usable (D). "
        f"{len(stale)} behind schedule. "
        + (
            f"Blocking backtests and the trade desk: {', '.join(blocked)}."
            if blocked
            else "Nothing critical is blocked."
        )
    )
    return WorkerResult(
        summary,
        items,
        data={"grades": [g.as_dict() for g in grades], "reran": reran},
    )


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _held(by_name: dict[str, contract.Graded], wanted: str) -> contract.Graded | None:
    """The graded dataset a request names, or None when it names none or several.

    Exact name first. Then by words: "is the bulk deals dataset fresh?" names
    bulk_deals because every word of the name is in the request; the name with
    the most words wins (bulk_deals over deals), and a tie names no one. Last,
    a request that is part of one name ("bulk" in bulk_deals).
    """
    key = wanted.lower().strip()
    if key in by_name:
        return by_name[key]
    asked = _words(key)
    fits = sorted(
        (g for name, g in by_name.items() if _words(name) and _words(name) <= asked),
        key=lambda g: len(_words(g.name)),
        reverse=True,
    )
    if fits and (len(fits) == 1 or len(_words(fits[0].name)) > len(_words(fits[1].name))):
        return fits[0]
    if fits:
        return None
    near = [g for name, g in by_name.items() if key and key in name]
    return near[0] if len(near) == 1 else None


def _answer_requests(ctx: Context, grades: list[contract.Graded]) -> list[Item]:
    """Turn data requests into answers or proposals: other agents' items, and a task's `dataset`."""
    by_name = {g.name.lower(): g for g in grades}
    asked: list[tuple[str, str, str]] = []
    task_wants = str(ctx.args.get("dataset") or "").strip()[:200]
    if task_wants:
        asked.append((f"task {ctx.args.get('task') or 'from the page'}", task_wants, ""))
    for agent in ("research", "skeptic"):
        latest = latest_output(agent, ctx.root)
        if latest is None:
            continue
        for item in latest.items:
            if item.kind == "data_request":
                wanted = str(item.data.get("dataset") or item.title).strip()
                asked.append((agent, wanted, item.body))
    out: list[Item] = []
    seen: set[str] = set()
    for who, wanted, body in asked:
        if not wanted or wanted.lower() in seen:
            continue
        seen.add(wanted.lower())
        held = _held(by_name, wanted)
        if held is not None and held.usable:
            out.append(
                Item(
                    kind="finding",
                    title=f"{wanted}: already held as {held.name}, grade {held.grade}",
                    body=f"asked for by {who}: {body[:200]}",
                    data={"dataset": held.name, "grade": held.grade, "asked_by": who},
                )
            )
            continue
        state = f"held as {held.name} but not usable (grade {held.grade})" if held else "not held"
        out.append(
            Item(
                kind="proposal",
                title=f"Acquire data: {wanted}",
                body=(
                    f"{who} needs it ({state}): {body[:300]}\n"
                    "Approving records that you want it. Adding a source means a register "
                    "entry in config/data_sources.yaml and an ingest step, reviewed like any code."
                ),
                needs_approval=True,
                data={"dataset": wanted, "asked_by": who},
            )
        )
    return out
