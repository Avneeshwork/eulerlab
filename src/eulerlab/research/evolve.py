"""The evolutionary search: rules bred from rules, a model proposing and code judging (ADR-177).

The autopilot writes ten rules a night in one shot. Here a night is a budget
of candidates, each a small change to a rule that already did something:

    islands     intraday and swing, each split by the kind of data a rule reads
                (price, volume, events, flows); half the night goes to each side
    bandit      Thompson sampling picks the island for each candidate from what
                each island has yielded; an island tried many times with nothing
                admitted is closed
    parent      drawn from the island's pool: better rules more often, and a
                bonus for lineages that have had few children
    child       the model proposes changes to the parent (given its results and
                its lineage), or code does: swap a field, add or drop a condition,
                flip an intraday side, change the shape, or cross two parents.
                Changing only a number, a window or the hold is not a move: it
                is the same idea (ADR-209)
    judge       code only. The child must be a new idea (`research/novelty.py`;
                refused before it is screened, so it spends nothing), compile
                (no look-ahead), be new, pass
                the engine's screen and bias checks, not move with a strategy
                already passed (0.5), and not move with a pool member (0.7).
                Fitness is net Sharpe less a charge for size and for likeness.
    survivors   the best admitted rule of each island that also holds on the
                selection period becomes a card. It waits for the gate in the
                autopilot's queue, under the same weekly allowance.

Every candidate is one row in the experiment store (with its parents) and one
row in `data/derived/evolve.jsonl`. The pool is rebuilt from that file, so a
night can be replayed and nothing is kept in memory between nights. The elite
(the best few of each island) are never dropped when a pool is full.

The same day gives the same draws.
"""

from __future__ import annotations

import json
import math
import random
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from eulerlab import constitution
from eulerlab.db.stream import add_row, read_rows
from eulerlab.features import formula
from eulerlab.features.formula import Node
from eulerlab.paths import data_path
from eulerlab.research import idea_memory, lang, novelty
from eulerlab.validation import firewall

KIND = "evolve"
GROUPS: dict[str, tuple[str, ...]] = {
    "flows": ("fii_net", "dii_net", "fii_futures_net", "dii_futures_net", "news_impact"),
    "events": ("results_morning", "bulk_buy", "bulk_sell", "promoter_buy"),
    "volume": ("delivery_ratio", "value_ratio"),
    "price": ("gap", "ret", "day_return", "at_high", "at_low"),
}
"""A rule belongs to the first group, in this order, that any of its fields is in."""
ISLANDS = tuple(f"{kind}:{group}" for kind in ("intraday", "swing") for group in GROUPS)

# ASSUMPTION: A-138 — the search's own settings, chosen by hand and not tuned on results.
POOL = 30
ELITE = 3
SAME_BET = 0.5
JOIN_AT = firewall.JOIN_AT
SIZE_CHARGE = 0.3
LIKENESS_CHARGE = 0.3
NEGLECT = 1.0
SATURATED = 60
MODEL_SHARE = 0.25
PER_ISLAND = 1
CONDITIONS = (
    "ge(abs(gap), 0.02)",
    "le(delay(ret(5), 1), -0.05)",
    "ge(delay(ret(20), 1), 0.1)",
    "ge(delay(delivery_ratio, 1), 1.5)",
    "ge(delay(value_ratio, 1), 2)",
    "has(delay(bulk_buy, 1))",
    "has(delay(at_high(20), 1))",
    "has(delay(at_low(20), 1))",
    "lt(delay(fii_net, 1), 0)",
    "gt(delay(dii_net, 1), 0)",
)


def path_for() -> Path:
    return data_path("derived/evolve.jsonl")


def island_of(spec: lang.Spec) -> str:
    used = set(spec.complexity["fields"])
    group = next((g for g, names in GROUPS.items() if used & set(names)), "price")
    return f"{spec.kind}:{group}"


@dataclass(frozen=True)
class Member:
    id: str
    spec: lang.Spec
    island: str
    fitness: float
    sharpe: float
    root: str
    """The id of the first rule of this lineage."""
    generation: int
    parents: tuple[str, ...] = ()


