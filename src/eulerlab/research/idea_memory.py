"""The idea lab's memory: every idea it tested, what each family has shown, and what to tell research (ADR-111).

    data/agents/memory/lab_ideas.jsonl   one line per card tested, appended, never edited

The lab forgot everything between runs until 2026-11-01, so it could neither
avoid retesting a dead idea nor lean towards what worked. This module is the
memory and the three things computed from it:

- **Family scores.** Each family's record is a Beta posterior on "a card from
  this family passes the IC screen": `Beta(1 + passed + 2 * survived,
  1 + tried - passed)`. Tomorrow's slots go to families by Thompson sampling
  from those posteriors (R&D-Agent(Q), research 131 finding 4): a family that
  keeps passing gets more tries, and a family never tried still gets some,
  because its wide posterior sometimes samples high.
- **Lessons.** Short rules computed from the record, each citing the
  experiences it rests on (ExpeL, research 131 finding 7). They are computed,
  never written by a model, so a lesson cannot claim what the record does not
  hold.
- **Feedback for the research agent.** Which families work, which are dead,
  which features drafts asked for that the library lacks, and the paper-search
  topics to look at next.

It reads and writes one file and computes; it backtests nothing and spends no
trial, so the research agent may import it too.

**Learning from results is still selection.** Choosing what to test next from
what passed is exactly the search the gate's bar exists to price. That is why
every card the lab tests is logged as a trial before its result is read
(`research/agent_trials.py`), and why each card carries its family, so the bar
counts families rather than variants (ADR-108).
"""

from __future__ import annotations

import hashlib
import random
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

FILE = Path("memory") / "lab_ideas.jsonl"
"""Under the agents' root (`data/agents`)."""

Source = Literal["template", "mutation", "flip", "combo", "model", "research"]


class Experience(BaseModel):
    """One card the lab tested, and what happened."""

    model_config = ConfigDict(extra="forbid")

    id: str = ""
    at: str
    day: str
    """The IST day of the run."""
    card: str
    """The card's label (a draft folder, or a generated idea's slug)."""
    path: str = ""
    family: str
    source: Source
    parent: str = ""
    """The idea this one was derived from, for mutations, flips and combinations."""
    features: list[str] = Field(default_factory=list)
    ic: dict[str, float] = Field(default_factory=dict)
    t: dict[str, float] = Field(default_factory=dict)
    screened_in: bool = False
    robust_sharpe: float | None = None
    annualised: float | None = None
    max_drawdown: float | None = None
    excess_sharpe: float | None = None
    """Annualised Sharpe of the daily return over Nifty; None when not measured."""
    survived: bool = False
    critical: list[str] = Field(default_factory=list)
    trials: int = 0
    stopped: str = ""
    min_turnover: float = 0.0
    """The card's liquidity floor in rupees (ADR-112). Generated cards tested before
    the floor existed have 0 and are left out of planning and lessons (`usable`)."""


def usable(experiences: Iterable[Experience], min_turnover: float) -> list[Experience]:
    """The experiences the lab learns from: research drafts, and its own cards tested
    at today's liquidity floor or stricter. The rest stay in the file, unread
    (2026-11-01: the first run's own cards had no floor and picked stocks that
    barely trade, HISTORY #48)."""
    return [e for e in experiences if e.source == "research" or e.min_turnover >= min_turnover]


def path_in(root: Path) -> Path:
    return root / FILE


def load(root: Path) -> list[Experience]:
    """Every experience, oldest first. A line that does not parse is skipped, not fatal."""
    path = path_in(root)
    if not path.exists():
        return []
    out: list[Experience] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            out.append(Experience.model_validate_json(line))
        except ValueError:
            continue
    return out


def experience_id(card: str, at: str) -> str:
    return hashlib.sha256(f"{card}|{at}".encode()).hexdigest()[:10]


