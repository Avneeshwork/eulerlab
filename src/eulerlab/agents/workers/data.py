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
6. **Download** with the allowed feed steps (`agents/jobs.py`), when
   `auto_rerun` is on: every stale dataset, and from 18:00 IST today's
   files too ("due tonight" until 21:00 means not stale, not "leave it"). A
   dataset only the operator can update (Kite needs that day's login) is a
   "Needs you" item. The card's first line says what was downloaded.
7. **Upkeep** (`upkeep: true`, ADR-132): under the `feed` lock, upload every
   landing tree `make daily` uploads, delete the local files the bucket now
   holds at the same size, then merge each file that differs from the
   bucket's copy into it, rows once, earliest knowledge time
   (`ingest/merge_back.py`), and delete it.
8. **AI help** when something is still wrong after that: one Groq request
   with the failures; its answer is a diagnosis for the operator, a re-run of
   one allowed step, or a task for the Head of Data and Platform. The model
   never runs anything itself.
9. **Optional**: download a few files back from B2 to prove the backup
   restores (`quality/restore_check.py`).

It runs every two hours from 06:00 to 20:00 IST (`make schedule
JOB=data-watch`), as well as in the 08:45 and 16:15 agent runs.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from eulerlab import jobrun, timings
from eulerlab.agents import jobs
from eulerlab.agents.runtime import (
    BudgetSpent,
    Context,
    Item,
    WorkerResult,
    latest_output,
    untrusted,
)
from eulerlab.paths import data_path
from eulerlab.quality import contract

IST = ZoneInfo("Asia/Kolkata")
DUE_UNTIL = 21
"""IST hour until which today's missing data is "due tonight": `make daily`
starts at 19:30 and usually finishes by 20:30."""
TRY_FROM = 18
"""IST hour from which the agent downloads today's NSE files itself instead of
waiting for `make daily`. ASSUMPTION A-014: NSE posts the day's files in the
evening; same-day bhavcopies have landed from 18:00 (2026-11-04). A try before
publication lands nothing and costs a few requests. Knowledge times still use
the deliberately late `bitemporal.provenance` hours, so this cannot leak."""
HELP = """You help the data agent of a small quant research platform keep its data
current and backed up. You get the problems still open after it re-ran the feed steps
it may run and uploaded to the bucket. For the most important problem, say what most
likely caused it and what fixes it. Answer only with JSON:
{"cause": "...", "fix": "...", "action": "rerun" | "head" | "operator" | "wait",
 "step": "<one of the allowed steps, only for rerun>"}
- rerun: the step failed for a passing reason (network, a timeout, the source late)
  and running it once more is likely to work. Only a step from the allowed list.
- head: code or a configuration must change; the Head of Data and Platform should
  give it to an agent.
- operator: only the operator can fix it (a login, a key, a payment, a decision).
- wait: nothing to do until the next run (the source has not published yet).
Never suggest deleting data, editing raw files, or changing the validation gate."""

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


def _behind(row: Any) -> bool:
    return bool(row.status in ("stale", "missing") or (row.status == "behind" and row.behind > 1))


def caught_up(before: Sequence[Any], after: Sequence[Any]) -> list[tuple[str, str]]:
    """(name, old status) of each dataset that was behind before a re-run and is not now."""
    now = {r.name: r for r in after}
    return [(r.name, str(r.status)) for r in before if r.name in now and not _behind(now[r.name])]


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
    due: list[Any] = []
    for row in rows:
        if due_tonight(row, ctx.now):
            due.append(row)
            continue
        if _behind(row):
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

    fetch_items, reran, fetched = _fetch(ctx, stale, due)
    if fetched.get("caught"):
        # A dataset the fetch brought up to date is not a problem, and must not
        # be described to the model as one (2026-11-04, HISTORY #77: the model
        # was told F&O was missing after it had landed).
        caught = set(fetched["caught"])
        items = [
            i
            for i in items
            if not (i.kind == "alert" and any(i.title.startswith(f"{n} is ") for n in caught))
        ]
    items = fetch_items + items

    upkeep: dict[str, Any] = {}
    if ctx.options.get("upkeep"):
        upkeep_items, upkeep = _upkeep(ctx)
        items.extend(upkeep_items)

    problems = [i for i in items if i.kind == "alert" and i.severity in ("warn", "critical")]
    if problems and ctx.options.get("ai_help"):
        items.extend(_ask_for_help(ctx, problems, already=reran))

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
        + f"{fetched['line']} "
        + f"{len(grades)} datasets graded: {counts['A'] + counts['B']} clean (A or B), "
        f"{counts['C']} usable with a failed check (C), {counts['D']} not usable (D). "
        f"{len(stale)} behind schedule"
        + (f", {len(due)} due tonight" if due else "")
        + ". "
        + (f"{upkeep['line']} " if upkeep.get("line") else "")
        + (
            f"Blocking backtests and the trade desk: {', '.join(blocked)}."
            if blocked
            else "Nothing critical is blocked."
        )
    )
    return WorkerResult(
        summary,
        items,
        data={
            "grades": [g.as_dict() for g in grades],
            "reran": reran,
            "due": [r.name for r in due],
            "fetched": fetched,
            "upkeep": upkeep,
        },
    )


