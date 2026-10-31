"""The knowledge keeper: keeps `docs/METRICS/` current and growing (ADR-104).

**Daily** (after the close):

1. **Normals.** Recompute what is normal for each market metric from the data
   held and save it (`metrics_library.normals`), so the assistant quotes
   today's range beside the written page.
2. **Regulator watch.** Land the SEBI, RBI and NSE feeds once and list the
   items not seen before (`metrics_library.regwatch`). Each new item that
   matches a page's topic is an inbox note with its link and the pages it may
   change. The first run only records what is there, so the inbox is not
   flooded with the feeds' back catalogue.

**Weekly** (`mode=weekly`, Sundays), the daily steps plus:

3. **Gaps.** Assumptions past their recheck date; pages whose written normals
   are older than `stale_days`; market-context sections with no page;
   questions the assistant looked up and found no page for.
4. **Drafts.** For up to `max_drafts` pages with new information (a linked
   circular this week, or stale normals), the model drafts the updated page
   from the current page and the new material only. The grounding check
   (ADR-088) drops a draft with any figure not in that material. A draft is
   saved in this run's folder and waits in the inbox; nothing in `docs/`
   changes until the operator runs `make metrics-accept DRAFT=...`.

A question with no page gets a proposal, never a drafted page: there is no
source material to draft it from, and a page written from memory is the thing
this library exists to prevent.
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from eulerlab.agents import grounding
from eulerlab.agents.runtime import Context, Item, WorkerResult, untrusted
from eulerlab.metrics_library import catalog, gaps, normals, regwatch

IST = ZoneInfo("Asia/Kolkata")
API = "http://127.0.0.1:8000"

DRAFT_SYSTEM = """You maintain one page of a metrics library for an Indian markets research platform.
You are given the page as it stands and new material (a regulator's notice, or freshly computed normal ranges).
Return the whole page, updated, in exactly the same Markdown layout and headings.
Change only what the new material supports. Keep everything else word for word.
Every number you add must appear in the new material. Write the date the material is from.
If the new material does not change the page, reply with exactly: NO CHANGE"""


def _market_context() -> dict[str, Any]:
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(f"{API}/api/market-context", timeout=60) as response:
            body = json.loads(response.read().decode("utf-8"))
            return body if isinstance(body, dict) else {}
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return {}


def _fetcher() -> Any:
    from eulerlab.ingest.fetch import Fetcher, FetchPolicy, UrllibTransport

    return Fetcher(UrllibTransport(), FetchPolicy(max_attempts=2))


def _daily(ctx: Context, items: list[Item], data: dict[str, Any]) -> None:
    ctx.step("Recomputing what is normal for each market metric from the data held")
    payload = normals.compute(ctx.now)
    normals.save(payload)
    data["normals"] = {k: len(v) for k, v in payload["metrics"].items()}
    ctx.notes.extend(f"normals: {n}" for n in payload["left_out"])

    ctx.step("Reading the SEBI, RBI and NSE feeds for anything new")
    sources = regwatch.load_sources()
    first_run = not regwatch.ITEMS.exists()
    result = regwatch.watch(
        _fetcher(),
        sources,
        today=ctx.now.astimezone(IST).date(),
        knowledge_time=ctx.now.isoformat(timespec="seconds"),
    )
    data["feeds"] = result.status
    data["new_items"] = len(result.new)
    for name, status in result.status.items():
        if status.startswith(("failed", "unreadable")):
            items.append(
                Item(kind="alert", title=f"Feed {name} {status}", severity="warn", ref=name)
            )
    if first_run:
        items.append(
            Item(
                kind="finding",
                title=f"Regulator watch started: {len(result.new)} existing items recorded",
                body="The first run records what the feeds already list. From the next run, "
                "only new items are reported.",
            )
        )
        return
    for item in result.new:
        if not item.pages:
            continue
        items.append(
            Item(
                kind="lead",
                title=f"{item.feed.upper()}: {item.title}"[:200],
                body=f"{item.published or 'undated'}. May affect: {', '.join(item.pages)}.\n"
                f"{item.summary[:400]}",
                severity="warn" if item.feed in ("sebi", "nse_circulars") else "info",
                ref=item.link,
                data={"pages": item.pages, "key": item.key},
            )
        )
    unlinked = [i for i in result.new if not i.pages]
    if unlinked:
        data["unlinked"] = [f"{i.feed}: {i.title}" for i in unlinked[:30]]


def _draft(ctx: Context, page: catalog.Page, material: str) -> Item | None:
    if not ctx.can_ask():
        return None
    try:
        answer = ctx.ask(
            DRAFT_SYSTEM, untrusted("page", page.text) + "\n\n" + untrusted("new", material)
        )
    except Exception as exc:  # the model or its host failed; the run goes on
        ctx.notes.append(f"draft for {page.id} not made: {type(exc).__name__}")
        return None
    text = answer.strip()
    if not text or text.upper().startswith("NO CHANGE") or not text.startswith("# "):
        return None
    found = grounding.check(text, [page.text, material])
    if not found.ok:
        ctx.notes.append(
            f"draft for {page.id} dropped: figures not in the material ({', '.join(found.unsupported[:6])})"
        )
        return None
    name = f"draft-{page.id}.md"
    path = ctx.write(name, text.rstrip() + "\n")
    ctx.write(f"draft-{page.id}.json", {"page": page.path, "id": page.id})
    return Item(
        kind="draft",
        title=f"Updated page drafted: {page.name}"[:200],
        body=f"Apply with: make metrics-accept DRAFT={path}",
        needs_approval=True,
        ref=str(path),
        data={"page": page.path},
    )


def _weekly(ctx: Context, items: list[Item], data: dict[str, Any]) -> None:
    today = ctx.now.astimezone(IST).date()
    pages = catalog.pages()
    known = {p.id for p in pages}
    by_id = {p.id: p for p in pages}

    ctx.step("Checking assumptions past their recheck date")
    late = gaps.overdue(
        gaps.ASSUMPTIONS.read_text(encoding="utf-8") if gaps.ASSUMPTIONS.exists() else "", today
    )
    for row in late:
        items.append(
            Item(
                kind="finding",
                title=f"{row.id} is past its recheck date ({row.recheck})",
                body=row.claim,
                severity="warn",
                ref="docs/ASSUMPTIONS.md",
            )
        )

    ctx.step("Finding pages whose written normal ranges have aged")
    stale = gaps.stale_pages(pages, today, int(ctx.options.get("stale_days", 90)))
    data["stale_pages"] = [p.id for p in stale]

    ctx.step("Checking every market-context section has a page")
    mapped = dict(ctx.options.get("sections") or {})
    payload = _market_context()
    for line in gaps.uncovered(payload, mapped, known) if payload else []:
        items.append(Item(kind="finding", title=f"No metric page: {line}", ref="docs/METRICS/"))

    ctx.step("Collecting questions that found no page")
    since = (ctx.now - timedelta(days=7)).isoformat(timespec="seconds")
    asked = gaps.asked_without_page(catalog.misses(), since)
    for query, count in asked[:10]:
        items.append(
            Item(
                kind="proposal",
                title=f"No page answers: '{query}' (asked {count}x this week)"[:200],
                body="Write a page from a primary source, or map the question to an existing page.",
                ref="docs/METRICS/",
            )
        )

    ctx.step("Drafting updates for pages with new material")
    week_ago = (ctx.now - timedelta(days=7)).isoformat(timespec="seconds")
    material: dict[str, list[str]] = {}
    sources = regwatch.load_sources()
    for notice in regwatch.seen().values():
        if notice.get("baseline") or str(notice.get("knowledge_time", "")) < week_ago:
            continue
        item = regwatch.FeedItem(
            feed=str(notice.get("feed")),
            title=str(notice.get("title")),
            link=str(notice.get("link")),
            published=str(notice.get("published") or ""),
            summary=str(notice.get("summary") or ""),
            key=str(notice.get("key")),
        )
        # Linked again with today's topics, so a tightened topic list applies to the week.
        for page_id in regwatch.link_pages(item, sources.topics, sources.skip_titles):
            material.setdefault(page_id, []).append(
                f"{item.feed} notice dated {item.published or 'undated'}: "
                f"{item.title}\n{item.summary}\nLink: {item.link}"
            )
    live = normals.load()
    for page in stale:
        described = normals.describe(page.id, live)
        if described:
            material.setdefault(page.id, []).append(described)
    drafted = attempts = 0
    for page_id, parts in material.items():
        if attempts >= int(ctx.options.get("max_drafts", 3)) or page_id not in by_id:
            continue
        attempts += 1
        made = _draft(ctx, by_id[page_id], "\n\n".join(parts))
        if made is not None:
            items.append(made)
            drafted += 1
        elif ctx.notes and ctx.notes[-1].endswith(("Refused", "BudgetSpent")):
            break  # no model reachable or no budget left: the rest would fail the same way
    data["drafts"] = drafted
    data["pages_with_material"] = sorted(material)


def run(ctx: Context) -> WorkerResult:
    mode = str(ctx.args.get("mode") or "daily")
    items: list[Item] = []
    data: dict[str, Any] = {"mode": mode}
    _daily(ctx, items, data)
    if mode == "weekly":
        _weekly(ctx, items, data)
    leads = sum(1 for i in items if i.kind == "lead")
    drafts = sum(1 for i in items if i.kind == "draft")
    summary = f"{mode}: {data.get('new_items', 0)} new feed item(s), {leads} linked to pages" + (
        f", {drafts} draft(s) waiting" if mode == "weekly" else ""
    )
    return WorkerResult(summary, items, data=data)


def accept(draft: Path, *, root: Path = Path()) -> Path:
    """Copy an approved draft over its page. The operator's command, not the agent's."""
    meta = json.loads(draft.with_suffix(".json").read_text(encoding="utf-8"))
    page = str(meta["page"])
    if not page.startswith("docs/METRICS/") or ".." in page or not page.endswith(".md"):
        msg = f"{page} is not a metrics page"
        raise ValueError(msg)
    target = root / page
    target.write_text(draft.read_text(encoding="utf-8"), encoding="utf-8")
    return target


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="metrics-accept")
    parser.add_argument("draft", type=Path)
    args = parser.parse_args(argv)
    target = accept(args.draft)
    print(f"applied {args.draft} -> {target}. Review the diff and commit it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
