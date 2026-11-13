"""The knowledge base: paper, claim, card, result, linked by id so an agent can ask what was tried (ADR-180).

The library had papers and cards but no record of which claim a card tests,
whether the paper's own result was reproduced here, or how the test went.
Agents re-read the files every run to work it out. Now:

    paper   research/papers/<id>.yaml                       (unchanged)
    claim   one per paper, `claim:<paper id>`: its market, signal, horizon,
            reported effect and sample years, read from the paper file.
            A card with no paper tests its own claim, `agent:<card id>`.
    card    hypotheses/H-NNNN.yaml. `source.claim` names the claim it tests,
            and `source.replicates: true` marks the paper's own form, tried
            before any adaptation (#131).
    result  the experiment store's rows for that card (ADR-172) and its
            latest gate verdict in the trial ledger.

Claims are rows in `data/derived/knowledge/claims.jsonl` (or Postgres, ADR-174):
`sync` adds the claim of any paper not yet there and edits nothing. Cards and
results are read where they already live, so there is one copy of each fact.

Three questions are answered from these links, each with ids and sources:
`tried_near` (what has been tried near this idea), `replicated` (which claims
were reproduced in India) and `failed` (what failed, and why). The knowledge
agent reaches them through the `claim_record` tool. Search is the platform's
BM25 (`agents/knowledge_index.py`); no embeddings and no new dependency.

Lessons and HISTORY link to claims through the card and paper ids they name:
`mentions` finds them, so no lesson needs rewriting.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import yaml

from eulerlab.db.stream import add_row, read_rows
from eulerlab.paths import data_path

KIND = "knowledge"
CLAIMS = "derived/knowledge/claims.jsonl"
PAPERS = Path("research/papers")
HYPOTHESES = Path("hypotheses")
HISTORY = Path("docs/HISTORY.md")
CARD_ID = re.compile(r"\bH-\d{4}\b")
YEARS = re.compile(r"\b(19[5-9]\d|20[0-4]\d)\s*(?:-|\u2013|to)\s*(19[5-9]\d|20[0-4]\d)\b")
HORIZONS = (
    ("intraday", ("intraday", "open to close", "minute", "same day")),
    ("days", ("day", "daily", "week", "overnight")),
    ("months", ("month", "quarter", "annual", "year")),
)
PASSED = ("PROMOTE", "PAPER")
DROPPED = ("not gated", "screen fail", "kill")
"""Words in a card's result line (`autopilot.result_line`) that mean it went no further."""


def claims_path() -> Path:
    return data_path(CLAIMS)


def claim_id(paper: str) -> str:
    return f"claim:{paper}"


@dataclass(frozen=True)
class Claim:
    id: str
    paper: str
    market: str
    signal: str
    horizon: str
    effect: str
    sample: str
    source: str
    at: str = ""


def _text(value: Any) -> str:
    if isinstance(value, list):
        return "; ".join(str(v) for v in value)
    return "" if value is None else str(value)


def horizon_of(text: str) -> str:
    low = text.lower()
    for name, words in HORIZONS:
        if any(w in low for w in words):
            return name
    return "unstated"


def claim_of(paper: Mapping[str, Any], *, at: str = "") -> Claim:
    """A paper file's claim, read from its own fields. Nothing is guessed beyond them."""
    pid = str(paper["id"])
    market = _text(paper.get("markets"))
    signal = _text(paper.get("trade_idea")) or _text(paper.get("summary"))
    found = YEARS.search(f"{market} {paper.get('summary', '')}")
    return Claim(
        id=claim_id(pid),
        paper=pid,
        market=market[:300],
        signal=signal[:600],
        horizon=horizon_of(f"{signal} {paper.get('implementation', '')}"),
        effect=_text(paper.get("reported_results"))[:600],
        sample=f"{found.group(1)}-{found.group(2)}" if found else "unstated",
        source=_text(paper.get("source_url")),
        at=at,
    )


def _yaml_files(root: Path) -> list[dict[str, Any]]:
    out = []
    for path in sorted(root.glob("*.yaml")):
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            continue
        if isinstance(raw, dict) and raw.get("id"):
            out.append({**raw, "_path": str(path)})
    return out


