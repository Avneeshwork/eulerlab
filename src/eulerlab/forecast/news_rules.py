"""What news means for Indian equities: a knowledge base that corrects tone and grows (ADR-135).

The tone model scores words, and words mislead: "crude falls" reads negative
although cheaper oil helps India (research 148). A rule says what a kind of
news means for the market, so the brief can correct the tone with no model
request at all.

**Seeds** are the operator's, in `config/news_rules.yaml`. **Learned** rules
are this module's, in `LEARNED`, rebuilt from the judgement log on every run:

1. Every story the model judges "up" or "down" is appended to `JUDGED` with
   its tone, NewsData's score when held, and the rule that matched then.
2. A candidate rule is one subject group and one movement group from
   `learn` in the config, both found in a judged story that no seed covers.
   Its direction is the judgements' majority.
3. It is **active** once `activate` judgements agree and fewer than
   `deactivate` go against it; **off** once `deactivate` go against it;
   **proposed** otherwise. Rebuilding from the whole log each time means the
   same log always gives the same rules.

Seeds are never switched off here: judgements against a seed are counted and
the brief lists a contested seed for the operator. Nothing here trades or
changes the forecast's numbers.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from eulerlab.config import CONFIG_DIR

LEARNED = Path("data/derived/news_rules_learned.json")
JUDGED = Path("data/derived/news_judgements.jsonl")
# A corrected story's score: the rule's sign, at least this strong.
FLOOR = 0.5


class Rule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    when: list[str]
    unless: list[str] = Field(default_factory=list)
    direction: Literal["up", "down"]
    against: list[str] = Field(default_factory=list)
    why: str
    source: Literal["seed", "learned"] = "seed"
    status: Literal["active", "proposed", "off"] = "active"
    agree: int = 0
    disagree: int = 0
    examples: list[str] = Field(default_factory=list)


class Learn(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    activate: int
    deactivate: int
    subjects: dict[str, str]
    moves: dict[str, str]


class Book(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rules: list[Rule]
    learn: Learn


def seeds(config_dir: Path | None = None) -> Book:
    path = (config_dir or CONFIG_DIR) / "news_rules.yaml"
    return Book.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})


@lru_cache(maxsize=512)
def _rx(pattern: str) -> re.Pattern[str]:
    return re.compile(rf"\b(?:{pattern})\b", re.IGNORECASE)


def fits(rule: Rule, text: str) -> bool:
    return all(_rx(p).search(text) for p in rule.when) and not any(
        _rx(p).search(text) for p in rule.unless
    )


def match(text: str, rules: Sequence[Rule]) -> Rule | None:
    """The most specific active rule that fits: most `when` patterns; seeds before learned."""
    found = [r for r in rules if r.status == "active" and fits(r, text)]
    if not found:
        return None
    return max(found, key=lambda r: (len(r.when), r.source == "seed"))


def corrected(tone: float, rule: Rule | None) -> float:
    """The tone with the rule's sign, at least `FLOOR` strong; the tone itself when no rule fits."""
    if rule is None:
        return tone
    sign = 1.0 if rule.direction == "up" else -1.0
    return round(sign * max(abs(tone), FLOOR), 4)


# --- the learned rules ----------------------------------------------------------------------------


def load_learned(path: Path | None = None) -> dict[str, Any]:
    p = path or LEARNED
    if not p.exists():
        return {"rules": [], "seed_evidence": {}, "updated": ""}
    loaded = json.loads(p.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {"rules": [], "seed_evidence": {}, "updated": ""}


def learned_rules(path: Path | None = None) -> list[Rule]:
    return [Rule.model_validate(r) for r in load_learned(path).get("rules") or []]


def all_rules(book: Book | None = None, path: Path | None = None) -> list[Rule]:
    """Seeds, then learned rules; `match` uses only the active ones."""
    return [*(book or seeds()).rules, *learned_rules(path)]


def judged(path: Path | None = None) -> list[dict[str, Any]]:
    p = path or JUDGED
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def record(
    impacts: Iterable[Mapping[str, Any]],
    rules: Sequence[Rule],
    now: datetime,
    path: Path | None = None,
) -> int:
    """Append each judged story not already logged. Returns how many were added."""
    p = path or JUDGED
    have = {str(r.get("title")) for r in judged(p)}
    rows = []
    for x in impacts:
        title = str(x["title"])
        if title in have:
            continue
        have.add(title)
        text = f"{title} {x.get('description') or ''}"
        rule = match(text, rules)
        rows.append(
            {
                "title": title,
                "description": str(x.get("description") or ""),
                "tone": x.get("tone"),
                "newsdata": x.get("newsdata"),
                "direction": x["direction"],
                "severity": x["severity"],
                "rule": rule.id if rule else None,
                "rule_direction": rule.direction if rule else None,
                "event_time": x.get("event_time"),
                "knowledge_time": now.isoformat(),
            }
        )
    if rows:
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, sort_keys=True) + "\n")
    return len(rows)


