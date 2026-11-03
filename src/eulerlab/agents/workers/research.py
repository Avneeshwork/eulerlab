"""The research agent: the paper agent (ADR-084), then a librarian and a data scout.

    brief / topic -> Quantpedia leads (landed strategies close to the topic, if synced)
                  -> paper_agent.run  (search, read, draft, critic; stops at drafts)
                  -> librarian: is this an idea already tried, under another name?
                  -> data scout: does it need data we do not hold, or cannot date?
                  -> rank the survivors -> the operator's inbox

**Ideas first, data second.** A draft that needs data the platform does not
hold is not dropped: it becomes a data request the data agent answers, and
stays in the inbox marked as waiting for data. The idea is judged on its
reason and its red flags, not on what happens to be on disk.

**It never spends a trial.** Approving an inbox item records the operator's
interest; registering still takes `make paper-agent-approve DRAFT=<folder>`,
then the operator moving the card to `registered`. This module imports
nothing that backtests, validates or writes the trial ledger
(`agents/boundaries.py`).

**Ranking is by reason, never by expected Sharpe.** A draft ranks higher with
a stated rationale, more specific red flags, no repeat of a closed card, no
blocking critic objection and data that is held and dateable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from eulerlab.agents.runtime import IST, Context, Item, WorkerResult, latest_output
from eulerlab.features import formula
from eulerlab.research import idea_memory

HYPOTHESES = Path("hypotheses")
REPEAT = 0.45
"""Word overlap (Jaccard, on title and claim) at which a draft is called a repeat."""

DATA_WORDS: dict[str, tuple[str, ...]] = {
    "Fundamentals": (
        "earnings",
        "book-to-market",
        "book to market",
        "roe",
        "profitability",
        "accrual",
        "fundamental",
        "value factor",
        "quality",
    ),
    "Nifty options": ("option", "implied vol", "volatility risk premium", "straddle", "put-call"),
    "India minute bars (Kite)": (
        "intraday",
        "minute",
        "opening range",
        "high-frequency",
        "order flow",
    ),
    "Delivery table": ("delivery",),
    "Participant OI": ("fii", "dii", "participant", "open interest"),
    "Nifty futures": ("futures", "basis", "roll"),
}
WORD = re.compile(r"[a-z][a-z0-9\-]{2,}")
STOP = frozenset(
    [
        "the",
        "and",
        "for",
        "with",
        "that",
        "this",
        "from",
        "are",
        "was",
        "were",
        "has",
        "have",
        "not",
        "but",
        "its",
        "into",
        "over",
        "than",
        "then",
        "indian",
        "india",
        "stocks",
        "stock",
        "returns",
        "return",
        "market",
        "markets",
    ]
)


@dataclass(frozen=True)
class Known:
    id: str
    title: str
    status: str
    words: frozenset[str]


def _words(text: str) -> frozenset[str]:
    return frozenset(w for w in WORD.findall(text.lower()) if w not in STOP)


def known_cards(directory: Path = HYPOTHESES) -> list[Known]:
    out: list[Known] = []
    for path in sorted(directory.glob("H-*.yaml")):
        spec = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        out.append(
            Known(
                id=str(spec.get("id", path.stem)),
                title=str(spec.get("title", "")),
                status=str(spec.get("status", "")),
                words=_words(f"{spec.get('title', '')} {spec.get('claim', '')}"),
            )
        )
    return out


def nearest(text: str, cards: list[Known]) -> tuple[Known | None, float]:
    mine = _words(text)
    best: tuple[Known | None, float] = (None, 0.0)
    for c in cards:
        union = mine | c.words
        score = len(mine & c.words) / len(union) if union else 0.0
        if score > best[1]:
            best = (c, score)
    return best


def data_needs(text: str) -> list[str]:
    lowered = text.lower()
    return [name for name, words in DATA_WORDS.items() if any(w in lowered for w in words)]


@dataclass
class _Answer:
    text: str
    provider: str
    model: str


def _draft_text(folder: Path) -> tuple[str, dict[str, Any]]:
    card_path = folder / "card.yaml"
    spec: dict[str, Any] = {}
    if card_path.exists():
        spec = yaml.safe_load(card_path.read_text(encoding="utf-8")) or {}
    paper = folder / "paper.yaml"
    paper_spec = yaml.safe_load(paper.read_text(encoding="utf-8")) if paper.exists() else {}
    text = " ".join(
        str(x)
        for x in (
            spec.get("title", ""),
            spec.get("claim", ""),
            spec.get("rationale", ""),
            (paper_spec or {}).get("summary", ""),
            (paper_spec or {}).get("implementation", ""),
        )
    )
    return text, spec


def by_source(drafts: list[Any]) -> dict[str, dict[str, int]]:
    """Each source's papers by outcome, so a run shows which sources pay (ADR-129)."""
    out: dict[str, dict[str, int]] = {}
    for d in drafts:
        key = "failed" if d.outcome.startswith("failed") else d.outcome
        row = out.setdefault(d.candidate.source, {})
        row[key] = row.get(key, 0) + 1
    return out