def append(root: Path, experience: Experience) -> Experience:
    """Add one line. The id is set here, from the card and the time."""
    stamped = experience.model_copy(
        update={"id": experience.id or experience_id(experience.card, experience.at)}
    )
    path = path_in(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(stamped.model_dump_json() + "\n")
    return stamped


def tested_features(experiences: Iterable[Experience]) -> set[str]:
    return {f for e in experiences for f in e.features}


# --- family scores ----------------------------------------------------------


@dataclass(frozen=True)
class FamilyScore:
    family: str
    tried: int
    passed: int
    survived: int
    best_sharpe: float | None

    @property
    def alpha(self) -> float:
        return 1.0 + self.passed + 2.0 * self.survived

    @property
    def beta(self) -> float:
        return 1.0 + max(self.tried - self.passed, 0)

    @property
    def mean(self) -> float:
        return self.alpha / (self.alpha + self.beta)


def scores(
    experiences: Iterable[Experience], families: Iterable[str] = ()
) -> dict[str, FamilyScore]:
    """Each family's record. Families named in `families` appear even with no tries."""
    tally: dict[str, list[Any]] = {name: [0, 0, 0, None] for name in families}
    for e in experiences:
        row = tally.setdefault(e.family, [0, 0, 0, None])
        row[0] += 1
        row[1] += int(e.screened_in)
        row[2] += int(e.survived)
        if e.robust_sharpe is not None and (row[3] is None or e.robust_sharpe > row[3]):
            row[3] = e.robust_sharpe
    return {name: FamilyScore(name, *row) for name, row in sorted(tally.items())}


def seed_for(day: date, salt: str = "") -> int:
    """The same day gives the same draws, so a rerun plans the same ideas."""
    return int(hashlib.sha256(f"{day.isoformat()}|{salt}".encode()).hexdigest()[:12], 16)


def thompson(
    family_scores: dict[str, FamilyScore], eligible: Sequence[str], rng: random.Random
) -> str:
    """One draw from each eligible family's posterior; the highest wins."""
    best, best_draw = eligible[0], -1.0
    for name in eligible:
        s = family_scores.get(name) or FamilyScore(name, 0, 0, 0, None)
        draw = rng.betavariate(s.alpha, s.beta)
        if draw > best_draw:
            best, best_draw = name, draw
    return best


# --- lessons ----------------------------------------------------------------


@dataclass(frozen=True)
class Lesson:
    text: str
    cites: tuple[str, ...]
    """Ids of the experiences it rests on."""


DEAD_AFTER = 4
"""A family with this many tries and no card through the IC screen is called dead on this panel."""

STRONG_T = 2.0


def lessons(experiences: Sequence[Experience], *, limit: int = 12) -> list[Lesson]:
    """Rules computed from the record, strongest evidence first. Never written by a model."""
    out: list[Lesson] = []
    by_family: dict[str, list[Experience]] = {}
    for e in experiences:
        by_family.setdefault(e.family, []).append(e)

    survivors = sorted(
        (e for e in experiences if e.survived),
        key=lambda e: -(e.robust_sharpe or 0.0),
    )
    for e in survivors[:4]:
        out.append(
            Lesson(
                f"{', '.join(e.features) or e.card} ({e.family}) survived the backtest and the "
                f"skeptic: robust Sharpe {e.robust_sharpe:.2f}. Variants and papers on it are worth a look.",
                (e.id,),
            )
        )
    for family, rows in sorted(by_family.items()):
        passed = [e for e in rows if e.screened_in]
        if len(rows) >= DEAD_AFTER and not passed:
            out.append(
                Lesson(
                    f"{family}: 0 of {len(rows)} cards passed the IC screen. Treat it as dead on "
                    "this panel unless a paper gives a different way to measure it.",
                    tuple(e.id for e in rows),
                )
            )
        elif passed:
            out.append(
                Lesson(
                    f"{family}: {len(passed)} of {len(rows)} cards passed the IC screen, "
                    f"{sum(e.survived for e in rows)} survived the backtest.",
                    tuple(e.id for e in passed),
                )
            )
    flipped = [
        (e, f)
        for e in experiences
        for f in e.features
        if e.t.get(f, 0.0) <= -STRONG_T and e.source != "flip"
    ]
    for e, f in flipped[-4:]:
        out.append(
            Lesson(
                f"{f} predicted returns the wrong way (IC {e.ic.get(f, 0.0):+.3f}, t {e.t.get(f, 0.0):.1f}): "
                "it predicts the other way, and its reverse is the same test, so it is not run again.",
                (e.id,),
            )
        )
    return out[:limit]


# --- feedback for the research agent -----------------------------------------


class Feedback(BaseModel):
    """What the lab hands the research agent each run (`output.data["feedback"]`)."""

    model_config = ConfigDict(extra="forbid")

    topics: list[str] = Field(default_factory=list)
    """Paper-search phrases, most useful first. Research takes one a day, in turn."""
    working: list[str] = Field(default_factory=list)
    dead: list[str] = Field(default_factory=list)
    untried: list[str] = Field(default_factory=list)
    missing_features: list[str] = Field(default_factory=list)
    """Features that drafts named and the library cannot build."""
    lessons: list[str] = Field(default_factory=list)
    tested: int = 0


def feedback(
    experiences: Sequence[Experience],
    searches: dict[str, str],
    *,
    missing_features: Iterable[str] = (),
) -> Feedback:
    """`searches` maps each family to its paper-search phrase (`config/idea_families.yaml`)."""
    s = scores(experiences, searches)
    working = sorted((name for name, x in s.items() if x.passed), key=lambda n: (-s[n].mean, n))
    dead = sorted(n for n, x in s.items() if x.tried >= DEAD_AFTER and not x.passed)
    untried = sorted(n for n, x in s.items() if not x.tried)
    middle = sorted(
        (n for n in s if n not in working and n not in dead and n not in untried),
        key=lambda n: (-s[n].mean, n),
    )
    topics: list[str] = []
    for name in [*working, *untried, *middle]:
        phrase = searches.get(name)
        if phrase and phrase not in topics:
            topics.append(phrase)
    return Feedback(
        topics=topics,
        working=working,
        dead=dead,
        untried=untried,
        missing_features=sorted(set(missing_features)),
        lessons=[lesson.text for lesson in lessons(experiences)],
        tested=len(experiences),
    )


def guidance(fb: Feedback, *, limit: int = 8) -> str:
    """The feedback as a few lines for the paper agent's prompt. Our own data, not a paper's."""
    lines = []
    if fb.working:
        lines.append(
            f"- Families that have passed the idea lab's IC screen: {', '.join(fb.working)}."
        )
    if fb.dead:
        lines.append(
            f"- Families that failed every test so far (do not redraft them as they are): {', '.join(fb.dead)}."
        )
    if fb.missing_features:
        lines.append(
            "- Earlier drafts named features the library does not have "
            f"({', '.join(fb.missing_features[:6])}); write a formula instead."
        )
    lines.extend(f"- {text}" for text in fb.lessons[:limit])
    if not lines:
        return ""
    return "What the idea lab has learned from testing earlier ideas:\n" + "\n".join(lines)
