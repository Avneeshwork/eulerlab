"""The idea lab's own ideas: formula cards from the signal families, steered by its memory (ADR-111).

    config/idea_families.yaml  (families: a reason, templates, windows)
    memory (research/idea_memory.py)
        -> mutations of what passed: each window halved and doubled
        -> flips of what predicted the wrong way: neg(x)
        -> combinations of two passers from different families
        -> fresh templates, families chosen by Thompson sampling
        -> one card per idea under research/lab_ideas/<day>/, one configuration each

Until 2026-11-01 the lab tested only the research agent's drafts, about one a
week, and spent no trial in its first run because the only draft named a
feature the library lacks. A family list gives it a steady supply of ideas
that each have a reason written before any result.

**Every idea is a formula** in the formula language (`features/formula.py`),
so it is parsed and interpreted, never executed, and the lookahead firewall
holds. Each card has exactly one configuration, decided here and written to
the card before the card is tested.

**Nothing already tested is planned again**, by canonical formula text, and
the ten library features count as tested under their library names. The plan
for a day is the same on a rerun: every draw uses a seed made from the date.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import random
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from eulerlab.features import formula
from eulerlab.research import idea_memory
from eulerlab.research.idea_memory import Experience, Source

CONFIG = Path("config/idea_families.yaml")
FOLDER = Path("research/lab_ideas")
"""Generated cards. Gitignored like `research/agent_drafts/`: a survivor is
registered by the operator, which copies it into `hypotheses/`."""

PROMISING_T = 1.0
"""A card that missed the screen with every feature's t at least this high still gets its windows varied."""

COMBO_WINDOW = 252
"""Two signals on different scales are combined through their time-series rank over a year."""


class Family(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    reason: str = Field(min_length=20)
    paper: str = ""
    search: str = Field(min_length=5)
    rebalance: int = Field(default=21, ge=1, le=252)
    templates: list[str] = Field(min_length=1)
    windows: dict[str, list[int]] = Field(default_factory=dict)


class Families(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    top_n: int = Field(default=30, ge=5, le=200)
    min_turnover: float = Field(default=0.0, ge=0.0)
    """Rupees of turnover on the day for a stock to be eligible (ADR-112)."""
    families: dict[str, Family]


def load_families(path: Path = CONFIG) -> Families:
    return Families.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})


_PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")


def canonical(text: str) -> str:
    """`formula:<canonical text>`, or the library name when it is one of the ten zoo features."""
    node = formula.parse(text)
    body = formula.text_of(node)
    for entry in formula.ZOO:
        if formula.text_of(formula.parse(entry.text)) == body:
            return entry.name
    return formula.PREFIX + body


def expand(family: Family) -> list[str]:
    """Every formula a family's templates make, in the file's order, canonical, without repeats."""
    out: list[str] = []
    for template in family.templates:
        keys = list(dict.fromkeys(_PLACEHOLDER.findall(template)))
        missing = [k for k in keys if k not in family.windows]
        if missing:
            msg = f"template {template!r} uses {missing} with no windows"
            raise ValueError(msg)
        for values in itertools.product(*(family.windows[k] for k in keys)):
            text = template.format(**dict(zip(keys, values, strict=True)))
            try:
                name = canonical(text)
            except formula.FormulaError:
                continue
            if name not in out:
                out.append(name)
    return out


@dataclass(frozen=True)
class Idea:
    feature: str
    family: str
    source: Source
    reason: str
    rebalance: int
    parent: str = ""

    @property
    def slug(self) -> str:
        """Readable and unique per feature, so a rerun finds the same folder for the same idea."""
        text = self.feature.removeprefix(formula.PREFIX)
        readable = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:48] or "idea"
        return f"{readable}-{hashlib.sha256(self.feature.encode()).hexdigest()[:6]}"


@dataclass
class Plan:
    ideas: list[Idea] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def _params(node: formula.Node) -> list[int]:
    out = list(node.params)
    for a in node.args:
        out.extend(_params(a))
    return out