def claims(path: Path | None = None) -> dict[str, Claim]:
    """Every stored claim by id. A later row for the same id is ignored: claims are not edited."""
    out: dict[str, Claim] = {}
    for row in read_rows(path or claims_path(), KIND):
        if row.get("id") and row["id"] not in out:
            out[str(row["id"])] = Claim(**{k: row.get(k, "") for k in Claim.__dataclass_fields__})
    return out


def sync(
    papers: Path = PAPERS, path: Path | None = None, *, now: datetime | None = None
) -> list[str]:
    """Add the claim of each paper not yet stored. Returns the new claim ids."""
    target = path or claims_path()
    held = claims(target)
    at = (now or datetime.now(UTC)).isoformat(timespec="seconds")
    new = []
    for paper in _yaml_files(papers):
        claim = claim_of(paper, at=at)
        if claim.id in held:
            continue
        add_row(target, KIND, {k: getattr(claim, k) for k in Claim.__dataclass_fields__})
        new.append(claim.id)
    return new


def _source(card: Mapping[str, Any]) -> dict[str, Any]:
    raw = card.get("source")
    return raw if isinstance(raw, dict) else {}


def card_claim(card: Mapping[str, Any]) -> str:
    """The claim a card tests: the one it names, else its paper's, else its own."""
    source = _source(card)
    named = str(source.get("claim") or "")
    if named:
        return named
    paper = str(source.get("paper") or "")
    return claim_id(paper) if paper else f"agent:{card.get('id', '')}"


@dataclass(frozen=True)
class Tried:
    card: str
    claim: str
    title: str
    replicates: bool
    verdict: str
    """The latest gate verdict, or '' when the card was never gated."""
    screens: int
    """How many rows the experiment store holds for this card."""
    why: str
    """The card's result line: the screen or gate in one sentence."""
    path: str
    text: str = field(default="", repr=False)

    @property
    def outcome(self) -> str:
        """passed (the gate let it through), failed (gate KILL or the screen dropped it),
        screened (screened, not gated yet) or untested."""
        if self.verdict.upper().startswith(PASSED):
            return "passed"
        if self.verdict or any(w in self.why.lower() for w in DROPPED):
            return "failed"
        return "screened" if self.screens or self.why else "untested"


def tried(
    cards: Path = HYPOTHESES,
    *,
    verdicts: Mapping[str, tuple[str, date]] | None = None,
    experiments: Sequence[Mapping[str, Any]] | None = None,
) -> list[Tried]:
    """Every card with its claim and its results, in id order."""
    if verdicts is None:
        from eulerlab import forward

        verdicts = forward.verdicts()
    if experiments is None:
        from eulerlab.research import experiments as store

        experiments = store.rows()
    counts: dict[str, int] = {}
    for row in experiments:
        h = str(row.get("hypothesis") or "")
        counts[h] = counts.get(h, 0) + 1
    out = []
    for card in _yaml_files(cards):
        h = str(card["id"])
        source = _source(card)
        out.append(
            Tried(
                card=h,
                claim=card_claim(card),
                title=_text(card.get("title")),
                replicates=bool(source.get("replicates")),
                verdict=verdicts.get(h, ("", date.min))[0],
                screens=counts.get(h, 0),
                why=_text(card.get("result")),
                path=str(card["_path"]),
                text=" ".join(
                    _text(card.get(k)) for k in ("title", "claim", "rationale", "family")
                ),
            )
        )
    return out


def mentions(text: str) -> set[str]:
    """Card ids named in a lesson, a HISTORY entry or any other text."""
    return set(CARD_ID.findall(text))