def fetch_now(row: Any, now: datetime) -> bool:
    """Today's data that NSE has most likely published by now: worth a try.

    Every step skips what is landed and reports what it could not get, so a
    try before NSE publishes costs a few requests and lands nothing.
    """
    return due_tonight(row, now) and now.astimezone(IST).hour >= TRY_FROM


def _fetch(
    ctx: Context, stale: Sequence[Any], due: Sequence[Any]
) -> tuple[list[Item], list[str], dict[str, Any]]:
    """Download what is behind, and today's files once NSE has published.

    Returns the items for the card, the steps run, and a report whose `line`
    says in one sentence what was downloaded (2026-11-09: before this, a run
    between 16:00 and 21:00 IST parked every missing dataset as "due tonight",
    fetched nothing, and its card did not say so).
    """
    wanted = list(stale) + [r for r in due if fetch_now(r, ctx.now)]
    waiting = [r for r in due if not fetch_now(r, ctx.now)]
    report: dict[str, Any] = {"tried": [], "caught": [], "still_behind": [], "cannot": []}
    items: list[Item] = []
    if not wanted:
        report["line"] = (
            f"Nothing to download yet: today's NSE files come out in the evening; "
            f"I fetch them from {TRY_FROM}:00 IST."
            if waiting
            else "Nothing to download: every dataset is up to date."
        )
        return items, [], report

    # A row none of whose steps an agent may run (Kite: a login only the
    # operator can make) is said plainly, not silently skipped.
    cannot = [r for r in wanted if not jobs.allowed_steps(list(r.steps))]
    report["cannot"] = [r.name for r in cannot]
    items.extend(
        Item(
            kind="alert",
            title=f"Needs you: {r.name} is not updating",
            body=f"I cannot download it myself. {r.detail or ''} Fix: {r.fix}".strip(),
            severity="warn",
            ref=r.fix,
            needs_approval=True,
        )
        for r in cannot
    )
    tryable = [r for r in wanted if r not in cannot]
    if not ctx.options.get("auto_rerun"):
        report["line"] = (
            f"Did not download anything: {len(tryable)} dataset(s) are behind, "
            "and re-running the feed is switched off (auto_rerun)."
        )
        return items, [], report
    if not tryable:
        report["line"] = "Downloaded nothing: what is behind needs you (see below)."
        return items, [], report

    steps: list[str] = []
    for row in tryable:
        steps.extend(s for s in jobs.allowed_steps(list(row.steps)) if s not in steps)
    ctx.step(f"Downloading: {', '.join(steps)}")
    result = jobs.rerun(steps)
    report["tried"] = list(result.steps)
    if not result.ok and "already running" not in result.detail:
        # Left for the on-call agent, which may run these same steps again (ADR-174).
        jobrun.dead_letter(
            "data", "feed", result.detail, remedy={"rerun": list(result.steps)}, now=ctx.now
        )
    caught = caught_up(tryable, _coverage_rows())
    caught_names = [n for n, _ in caught]
    left = [r.name for r in tryable if r.name not in caught_names]
    report["caught"] = caught_names
    report["still_behind"] = left
    if "already running" in result.detail:
        line = "Downloaded nothing: the nightly feed is running right now and will land the data."
    else:
        line = f"Downloaded with {', '.join(result.steps)}."
        if caught_names:
            line += f" Now up to date: {', '.join(caught_names)}."
        if left:
            why = "NSE has probably not published it yet" if result.ok else "a step failed"
            line += f" Still not in: {', '.join(left)} ({why}; I try again next run)."
    report["line"] = line
    items.insert(
        0,
        Item(
            kind="finding",
            title=(
                f"Updated {len(caught_names)} dataset(s)"
                if caught_names
                else "Downloaded nothing new"
            ),
            body=f"{line} Steps said: {result.detail}",
            severity="info" if result.ok else "warn",
            data={"steps": list(result.steps), "caught": caught_names, "left": left},
        ),
    )
    return items, list(result.steps), report