@dataclass
class Pool:
    """Tonight's view of every island, rebuilt from the file."""

    members: dict[str, Member] = field(default_factory=dict)
    tried: dict[str, int] = field(default_factory=dict)
    admitted: dict[str, int] = field(default_factory=dict)
    seen: set[str] = field(default_factory=set)
    children: dict[str, int] = field(default_factory=dict)
    """Candidates bred from each lineage, by its root."""
    returns: dict[str, dict[date, float]] = field(default_factory=dict)

    def of(self, island: str) -> list[Member]:
        found = [m for m in self.members.values() if m.island == island]
        return sorted(found, key=lambda m: (-m.fitness, m.id))

    def elite(self, island: str) -> list[Member]:
        return sorted(self.of(island), key=lambda m: (-m.sharpe, m.id))[:ELITE]


def load(
    path: Path | None = None, returns: Callable[[str], dict[date, float]] | None = None
) -> Pool:
    pool = Pool()
    for row in read_rows(path or path_for(), KIND):
        island = str(row["island"])
        if row["event"] == "try":
            pool.tried[island] = pool.tried.get(island, 0) + 1
            pool.seen.add(str(row["fingerprint"]))
            if row.get("root"):
                pool.children[row["root"]] = pool.children.get(row["root"], 0) + 1
        elif row["event"] == "admit":
            pool.admitted[island] = pool.admitted.get(island, 0) + 1
            member = Member(
                id=str(row["id"]),
                spec=lang.Spec.model_validate(row["spec"]),
                island=island,
                fitness=float(row["fitness"]),
                sharpe=float(row["sharpe"]),
                root=str(row["root"]),
                generation=int(row["generation"]),
                parents=tuple(row.get("parents") or ()),
            )
            pool.members[member.id] = member
            if returns is not None:
                pool.returns[member.id] = returns(member.id)
        elif row["event"] == "drop":
            pool.members.pop(str(row["id"]), None)
            pool.returns.pop(str(row["id"]), None)
    return pool


# --- breeding ----------------------------------------------------------------------------


def _replace(node: Node, target: int, new: Callable[[Node], Node], counter: list[int]) -> Node:
    """A copy of the tree with its `target`-th node (walk order) passed through `new`."""
    index = counter[0]
    counter[0] += 1
    if index == target:
        return new(node)
    args = tuple(_replace(a, target, new, counter) for a in node.args)
    return node.model_copy(update={"args": args})


def _edit(
    text: str, pick: Callable[[Node], bool], new: Callable[[Node], Node], rng: random.Random
) -> str:
    tree = lang.compile_text(text)
    spots = [i for i, n in enumerate(formula._walk(tree)) if pick(n)]
    if not spots:
        return text
    return formula.text_of(_replace(tree, rng.choice(spots), new, [0]))


def _group_of(name: str) -> tuple[str, ...]:
    return next((names for names in GROUPS.values() if name in names), ())


def mutate(
    parent: lang.Spec, rng: random.Random, other: lang.Spec | None = None
) -> lang.Spec | None:
    """One small change to `parent`, or None when it makes no valid rule or no new idea."""
    body = parent.model_dump(mode="json")
    # No number, window or hold moves: each gives the parent's idea back (ADR-209).
    moves = ["field", "add", "drop", "shape"]
    if parent.kind == "intraday":
        moves.append("side")
    if other is not None and other.kind == parent.kind:
        moves.append("cross")
    move = rng.choice(moves)
    key = rng.choice(["when", "score"])
    if move == "field":

        def swap(n: Node) -> Node:
            choices = [
                f for f in _group_of(n.op) if lang.FIELDS[f].window == lang.FIELDS[n.op].window
            ]
            return n.model_copy(update={"op": rng.choice(choices)}) if choices else n

        body[key] = _edit(body[key], lambda n: n.op in lang.FIELDS, swap, rng)
    elif move == "add":
        body["when"] = f"and({parent.when}, {rng.choice(CONDITIONS)})"
    elif move == "drop":
        tree = parent.trees["when"]
        if tree.op != "and":
            return None
        body["when"] = formula.text_of(rng.choice(tree.args))
    elif move == "side":
        body["side"] = {"long": "short", "short": "long"}.get(parent.side, parent.side)
    elif move == "shape":
        body["shape"] = "cross_section" if parent.shape == "event" else "event"
        body["top"] = rng.choice((3, 5, 10))
        body["every"] = max(1, parent.hold) if parent.kind == "swing" else 1
    else:
        assert other is not None
        body["score"] = other.score
    try:
        child = lang.Spec.model_validate(body)
    except (ValidationError, formula.FormulaError):
        return None
    # A swap that lands on the same field, or a new score on an event rule, is the parent's idea.
    return None if novelty.rule_key(child) == novelty.rule_key(parent) else child