def _replace_param(node: formula.Node, index: int, value: int) -> tuple[formula.Node, int]:
    """The tree with its `index`-th window (depth first) set to `value`."""
    params = list(node.params)
    if index < len(params):
        params[index] = value
        return node.model_copy(update={"params": tuple(params)}), -1
    index -= len(params)
    args = list(node.args)
    for i, a in enumerate(args):
        new, index = _replace_param(a, index, value)
        if index < 0:
            args[i] = new
            return node.model_copy(update={"args": tuple(args)}), -1
    return node, index


def neighbours(feature: str) -> list[str]:
    """Each window of a formula halved and doubled, one at a time, within the language's limits."""
    try:
        node = formula.parse(feature)
    except formula.FormulaError:
        return []
    out: list[str] = []
    for i, p in enumerate(_params(node)):
        if p < 5:
            continue  # ret(1) and other lags are part of the idea, not a window to vary
        for q in (p // 2, p * 2):
            if not 2 <= q <= formula.MAX_WINDOW:
                continue
            new, _ = _replace_param(node, i, q)
            try:
                name = canonical(formula.text_of(new))
            except formula.FormulaError:
                continue
            if name != feature and name not in out:
                out.append(name)
    return out


def flip(feature: str) -> str | None:
    """The reverse signal: neg(x), or x when the formula already is neg(x)."""
    try:
        node = formula.parse(feature)
    except formula.FormulaError:
        return None
    new = node.args[0] if node.op == "neg" else formula.Node(op="neg", args=(node,))
    try:
        return canonical(formula.text_of(new))
    except formula.FormulaError:
        return None


def combine(a: str, b: str) -> str | None:
    """add(ts_rank(a, 252), ts_rank(b, 252)): two signals, each scaled to its own year."""
    text = f"add(ts_rank({_body(a)}, {COMBO_WINDOW}), ts_rank({_body(b)}, {COMBO_WINDOW}))"
    try:
        return canonical(text)
    except formula.FormulaError:
        return None


def _body(feature: str) -> str:
    """A formula's text, or a library feature's formula from the zoo."""
    for entry in formula.ZOO:
        if entry.name == feature:
            return entry.text
    return feature.removeprefix(formula.PREFIX)


def plan(
    families: Families,
    experiences: list[Experience],
    *,
    n: int,
    day: date,
    exclude: set[str] | None = None,
    min_t: float = 2.0,
) -> Plan:
    """Up to `n` untested ideas for `day`: about a third from what the memory says, the rest fresh."""
    rng = random.Random(idea_memory.seed_for(day, "plan"))
    taken: set[str] = set(idea_memory.tested_features(experiences)) | set(exclude or ())
    out = Plan()
    by_name = families.families

    def add(idea: Idea) -> bool:
        if idea.feature in taken or len(out.ideas) >= n:
            return False
        taken.add(idea.feature)
        out.ideas.append(idea)
        return True

    passers = [e for e in experiences if e.screened_in and e.features]
    passers.sort(key=lambda e: (-int(e.survived), -(e.robust_sharpe or 0.0), e.at))
    promising = passers + sorted(
        (
            e
            for e in experiences
            if not e.screened_in
            and e.features
            and min(e.t.get(f, 0.0) for f in e.features) >= PROMISING_T
        ),
        key=lambda e: (-min(e.t.get(f, 0.0) for f in e.features), e.at),
    )
    queues = {name: [f for f in expand(fam) if f not in taken] for name, fam in by_name.items()}
    fresh = sum(len(q) for q in queues.values())
    # A third of the day goes to what the memory suggests while fresh templates remain;
    # once they run low, the memory gets every slot they cannot fill.
    learned_slots = 0 if not experiences else max(n // 3, n - fresh, 1)

    # 1. Flips: a signal that predicted strongly the wrong way gets one test of its reverse.
    for e in experiences:
        if e.source == "flip" or len(out.ideas) >= learned_slots:
            continue
        for f in e.features:
            if e.t.get(f, 0.0) <= -min_t:
                reverse = flip(f)
                if reverse:
                    fam = by_name.get(e.family)
                    add(
                        Idea(
                            reverse,
                            e.family,
                            "flip",
                            f"The reverse of {f}, which predicted returns the wrong way "
                            f"(IC {e.ic.get(f, 0.0):+.3f}, t {e.t.get(f, 0.0):.1f}).",
                            fam.rebalance if fam else 21,
                            parent=f,
                        )
                    )

    # 2. Combinations: two passers from different families, up to a third of the learned slots.
    pairs = [
        (a, b)
        for a, b in itertools.combinations(passers[:8], 2)
        if a.family != b.family and a.features and b.features
    ]
    combo_cap = len(out.ideas) + max(learned_slots // 3, 1)
    for a, b in pairs:
        if len(out.ideas) >= min(combo_cap, learned_slots):
            break
        combo = combine(a.features[0], b.features[0])
        if combo:
            add(
                Idea(
                    combo,
                    "combo",
                    "combo",
                    f"Two signals that each passed the IC screen, from different families "
                    f"({a.family} and {b.family}), each ranked against its own past year.",
                    21,
                    parent=f"{a.features[0]} + {b.features[0]}",
                )
            )

    # 3. Mutations: each window of a passer (then a near-passer) halved and doubled.
    for e in promising:
        if len(out.ideas) >= learned_slots:
            break
        fam = by_name.get(e.family)
        for f in e.features:
            for m in neighbours(f):
                if len(out.ideas) >= learned_slots:
                    break
                add(
                    Idea(
                        m,
                        e.family,
                        "mutation",
                        f"A window variant of {f}, which "
                        + ("passed the IC screen" if e.screened_in else "came close to it")
                        + f" (IC {e.ic.get(f, 0.0):+.3f}, t {e.t.get(f, 0.0):.1f}).",
                        fam.rebalance if fam else 21,
                        parent=f,
                    )
                )

    # 4. Fresh templates, families by Thompson sampling.
    queues = {name: [f for f in q if f not in taken] for name, q in queues.items()}
    family_scores = idea_memory.scores(experiences, by_name)
    while len(out.ideas) < n:
        eligible = [name for name, q in queues.items() if q]
        if not eligible:
            out.skipped.append("every family template is already tested")
            break
        name = idea_memory.thompson(family_scores, eligible, rng)
        feature = queues[name].pop(0)
        fam = by_name[name]
        add(Idea(feature, name, "template", fam.reason, fam.rebalance))
    return out


MODEL_SYSTEM = """You propose stock-selection signals for EulerLab's idea lab, for Indian equities on daily bars.

Each signal is a formula in this language, and nothing else:
{operators}

A formula is a function of ONE stock's own past (close, volume, turnover). Stocks are ranked by it and the
top {top_n} are held. Higher must mean "expected to do better".

Reply with ONE JSON object and nothing else:
{{"ideas": [{{"family": "<one of: {families}, or new>", "formula": "<formula>", "reason": "one or two sentences: the economic reason, written before any test"}}]}}

Rules:
- At most {count} ideas. Each must differ from every formula listed as already tested.
- Prefer families the lessons say are working, and new ideas with a clear reason; never a family the lessons call dead in the same form.
- Never claim a result, a Sharpe or a number you were not given."""


def proposals(answer: str, families: Families, taken: set[str], *, limit: int) -> list[Idea]:
    """The model's ideas that parse, are new and have a reason. Everything else is dropped."""
    start, end = answer.find("{"), answer.rfind("}")
    if start < 0 or end <= start:
        return []
    try:
        raw = json.loads(answer[start : end + 1])
    except ValueError:
        return []
    out: list[Idea] = []
    seen = set(taken)
    for item in raw.get("ideas", []) if isinstance(raw, dict) else []:
        if not isinstance(item, dict) or len(out) >= limit:
            continue
        reason = str(item.get("reason", "")).strip()
        try:
            feature = canonical(str(item.get("formula", "")))
        except formula.FormulaError:
            continue
        if feature in seen or len(reason) < 20:
            continue
        name = str(item.get("family", "new")).strip()
        fam = families.families.get(name)
        seen.add(feature)
        out.append(
            Idea(
                feature,
                name if fam else "model",
                "model",
                reason[:400],
                fam.rebalance if fam else 21,
            )
        )
    return out


def model_prompt(
    families: Families, taken: set[str], lessons_text: str, *, count: int
) -> tuple[str, str]:
    """The system prompt and the user message for one request for ideas."""
    system = MODEL_SYSTEM.format(
        operators=formula.describe(),
        top_n=families.top_n,
        families=", ".join(families.families),
        count=count,
    )
    shown = sorted(f.removeprefix(formula.PREFIX) for f in taken)[-60:]
    user = (
        f"{lessons_text or 'The lab has no lessons yet.'}\n\n"
        f"Already tested ({len(taken)}; the latest 60 shown):\n"
        + "\n".join(f"- {t}" for t in shown)
        + f"\n\nPropose up to {count} new formulas."
    )
    return system, user


def card(
    idea: Idea,
    *,
    top_n: int,
    holdout_starts: date,
    day: date,
    paper: str = "",
    min_turnover: float = 0.0,
) -> dict[str, Any]:
    """The card for one idea: the claim, the family's reason, one configuration, red flags."""
    shown = idea.feature.removeprefix(formula.PREFIX)
    return {
        "id": "PENDING",
        "title": f"{idea.family.replace('_', ' ')}: {shown}"[:120],
        "status": "draft",
        "family": idea.family,
        "source_kind": idea.source,
        "parent": idea.parent,
        "claim": (
            f"Indian stocks ranked highest by {shown} earn more over the next month than the rest; "
            f"holding the top {top_n}, equal-weighted, rebalanced every {idea.rebalance} sessions, "
            "beats Nifty after realistic costs."
        ),
        "rationale": idea.reason + (f" Best-known study: {paper}." if paper else ""),
        "source": {"generated_by": "idea lab (ADR-111)", "day": day.isoformat()},
        "configurations": [
            {
                "shape": "rank_and_hold",
                "feature": idea.feature,
                "top_n": top_n,
                "rebalance": idea.rebalance,
                **({"min_turnover": min_turnover} if min_turnover else {}),
            }
        ],
        "red_flags": [
            "Generated by the idea lab from a family template, not read from a paper: the reason is "
            "the family's, written before the test, and has not been checked on Indian data.",
            "Many ideas are tested each day; a pass here is one of many tries and the gate's bar "
            "is what prices that search, not this screen.",
            f"Rebalancing every {idea.rebalance} sessions across {top_n} names pays costs that a "
            "small or illiquid stock can make larger than the backtest's model.",
        ],
        "holdout": {"starts": holdout_starts.isoformat(), "status": "unread"},
    }


def write_cards(
    ideas: list[Idea],
    families: Families,
    *,
    day: date,
    holdout_starts: date,
    folder: Path = FOLDER,
) -> list[tuple[Idea, Path]]:
    """One folder per idea under `folder/<day>/`. An existing card is left as it is.

    The folder name carries the liquidity floor, so a card written before the
    floor existed is never reused for the same idea with one (ADR-112).
    """
    out: list[tuple[Idea, Path]] = []
    base = folder / day.isoformat()
    floor = f"-liq{families.min_turnover:.0f}" if families.min_turnover else ""
    for idea in ideas:
        target = base / f"{idea.slug}{floor}"
        path = target / "card.yaml"
        if not path.exists():
            target.mkdir(parents=True, exist_ok=True)
            fam = families.families.get(idea.family)
            spec = card(
                idea,
                top_n=families.top_n,
                holdout_starts=holdout_starts,
                day=day,
                paper=fam.paper if fam else "",
                min_turnover=families.min_turnover,
            )
            path.write_text(yaml.safe_dump(spec, sort_keys=False, allow_unicode=True), "utf-8")
        out.append((idea, path))
    return out