def due_tonight(row: Any, now: datetime) -> bool:
    """Today's data, absent only because the nightly run has not reached it yet."""
    detail = str(getattr(row, "detail", "") or "")
    return (
        getattr(row, "status", "") == "missing"
        and detail.startswith("today's data not in yet")
        and now.astimezone(IST).hour < DUE_UNTIL
    )


def _cloud() -> tuple[Any, Any]:
    """The bucket and its key prefix. Raises when there are no credentials."""
    from pathlib import Path

    from eulerlab.ingest.cloud import S3ObjectStore, load_storage_config

    config = load_storage_config(Path("config/storage.yaml"))
    return S3ObjectStore(config), config


def _upkeep(ctx: Context) -> tuple[list[Item], dict[str, Any]]:
    """Upload, delete what the bucket holds, merge what differs (ADR-132). Never raises."""

    from eulerlab.ingest import filelock, merge_back

    if os.environ.get("EULERLAB_NO_CLOUD", "").strip().lower() in ("1", "true", "yes"):
        return [], {"line": "Upkeep skipped: offline."}
    trees = [str(t) for t in ctx.options.get("upkeep_trees") or merge_back.TREES]
    limit = int(ctx.options.get("merge_limit") or merge_back.DEFAULT_LIMIT)
    ctx.step(f"Upkeep: uploading {', '.join(trees)}, deleting what B2 holds, merging what differs")
    try:
        with filelock.exclusive("feed", wait=False, what="the data agent's upkeep"):
            store, config = _cloud()
            from eulerlab.ingest.sync_cloud import mirror_trees

            printed = io.StringIO()
            root = data_path("landing")
            with contextlib.redirect_stdout(printed):
                mirror_trees(trees, store, config, root / "nse", root, then_delete=True)
            reports = merge_back.run(
                store,
                prefix=config.prefix,
                trees=trees,
                root=root,
                limit=limit,
                log=ctx.notes.append,
            )
            merge_back.save(reports)
    except filelock.Busy:
        return [], {"line": "Upkeep waits: the feed is running."}
    except Exception as exc:  # no credentials, no network: say so, do not fail the grading
        return [
            Item(
                kind="alert",
                title="upkeep could not run",
                body=f"{type(exc).__name__}: {str(exc)[:300]}",
                severity="warn",
            )
        ], {"line": "Upkeep failed."}
    text = printed.getvalue()
    deleted = sum(int(m) for m in re.findall(r"deleted (\d+) local files", text))
    uploaded = sum(int(m) for m in re.findall(r"uploaded (\d+),", text))
    failed_upload = [line.strip() for line in text.splitlines() if line.startswith("    ")]
    merged = sum(r.merged_uploaded for r in reports)
    duplicates = sum(r.duplicates_deleted for r in reports)
    unresolved = [u for r in reports for u in r.unresolved]
    left = sum(r.left_for_next_run for r in reports)
    added = sum(r.rows_added for r in reports)
    summary = {
        "uploaded": uploaded,
        "deleted": deleted,
        "duplicates_deleted": duplicates,
        "merged": merged,
        "rows_added": added,
        "unresolved": unresolved[:50],
        "left_for_next_run": left,
        "line": (
            f"Upkeep: {uploaded} uploaded, {deleted + duplicates + merged} local files deleted "
            f"({duplicates} duplicates, {merged} merged into B2 with {added} new rows)"
            + (f", {len(unresolved)} unresolved" if unresolved else "")
            + (f", {left} for the next run" if left else "")
            + "."
        ),
    }
    out: list[Item] = []
    if unresolved:
        out.append(
            Item(
                kind="alert",
                title=f"{len(unresolved)} local file(s) differ from B2 and could not be merged",
                body="; ".join(unresolved[:5]),
                severity="warn",
            )
        )
    shrinking = [f for f in failed_upload if "smaller than the bucket" not in f]
    if shrinking:
        out.append(
            Item(
                kind="alert",
                title=f"{len(shrinking)} upload(s) failed",
                body="; ".join(shrinking[:5]),
                severity="warn",
            )
        )
    return out, summary