def choose_parent(
    members: Sequence[Member], children: Mapping[str, int], rng: random.Random
) -> Member:
    """Better rules more often; a lineage with few children gets a bonus."""
    ranked = sorted(members, key=lambda m: (m.fitness, m.id))
    weights = [
        ((i + 1) / len(ranked)) * (1.0 + NEGLECT / math.sqrt(1.0 + children.get(m.root, 0)))
        for i, m in enumerate(ranked)
    ]
    return rng.choices(ranked, weights=weights, k=1)[0]


SYSTEM = (
    "You improve trading rules for Indian cash equities by small, reasoned changes. "
    "You answer with JSON only. You never see prices and you never claim a result."
)


def prompt(parent: Member, line: Sequence[Member], count: int) -> str:
    history = "\n".join(
        f"  generation {m.generation}: net Sharpe {m.sharpe:+.2f}  {m.spec.describe()}"
        for m in line
    )
    return (
        f"{lang.describe()}\n\nThe rule to change (net Sharpe {parent.sharpe:+.2f} on the screen):\n"
        f"{json.dumps(parent.spec.model_dump(mode='json'))}\n\nIts lineage so far:\n{history}\n\n"
        f"Propose {count} different changed rules. Each must keep kind '{parent.spec.kind}', "
        "change one or two things, and say in one sentence why the change should help. "
        "Change what the rule reads or how (a field, a condition, the side, the shape), never "
        f"only a number, window or hold. {novelty.REPEAT_RULE} "
        'Answer as {"cards": [{"spec": {...}, "why": "..."}]}.'
    )


def proposals(answer: str) -> list[lang.Spec]:
    """The valid rules in a model's answer. An invalid one is dropped, not repaired."""
    from eulerlab.agents.workers.autopilot import parse

    out: list[lang.Spec] = []
    for card in parse(answer):
        try:
            out.append(lang.Spec.model_validate(card.get("spec")))
        except (ValidationError, formula.FormulaError):
            continue
    return out


# --- judging -----------------------------------------------------------------------------


def _correlation(a: Mapping[date, float], b: Mapping[date, float]) -> float | None:
    from eulerlab.research.autopilot import correlation

    return correlation(dict(a), dict(b))


def judge(
    spec: lang.Spec,
    found: Mapping[str, Any],
    pool: Pool,
    peers: Mapping[str, Mapping[date, float]],
) -> tuple[float | None, str]:
    """(fitness, "") when the rule may join the pool, or (None, why not)."""
    if not found.get("clean"):
        return None, "did not pass the screen and its bias checks"
    sharpe = (found.get("net") or {}).get("sharpe")
    if sharpe is None:
        return None, "no Sharpe"
    daily = found.get("daily") or {}
    for name, series in peers.items():
        c = _correlation(daily, series)
        if c is not None and abs(c) > SAME_BET:
            return None, f"moves with {name} ({c:+.2f}): the same bet as a strategy already passed"
    for member_id, series in pool.returns.items():
        c = _correlation(daily, series)
        if c is not None and c >= JOIN_AT:
            return None, f"moves with pool member {member_id} ({c:+.2f})"
    others = [m.spec.trees["when"] for m in pool.members.values()]
    likeness = formula.max_similarity(spec.trees["when"], others)
    size = spec.complexity["size"] / lang.MAX_NODES
    return float(sharpe) - SIZE_CHARGE * size - LIKENESS_CHARGE * likeness, ""


