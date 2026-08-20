"""Hypothesis cards: a spec written before the evidence, never a prose summary.

`CLAUDE.md`: *Turn any strategy paper into a `hypotheses/H-NNNN.yaml` spec, not
a prose summary. Include a `red_flags` list.*

The distinction is the whole point. A prose summary describes what a paper
said; a card commits, in advance, to a claim, to which configurations may be
tried, and to what would make it wrong. Only the second can be tested, because
only the second cannot be reworded once the numbers arrive.

**Red flags are the part that matters and the part most easily faked.** Their
purpose is to write down, before you are invested, the objections you would
otherwise rationalise away afterwards. A card that lists "markets can change"
has technically complied and actually done nothing. So `validate` rejects red
flags that are generic, and the test for generic is deliberately crude — a
short sentence with no numbers, no named risk, and no reference to this
project's own data is not an objection, it is a hedge.

That check will occasionally reject a real objection that happens to be
briefly worded. Good: the cost of rewriting one is trivial and the cost of a
card full of hedges is a gate that passes things it should not.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import yaml

HYPOTHESES = Path("hypotheses")

MIN_RED_FLAGS = 3
MIN_RED_FLAG_WORDS = 12
MIN_CONFIGURATIONS = 2

_VAGUE = re.compile(
    r"^(markets?\s+(can\s+)?change|past\s+performance|no\s+guarantee|"
    r"results?\s+may\s+vary|this\s+may\s+not\s+work|needs?\s+more\s+(work|data|research))",
    re.IGNORECASE,
)

_SPECIFIC_SIGNAL = re.compile(
    r"\d|Sprint\s+\d+|S-\d{3}|A-\d{3}|T-\d{3,4}|"
    r"microcap|liquidity|turnover|regime|crash|cost|slippage|impact|survivorship|"
    r"crowded|decay|capacity|lookahead|holdout",
    re.IGNORECASE,
)


@dataclass
class Card:
    """One hypothesis, in the shape the gate already understands."""

    id: str
    title: str
    claim: str
    configurations: list[dict[str, Any]]
    red_flags: list[str]
    holdout_starts: date
    source_url: str = ""
    source_fetched: str = ""
    rationale: str = ""
    status: str = "draft"

    def to_yaml(self) -> str:
        body: dict[str, Any] = {
            "id": self.id,
            "title": self.title,
            "status": self.status,
            "claim": self.claim.strip(),
        }
        if self.rationale:
            body["rationale"] = self.rationale.strip()
        if self.source_url:
            body["source"] = {"url": self.source_url, "fetched": self.source_fetched}
        body["configurations"] = self.configurations
        body["red_flags"] = self.red_flags
        body["holdout"] = {"starts": self.holdout_starts.isoformat(), "status": "unread"}
        return yaml.safe_dump(body, sort_keys=False, allow_unicode=True, width=80)


@dataclass
class Validation:
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def validate(card: Card) -> Validation:
    """Reject a card that cannot function as a pre-registration.

    Everything here is refused rather than warned about. A warning on a
    hypothesis card is a warning nobody reads once the backtest looks good.
    """
    result = Validation()

    if not re.fullmatch(r"H-\d{4}", card.id):
        result.problems.append(f"id {card.id!r} must look like H-0001")
    if len(card.claim.split()) < 15:
        result.problems.append(
            "the claim is too short to be falsifiable; say what is predicted, "
            "for which instruments, and net of what"
        )
    if len(card.configurations) < MIN_CONFIGURATIONS:
        result.problems.append(
            f"{len(card.configurations)} configuration(s); PBO needs at least "
            f"{MIN_CONFIGURATIONS} to measure whether *choosing* between them picks noise"
        )
    if not card.source_url:
        result.problems.append(
            "no source URL. CLAUDE.md forbids inventing a source, and an "
            "uncited card poisons the one artefact the gate depends on"
        )

    if len(card.red_flags) < MIN_RED_FLAGS:
        result.problems.append(
            f"{len(card.red_flags)} red flag(s), need {MIN_RED_FLAGS}. These are the "
            f"objections you would rationalise away later"
        )
    for flag in card.red_flags:
        text = flag.strip()
        if _VAGUE.match(text):
            result.problems.append(f"red flag is a hedge, not an objection: {text[:60]!r}")
        elif len(text.split()) < MIN_RED_FLAG_WORDS or not _SPECIFIC_SIGNAL.search(text):
            result.problems.append(
                f"red flag is too generic to test against: {text[:60]!r} — name a "
                f"number, a mechanism, or a specific finding from this project"
            )
    return result


def next_id(directory: Path = HYPOTHESES) -> str:
    """The next free H-NNNN, never reusing a retired one.

    Ids are not recycled even when a hypothesis is killed. The trial ledger
    refers to them, and a reused id would silently merge two different claims
    in the audit trail — which is exactly the resubmission the ledger exists
    to make visible.
    """
    existing = {p.stem for p in directory.glob("H-*.yaml")} if directory.exists() else set()
    n = 1
    while f"H-{n:04d}" in existing:
        n += 1
    return f"H-{n:04d}"


def write(card: Card, directory: Path = HYPOTHESES) -> Path:
    """Persist a validated card. Refuses to overwrite.

    A card is a pre-registration; overwriting one would let a claim be edited
    after its evidence existed, which is the one thing pre-registration is for.
    """
    checked = validate(card)
    if not checked.ok:
        msg = "card is not a valid pre-registration:\n  " + "\n  ".join(checked.problems)
        raise ValueError(msg)

    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{card.id}.yaml"
    if path.exists():
        msg = (
            f"{path} already exists. A hypothesis card is a pre-registration and is "
            f"never rewritten — use a new id, which keeps the resubmission visible."
        )
        raise FileExistsError(msg)
    path.write_text(card.to_yaml(), encoding="utf-8")
    return path