def lab_feedback(ctx: Context) -> idea_memory.Feedback | None:
    """The idea lab's latest feedback: topics to search and what its tests have shown."""
    lab = latest_output("lab", ctx.root)
    raw = lab.data.get("feedback") if lab is not None else None
    if not isinstance(raw, dict):
        return None
    try:
        return idea_memory.Feedback.model_validate(raw)
    except ValueError:
        return None


def todays_topic(topics: list[str], now: datetime) -> str:
    """One topic a day, in turn, so the research agent stops reading one topic's papers again."""
    day = now.astimezone(IST).date()
    return topics[day.toordinal() % len(topics)]


def memory_of_tests(fb: idea_memory.Feedback) -> str:
    """What the lab has already tested and seen fail, for the paper agent's prompt.

    Memory, not direction (operator, 2026-11-03: "research then lab then
    engineering"): research picks its own topics; the lab's record only stops it
    redrafting an idea that already failed. Which families "work" is left out,
    so the lab does not steer research.
    """
    lines = []
    if fb.dead:
        lines.append(
            f"- Families that failed every test so far (do not redraft them as they are): {', '.join(fb.dead)}."
        )
    if fb.missing_features:
        lines.append(
            "- Earlier drafts named features the library does not have "
            f"({', '.join(fb.missing_features[:6])}); a formula, if one fits, is tested sooner."
        )
    if not lines:
        return ""
    return "What the idea lab has already tested:\n" + "\n".join(lines)