def allot(budget: int, pool: Pool, rng: random.Random, forward: Mapping[str, int]) -> list[str]:
    """The island of each of tonight's candidates: half intraday, half swing, by Thompson draws."""
    scores = {
        island: idea_memory.FamilyScore(
            island,
            pool.tried.get(island, 0),
            pool.admitted.get(island, 0),
            forward.get(island, 0),
            None,
        )
        for island in ISLANDS
    }
    out: list[str] = []
    for kind, share in (("intraday", budget // 2), ("swing", budget - budget // 2)):
        open_ = [
            i
            for i in ISLANDS
            if i.startswith(kind)
            and not (pool.tried.get(i, 0) >= SATURATED and not pool.admitted.get(i, 0))
        ]
        out += [idea_memory.thompson(scores, open_, rng) for _ in range(share)] if open_ else []
    return out


@dataclass
class Night:
    tried: int = 0
    admitted: list[Member] = field(default_factory=list)
    refused: dict[str, int] = field(default_factory=dict)
    from_model: int = 0
    closed: list[str] = field(default_factory=list)


Evaluate = Callable[[lang.Spec, str, Sequence[str]], dict[str, Any]]
"""(rule, island, parent ids) -> the screen's result with `daily` and the experiment `id`."""


def run(
    *,
    budget: int,
    seeds: Sequence[lang.Spec],
    evaluate: Evaluate,
    peers: Mapping[str, Mapping[date, float]],
    day: date,
    ask: Callable[[str, str], str] | None = None,
    forward: Mapping[str, int] | None = None,
    path: Path | None = None,
    returns: Callable[[str], dict[date, float]] | None = None,
    now: datetime | None = None,
    ideas: novelty.Seen | None = None,
) -> Night:
    """One night of search. Everything it does is appended to the file at `path`.

    `ideas` holds the ideas tried before tonight (ADR-209). A child whose idea is
    among them, or tried earlier tonight, is refused before it is evaluated; a
    seed (no parents) is where an island starts and is not checked."""
    path = path or path_for()
    rng = random.Random(idea_memory.seed_for(day, "evolve"))
    pool = load(path, returns)
    night = Night()
    night.closed = [
        i for i in ISLANDS if pool.tried.get(i, 0) >= SATURATED and not pool.admitted.get(i, 0)
    ]
    stamp = (now or datetime.now(UTC)).isoformat(timespec="seconds")
    waiting: dict[str, list[lang.Spec]] = {}
    taken = ideas.copy() if ideas is not None else novelty.Seen()
    for m in pool.members.values():
        taken.add(novelty.rule_key(m.spec), m.id)

    def consider(spec: lang.Spec, parents: Sequence[Member]) -> None:
        island = island_of(spec)
        if spec.fingerprint() in pool.seen:
            night.refused["a repeat"] = night.refused.get("a repeat", 0) + 1
            return
        if parents and taken.rule(spec) is not None:
            why = "a tried idea with other numbers"
            night.refused[why] = night.refused.get(why, 0) + 1
            return
        taken.add(novelty.rule_key(spec), "tonight")
        found = evaluate(spec, island, [p.id for p in parents])
        root = parents[0].root if parents else str(found["id"])
        base = {"at": stamp, "island": island, "fingerprint": spec.fingerprint(), "root": root}
        add_row(path, KIND, {**base, "event": "try", "id": found["id"]})
        pool.seen.add(spec.fingerprint())
        pool.tried[island] = pool.tried.get(island, 0) + 1
        pool.children[root] = pool.children.get(root, 0) + 1
        night.tried += 1
        fitness, why = judge(spec, found, pool, peers)
        if fitness is None:
            reason = why.split(" (")[0]
            night.refused[reason] = night.refused.get(reason, 0) + 1
            return
        member = Member(
            id=str(found["id"]),
            spec=spec,
            island=island,
            fitness=round(fitness, 4),
            sharpe=float(found["net"]["sharpe"]),
            root=root,
            generation=1 + max((p.generation for p in parents), default=-1),
            parents=tuple(p.id for p in parents),
        )
        add_row(
            path,
            KIND,
            {
                **base,
                "event": "admit",
                "id": member.id,
                "spec": spec.model_dump(mode="json"),
                "fitness": member.fitness,
                "sharpe": member.sharpe,
                "generation": member.generation,
                "parents": list(member.parents),
            },
        )
        pool.members[member.id] = member
        pool.admitted[island] = pool.admitted.get(island, 0) + 1
        pool.returns[member.id] = dict(found.get("daily") or {})
        night.admitted.append(member)
        mine = pool.of(island)
        if len(mine) > POOL:
            safe = {m.id for m in pool.elite(island)}
            weakest = next(m for m in reversed(mine) if m.id not in safe)
            add_row(path, KIND, {**base, "event": "drop", "id": weakest.id})
            pool.members.pop(weakest.id)
            pool.returns.pop(weakest.id, None)

    for island in allot(budget, pool, rng, forward or {}):
        if night.tried >= budget:
            break
        members = pool.of(island)
        if not members:
            fresh = [
                s for s in seeds if island_of(s) == island and s.fingerprint() not in pool.seen
            ]
            if fresh:
                consider(rng.choice(fresh), [])
            continue
        parent = choose_parent(members, pool.children, rng)
        if ask is not None and rng.random() < MODEL_SHARE and not waiting.get(parent.id):
            line = [m for m in members if m.root == parent.root]
            try:
                waiting[parent.id] = proposals(ask(SYSTEM, prompt(parent, line, 4)))
            except Exception:
                ask = None  # the model cannot answer tonight: code breeds the rest
        if waiting.get(parent.id):
            night.from_model += 1
            consider(waiting[parent.id].pop(0), [parent])
            continue
        other = rng.choice(members) if len(members) > 1 else None
        for _ in range(5):
            child = mutate(parent.spec, rng, other.spec if other else None)
            if (
                child is not None
                and child.fingerprint() not in pool.seen
                and taken.rule(child) is None
            ):
                used_other = (
                    other is not None and child.score == other.spec.score != parent.spec.score
                )
                consider(child, [parent, other] if used_other and other else [parent])
                break
    return night


# --- survivors become cards --------------------------------------------------------------


def survivors(night: Night, holds: Callable[[Member], bool | None]) -> list[Member]:
    """The best rule admitted tonight in each island that did not fail the selection period."""
    out: list[Member] = []
    for island in ISLANDS:
        mine = sorted((m for m in night.admitted if m.island == island), key=lambda m: -m.fitness)
        out += [m for m in mine if holds(m) is not False][:PER_ISLAND]
    return out


def card_yaml(hypothesis: str, member: Member, *, day: date, tried: int) -> str:
    spec = member.spec
    body = {
        "id": hypothesis,
        "title": f"Evolved rule: {spec.describe()[:90]}",
        "status": "draft",
        "family": "evolved_rules",
        "source_kind": "agent",
        "parent": "",
        "claim": f"{spec.describe()} earns more than costs in both halves and at 2x costs.",
        "rationale": f"Bred by the evolutionary search (ADR-177), generation {member.generation} "
        f"of lineage {member.root}, island {member.island}. No paper behind it.",
        "source": {
            "research": "evolve",
            "claim": f"agent:{hypothesis}",
            "experiment": member.id,
            "day": day.isoformat(),
        },
        "engine_v2": spec.model_dump(mode="json", exclude_defaults=True),
        "red_flags": [
            f"Chosen from {tried} candidates tried by the search; the simple gate does not "
            "correct for that. The firewall figures in the experiment store do.",
            "Written after it was screened: the search itself is the record of what was tried.",
            "Daily bars: the official open and close stand in for real fills.",
        ],
        "holdout": {
            "starts": constitution.load().periods.forward_start.isoformat(),
            "status": "unread",
        },
        "result": f"Screen net Sharpe {member.sharpe:+.2f}; fitness {member.fitness:+.2f}.",
    }
    return yaml.safe_dump(body, sort_keys=False, allow_unicode=True, width=100)


# --- the nightly job ---------------------------------------------------------------------


def seed_specs() -> list[lang.Spec]:
    """Where an empty island starts: research 176's rules and the fixed-rule grid, as v2 specs."""
    from eulerlab.agents.workers import autopilot as writer
    from eulerlab.intraday import rule_engine

    rules = [*rule_engine.reference_specs().values()]
    rules += [card["spec"] for card in writer.fallback(60, 0, {})]
    return [lang.Spec.model_validate(lang.from_rule(r).model_dump(mode="json")) for r in rules]


def pipeline(ctx: Any, *, data: Any = None, run_git: Any = None) -> Any:
    """`make agents-evolve`: one night of search, then cards for the survivors.

    Runs as the autopilot agent, so its survivors join the autopilot's gate
    queue and its model requests count against that agent's day and the
    month's budget. It never gates: `research/autopilot.py` does, within the
    week's allowance.
    """
    from eulerlab.agents.runtime import Item, WorkerResult
    from eulerlab.agents.workers import autopilot as writer
    from eulerlab.intraday import rule_engine
    from eulerlab.research import autopilot, experiments, fast_eval

    rules = constitution.load()
    constitution.require("register_hypothesis", who="the evolutionary search")
    engine = fast_eval.FastEngine(data or rule_engine.Data())
    if engine.data.end > rules.periods.backtest_end:
        msg = f"the search's data ends {engine.data.end}, inside the forward test"
        raise experiments.SealedPeriod(msg)
    by_id = {str(r["id"]): r for r in experiments.rows()}

    def evaluate(spec: lang.Spec, island: str, parents: Sequence[str]) -> dict[str, Any]:
        (found,) = fast_eval.evaluate(
            [spec],
            engine,
            asked_by="evolve",
            family=island,
            parents={spec.fingerprint(): parents},
            now=ctx.now,
        )
        return found

    def ask(system: str, user: str) -> str:
        return str(ctx.ask(system, user))

    day = ctx.now.date()
    budget = int(ctx.options.get("evolve_candidates", 200))
    ctx.step(f"Searching: up to {budget} candidate rules across {len(ISLANDS)} islands")
    night = run(
        budget=budget,
        seeds=seed_specs(),
        evaluate=evaluate,
        peers=autopilot.peers(engine, ctx.root),
        day=day,
        ask=ask if ctx.can_ask() else None,
        returns=lambda i: experiments.returns_of(by_id[i]) if i in by_id else {},
        now=ctx.now,
        ideas=novelty.seen(),
    )
    pool = load()
    after = {str(r["id"]): r for r in experiments.rows()}

    def held(member: Member) -> bool | None:
        daily = experiments.returns_of(after[member.id]) if member.id in after else {}
        return firewall.holds(daily, member.spec.fingerprint())[2]

    chosen = survivors(night, held)
    ids = writer.next_ids(len(chosen)) if chosen else []
    paths: list[str] = []
    for hypothesis, member in zip(ids, chosen, strict=True):
        card = autopilot.HYPOTHESES / f"{hypothesis}.yaml"
        card.write_text(
            card_yaml(hypothesis, member, day=day, tried=sum(pool.tried.values())), encoding="utf-8"
        )
        paths.append(str(card))
    if paths:
        ok, out = autopilot.commit(
            paths,
            f"docs(research): {ids[0]} to {ids[-1]}, evolved rules {day} (ADR-177)",
            run_git or autopilot.git,
        )
        if not ok:
            ctx.notes.append(f"cards written but not committed: {out[:200]}")
    refused = "; ".join(f"{n} {why}" for why, n in sorted(night.refused.items())) or "none"
    summary = (
        f"{night.tried} candidate(s) tried ({night.from_model} from the model), "
        f"{len(night.admitted)} admitted to the pool, {len(ids)} card(s) written for the gate"
    )
    body = (
        f"{summary}.\nRefused: {refused}.\nIslands closed as saturated: {night.closed or 'none'}."
    )
    return WorkerResult(
        summary,
        items=[Item(kind="finding", title=f"Evolution: {summary}"[:200], body=body)],
        data={
            "survivors": ids,
            "tried": night.tried,
            "admitted": [m.id for m in night.admitted],
            "refused": night.refused,
            "closed": night.closed,
        },
    )


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    from eulerlab.agents import runtime
    from eulerlab.research import autopilot

    argparse.ArgumentParser(prog="agents-evolve", description=__doc__).parse_args(argv)
    output = runtime.run(autopilot.NAME, worker=pipeline)
    print(f"{output.status}: {output.summary}")
    return 0 if output.status in ("ok", "skipped") else 1


if __name__ == "__main__":
    raise SystemExit(main())