def learn(
    book: Book, log: Sequence[Mapping[str, Any]]
) -> tuple[list[Rule], dict[str, dict[str, int]]]:
    """Learned rules and each seed's evidence, rebuilt from the whole judgement log."""
    cfg = book.learn
    seeds_on = [r for r in book.rules if r.status == "active"]
    evidence: dict[str, dict[str, int]] = {r.id: {"agree": 0, "disagree": 0} for r in book.rules}
    counts: dict[tuple[str, str], dict[str, list[str]]] = {}
    for j in log:
        said = str(j.get("direction"))
        if said not in ("up", "down"):
            continue
        text = f"{j.get('title', '')} {j.get('description') or ''}"
        seed = match(text, seeds_on)
        if seed is not None:
            evidence[seed.id]["agree" if seed.direction == said else "disagree"] += 1
            continue
        for s, sp in sorted(cfg.subjects.items()):
            if not _rx(sp).search(text):
                continue
            for m, mp in sorted(cfg.moves.items()):
                if _rx(mp).search(text):
                    counts.setdefault((s, m), {"up": [], "down": []})[said].append(
                        str(j.get("title", ""))
                    )
    out: list[Rule] = []
    for (s, m), by in sorted(counts.items()):
        direction: Literal["up", "down"] = "up" if len(by["up"]) >= len(by["down"]) else "down"
        agree, disagree = len(by[direction]), len(by["down" if direction == "up" else "up"])
        status: Literal["active", "proposed", "off"] = (
            "off"
            if disagree >= cfg.deactivate
            else "active"
            if agree >= cfg.activate
            else "proposed"
        )
        out.append(
            Rule(
                id=f"learned-{s}-{m}",
                when=[cfg.subjects[s], cfg.moves[m]],
                direction=direction,
                why=f"Learned from {agree} judged {'story' if agree == 1 else 'stories'} "
                f'(against: {disagree}), e.g. "{by[direction][0][:90]}"',
                source="learned",
                status=status,
                agree=agree,
                disagree=disagree,
                examples=by[direction][:3],
            )
        )
    return out, evidence


def update(
    book: Book | None = None,
    *,
    now: datetime,
    log_path: Path | None = None,
    path: Path | None = None,
) -> list[str]:
    """Rebuild and save the learned rules. Returns what changed, in words, for the brief."""
    book = book or seeds()
    before = {str(r["id"]): str(r["status"]) for r in load_learned(path).get("rules") or []}
    rules, evidence = learn(book, judged(log_path))
    changes = []
    for r in rules:
        was = before.get(r.id, "new")
        if was != r.status and r.status in ("active", "off"):
            changes.append(
                f"{'Switched on' if r.status == 'active' else 'Switched off'}: {r.id} "
                f"({r.direction}, {r.agree} for, {r.disagree} against)"
            )
    p = path or LEARNED
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(
            {
                "rules": [r.model_dump() for r in rules],
                "seed_evidence": evidence,
                "updated": now.isoformat(),
            },
            indent=1,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return changes


def contested(evidence: Mapping[str, Mapping[str, int]], deactivate: int) -> list[str]:
    """Seeds the judgements went against at least `deactivate` times and more often than for."""
    return [
        k
        for k, v in sorted(evidence.items())
        if v.get("disagree", 0) >= deactivate and v.get("disagree", 0) > v.get("agree", 0)
    ]


def agreement(log: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, float | int]]:
    """How often each score's sign matched the judged direction, over stories judged up or down."""
    out: dict[str, dict[str, float | int]] = {}
    sides = [j for j in log if j.get("direction") in ("up", "down")]

    def rate(name: str, sign_of: Any) -> None:
        pairs = [(sign_of(j), j["direction"]) for j in sides]
        pairs = [(s, d) for s, d in pairs if s is not None]
        if pairs:
            out[name] = {
                "n": len(pairs),
                "agree": round(sum(s == d for s, d in pairs) / len(pairs), 3),
            }

    def sign(value: Any) -> str | None:
        if not isinstance(value, int | float) or abs(value) < 0.3:
            return None
        return "up" if value > 0 else "down"

    rate("tone model", lambda j: sign(j.get("tone")))
    rate("NewsData", lambda j: sign(j.get("newsdata")))
    rate("rules", lambda j: j.get("rule_direction"))
    return out