def run(ctx: Context) -> WorkerResult:
    from eulerlab.quality import contract
    from eulerlab.research import paper_agent, paper_search, quantpedia

    lab = lab_feedback(ctx)
    # Research comes first and chooses its own topic (ADR-128): a task's or your
    # brief's, else the day's from its own list, else its one default. Never the lab's.
    topic = str(ctx.args.get("topic") or "").strip()
    if not topic and ctx.brief:
        topic = ctx.brief.splitlines()[-1].split(": ", 1)[-1][:200]
    listed = [str(t).strip() for t in ctx.options.get("topics") or [] if str(t).strip()]
    if not topic and listed:
        topic = todays_topic(listed, ctx.now)
        ctx.notes.append(f"topic from its own list, in turn: {topic}")
    topic = topic or str(ctx.options.get("topic") or "")
    if not topic:
        return WorkerResult("no topic: give one, or write a brief", status="refused")
    limit = int(ctx.args.get("limit") or ctx.options.get("limit") or 5)
    limit = max(1, min(limit, max(ctx.budget_left - ctx.requests, 0)))

    ctx.step(f"Looking for '{topic[:80]}' in Quantpedia's catalogue")
    found = quantpedia.leads(topic, quantpedia.catalogue(), limit=5)
    if not found:
        ctx.notes.append("no Quantpedia leads: none landed for this topic (make quantpedia-sync)")
    leads = [
        Item(
            kind="lead",
            title=f"Quantpedia: {lead.name}"[:200],
            body="\n".join(
                [
                    f"paper: {lead.paper or 'not named'}",
                    f"Sharpe in the paper {lead.sharpe_paper if lead.sharpe_paper is not None else 'n/a'}, "
                    f"recalculated by Quantpedia {lead.sharpe_recalculated if lead.sharpe_recalculated is not None else 'n/a'}",
                    f"markets: {lead.markets or 'n/a'}",
                    "Prior evidence only: their numbers are not ours and spend no trial here.",
                ]
            ),
            ref=lead.path,
            data={"quantpedia_id": lead.id, "overlap": lead.score},
        )
        for lead in found
    ]

    def ask(system: str, user: str, accept: Any) -> _Answer:
        text = ctx.ask(system, user, accept)
        return _Answer(text, ctx.model, ctx.model)

    ctx.step(f"Searching arXiv and OpenAlex; drafting up to {limit} cards")
    guidance = memory_of_tests(lab) if lab is not None else ""
    sources = [str(x) for x in ctx.options.get("sources") or paper_search.DEFAULT_SOURCES]
    ctx.step(f"Sources: {', '.join(sources)}")
    result = paper_agent.run(
        topic, limit=limit, ask=ask, log=ctx.notes.append, guidance=guidance, sources=sources
    )
    if result.failures and not result.drafts:
        return WorkerResult(
            "; ".join(result.failures)[:300],
            leads,
            status="refused" if "affordable" in " ".join(result.failures) else "failed",
        )

    # Every paper's fate, in words (2026-11-03: runs said "0 drafted" and
    # nothing else, so a reply-shape bug looked like a lack of papers).
    for d in result.drafts:
        if d.outcome == "not relevant":
            ctx.notes.append(f"not a trading idea: {d.candidate.title[:70]} ({d.relevance[:150]})")
        elif d.outcome.startswith("failed"):
            ctx.notes.append(f"could not read: {d.candidate.title[:70]} ({d.outcome[8:][:150]})")
    ctx.step(f"Checking {len(result.drafts)} drafts against ideas already tried")
    cards = known_cards()
    lab_tested = idea_memory.tested_features(idea_memory.load(ctx.root))
    grades = {str(g.get("name")): g for g in contract.saved()}
    items: list[Item] = []
    ranked: list[tuple[float, Item]] = []
    for draft in result.drafts:
        if draft.outcome != "drafted" or draft.path is None:
            continue
        text, spec = _draft_text(draft.path)
        match, score = nearest(text, cards)
        configured = [
            str(c.get("feature")) for c in spec.get("configurations") or [] if c.get("feature")
        ]
        unknown = [f for f in configured if not formula.is_known(f)]
        lab_tried = bool(configured) and all(f in lab_tested for f in configured)
        repeat = (match is not None and score >= REPEAT) or lab_tried
        # Words in an abstract are a guess at data needs; a card whose every feature
        # the library can build needs nothing more (2026-11-01: a buildable draft was
        # marked as waiting for three datasets and never tested).
        needs = data_needs(text) if unknown or not configured else []
        missing = [
            n
            for n in needs
            if n not in grades
            or grades[n].get("grade") in ("C", "D")
            or grades[n].get("point_in_time") is False
        ]
        for name in missing:
            items.append(
                Item(
                    kind="data_request",
                    title=name,
                    body=f"for the draft '{spec.get('title', draft.candidate.title)}'",
                    data={"dataset": name, "draft": str(draft.path)},
                )
            )
        flags = list(spec.get("red_flags") or [])
        rank = (
            2.0 * bool(spec.get("rationale"))
            + min(len(flags), 6) * 0.5
            - 3.0 * repeat
            - 1.5 * bool(draft.card_problems)
            - 1.0 * len(missing)
        )
        lines = [
            f"paper: {draft.candidate.title} ({draft.candidate.year or 'year unknown'})",
            f"read: {draft.read}",
            f"claim: {spec.get('claim', 'no card drafted')}",
        ]
        if lab_tried:
            lines.append("the idea lab has already tested every feature this card names")
        elif repeat and match is not None:
            lines.append(
                f"looks like {match.id} ({match.status}): {match.title} — overlap {score:.0%}"
            )
        if missing:
            lines.append(f"waiting for data: {', '.join(missing)} (asked the data agent)")
        if draft.card_problems:
            lines.append(f"card incomplete: {'; '.join(draft.card_problems)[:200]}")
        lines.append(f"to keep it: make paper-agent-approve DRAFT={draft.path}")
        ranked.append(
            (
                rank,
                Item(
                    kind="draft",
                    title=str(spec.get("title") or draft.candidate.title)[:200],
                    body="\n".join(lines),
                    severity="warn" if repeat else "info",
                    needs_approval=not repeat,
                    ref=str(draft.path),
                    data={
                        "rank": round(rank, 2),
                        "repeat_of": "idea lab"
                        if lab_tried
                        else (match.id if repeat and match else ""),
                        "unknown_features": unknown,
                        "overlap": round(score, 2),
                        "needs_data": missing,
                    },
                ),
            )
        )
    ranked.sort(key=lambda pair: -pair[0])
    items = [item for _, item in ranked] + items + leads
    drafted = len(ranked)
    # How many the lab can test: a card research found incomplete is not (HISTORY #73).
    complete = sum(
        1
        for d in result.drafts
        if d.outcome == "drafted" and d.hypothesis is not None and not d.card_problems
    )
    repeats = sum(1 for _, i in ranked if i.data.get("repeat_of"))
    counts = result.counts()
    read = sum(counts.get(k, 0) for k in ("drafted", "not relevant", "failed"))
    kept = sum(1 for d in result.drafts if d.paper is not None)
    skipped = ", ".join(
        f"{counts[k]} {label}"
        for k, label in (
            ("known", "already known"),
            ("nothing to read", "with no abstract"),
            ("off topic", "off topic"),
        )
        if counts.get(k)
    )
    return WorkerResult(
        f"{topic}: {read} read, {drafted} drafted ({complete} complete), "
        f"{counts.get('not relevant', 0)} not a trading idea, {counts.get('failed', 0)} failed"
        + (f"; skipped {skipped}" if skipped else "")
        + f"; {kept} added to the library; {repeats} repeats of closed ideas, "
        f"{sum(1 for i in items if i.kind == 'data_request')} data requests, "
        f"{len(leads)} Quantpedia leads. Nothing registered.",
        items,
        data={
            "topic": topic,
            "folder": str(result.folder),
            "bar_now": round(result.cost.bar_now, 3),
            "topic_from_list": topic in listed,
            "outcomes": counts,
            "by_source": by_source(result.drafts),
            "library": [d.paper.id for d in result.drafts if d.paper is not None],
        },
    )