def _ask_for_help(ctx: Context, problems: list[Item], *, already: list[str]) -> list[Item]:
    """One model request about what is still wrong; act only within the allowed list."""
    if not ctx.can_ask():
        return []
    allowed = sorted(jobs.ALLOWED)
    listed = "\n".join(f"- {p.title}: {p.body[:300]}" for p in problems[:12])
    user = (
        f"Allowed steps: {', '.join(allowed)}\nAlready re-run this time: {', '.join(already) or 'none'}\n\n"
        + untrusted("data-problems", listed, limit=4000)
    )
    try:
        advice = _parse_help(ctx.ask(HELP, user, accept=_parse_help))
    except BudgetSpent:
        return []
    except Exception as exc:  # no model, or an answer that is not the JSON asked for
        ctx.notes.append(f"AI help failed ({type(exc).__name__})")
        return []
    cause = " ".join(str(advice.get("cause") or "").split())[:300]
    fix = " ".join(str(advice.get("fix") or "").split())[:300]
    action = str(advice.get("action") or "operator")
    out = [
        Item(
            kind="finding",
            title=f"AI help: {cause[:120] or 'no cause given'}",
            body=f"Cause: {cause}. Fix: {fix}. Action: {action}.",
            severity="info",
        )
    ]
    step = str(advice.get("step") or "")
    if action == "rerun" and step in jobs.ALLOWED and step not in already:
        result = jobs.rerun([step])
        out.append(
            Item(
                kind="finding",
                title=f"re-ran {step} on AI advice: {'ok' if result.ok else 'still failing'}",
                body=result.detail,
                severity="info" if result.ok else "warn",
            )
        )
    elif action == "head":
        from eulerlab.agents import tasks

        task = tasks.create(
            title=f"Data problem: {problems[0].title}"[:200],
            owner="head_platform",
            department="platform",
            created_by=ctx.name,
            detail=f"{problems[0].body[:800]}\n\nAI help says. Cause: {cause}. Fix: {fix}",
            key=f"data-help|{problems[0].title}|{ctx.now.date().isoformat()}",
            root=ctx.root,
            now=ctx.now,
        )
        out.append(
            Item(
                kind="finding",
                title=f"asked the Head of Data and Platform ({task.id})",
                body=fix,
                severity="info",
            )
        )
    elif action == "operator":
        out[0] = Item(
            kind="alert",
            title=f"Needs you: {cause[:120] or problems[0].title}",
            body=f"{fix}",
            severity="warn",
            needs_approval=True,
        )
    return out


def _parse_help(text: str) -> dict[str, Any]:
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        raise ValueError("no JSON object in the answer")
    body = json.loads(match.group(0))
    if not isinstance(body, dict) or "action" not in body:
        raise ValueError("the answer has no action")
    return body


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