def _history_entries(path: Path = HISTORY) -> list[tuple[str, str]]:
    """HISTORY.md's sections as (heading, body)."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    parts = re.split(r"^#{2,3} ", text, flags=re.MULTILINE)[1:]
    return [(p.splitlines()[0].strip(), p) for p in parts if p.strip()]


def notes_on(cards: Iterable[str], *, history: Path = HISTORY) -> list[str]:
    """Lessons and HISTORY entries that name any of these cards."""
    from eulerlab.agents import lessons

    wanted = set(cards)
    out = [f"lesson {x.id}: {x.text[:160]}" for x in lessons.load() if mentions(x.text) & wanted]
    out += [
        f"HISTORY: {head[:120]}"
        for head, body in _history_entries(history)
        if mentions(body) & wanted
    ]
    return out


# --- the three questions ------------------------------------------------------------------


def tried_near(
    idea: str, done: Sequence[Tried], held: Mapping[str, Claim], *, limit: int = 8
) -> list[dict[str, Any]]:
    """Cards whose claim, title or rationale is closest to the idea, with how each went."""
    from eulerlab.agents import knowledge_index

    def words(t: Tried) -> str:
        claim = held.get(t.claim)
        extra = f"{claim.signal} {claim.market}" if claim else ""
        return f"{t.text} {extra} {t.why}"

    entries = [knowledge_index.Entry("card", t.card, t.title, words(t), 0.0) for t in done]
    by_card = {t.card: t for t in done}
    hits = knowledge_index.search(idea, entries, limit=limit)
    return [_line(by_card[h["path"]], held) for h in hits]


def replicated(done: Sequence[Tried], held: Mapping[str, Claim]) -> list[dict[str, Any]]:
    """Claims whose paper form was tried here, and whether it held up."""
    out: dict[str, dict[str, Any]] = {}
    for t in done:
        if not t.replicates or not t.claim.startswith("claim:"):
            continue
        row = out.setdefault(t.claim, {**_claim_line(t.claim, held), "cards": [], "held_up": False})
        row["cards"].append(_line(t, held))
        row["held_up"] = row["held_up"] or t.outcome == "passed"
    return sorted(out.values(), key=lambda r: (not r["held_up"], r["claim"]))


def failed(
    done: Sequence[Tried], held: Mapping[str, Claim], about: str = ""
) -> list[dict[str, Any]]:
    """Cards the gate killed or the screen dropped, each with its reason."""
    bad = [t for t in done if t.outcome == "failed"]
    if about.strip():
        near = {r["card"] for r in tried_near(about, bad, held, limit=20)}
        bad = [t for t in bad if t.card in near]
    return [_line(t, held) for t in bad]


def _claim_line(cid: str, held: Mapping[str, Claim]) -> dict[str, Any]:
    claim = held.get(cid)
    if claim is None:
        return {"claim": cid, "paper": "", "source": ""}
    return {
        "claim": cid,
        "paper": f"research/papers/{claim.paper}.yaml",
        "source": claim.source,
        "market": claim.market,
        "sample": claim.sample,
        "reported": claim.effect,
    }


def _line(t: Tried, held: Mapping[str, Claim]) -> dict[str, Any]:
    return {
        "card": t.card,
        "path": t.path,
        "title": t.title,
        "outcome": t.outcome,
        "verdict": t.verdict,
        "why": t.why,
        "screens": t.screens,
        **_claim_line(t.claim, held),
    }


def answer(ask: str, about: str = "") -> str:
    """The `claim_record` tool's text: plain lines, every one with its ids and files."""
    held = claims()
    done = tried()
    if ask == "replicated":
        rows = replicated(done, held)
        if not rows:
            return "No card is marked as replicating a paper's own form (source.replicates)."
        lines = []
        for r in rows:
            cards = ", ".join(f"{c['card']} {c['outcome']}" for c in r["cards"])
            state = "held up" if r["held_up"] else "did not hold up"
            lines.append(
                f"{r['claim']} ({r['paper']}): {state} here. Cards: {cards}. {r['source']}"
            )
        return "\n".join(lines)
    if ask == "failed":
        rows = failed(done, held, about)
    elif ask == "tried_near":
        if not about.strip():
            return "Say what idea to look near."
        rows = tried_near(about, done, held)
    else:
        return "ask must be tried_near, replicated or failed."
    if not rows:
        return "Nothing held matches." if about else "Nothing held."
    lines = [
        f"{r['card']} ({r['path']}) {r['outcome']}"
        + (f", gate {r['verdict']}" if r["verdict"] else "")
        + f": {r['title']}. Claim {r['claim']}"
        + (f" from {r['paper']}" if r["paper"] else "")
        + (f". Result: {r['why'][:200]}" if r["why"] else "")
        for r in rows
    ]
    notes = notes_on(r["card"] for r in rows)
    return "\n".join(lines + (["Notes that name these cards:", *notes] if notes else []))
