"""The autopilot's card writer: new rules in the engine's language, half intraday, half swing (ADR-150).

    papers in the library + every rule already tried + what earlier screens showed
        -> the model writes about ten cards as `engine:` specs (Claude first, Groq
           if Claude cannot answer), each with a reason and red flags
        -> each spec is parsed by `intraday/rule_engine.py` (no lookahead, long-only
           swings, a window it cannot choose); a spec that fails is dropped, with why
        -> a repeat of any rule already tried is dropped: the same fingerprint, or
           the same idea with other numbers (`research/novelty.py`, ADR-209)
        -> too few left: fixed-rule specs fill the gap from the signal vocabulary
        -> written to `hypotheses/H-NNNN.yaml` as drafts, unscreened

This worker only writes cards. It never screens, validates, gates or commits:
`research/autopilot.py` (`make agents-autopilot`) commits the cards as their
pre-registration and runs the rest of the loop under the operator's approval
of 2026-11-07. Run alone (`make agent NAME=autopilot`) it stops at the cards.
"""

from __future__ import annotations

import json
import random
import re
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError

from eulerlab.agents import lessons
from eulerlab.agents.runtime import BudgetSpent, Context, Item, WorkerResult, model_asker, untrusted
from eulerlab.intraday import rule_engine as engine
from eulerlab.llm.spend import MonthBudgetSpent
from eulerlab.research import knowledge, novelty

HYPOTHESES = Path("hypotheses")
PAPERS = Path("research/papers")
FAMILY = "autopilot_event_rules"
DEFAULT_CARDS = 10
MAX_ASKS = 5
"""Requests a night at most: the first writes every card, each later one only the cards
a repeat or an invalid spec cost (operator, 2026-11-08: up to 5 a day)."""
FALLBACK_PROVIDER = "groq"
HOLDOUT_START = "2024-12-01"

SCOPE = (
    "Scope (operator, 2026-11-07): Indian cash stocks only, NSE. Trade only stocks, never "
    "options or futures; other data (F&O, OI, deals, results dates) may be signals. 1x capital, "
    "no leverage. Half intraday (official open to official close, long or short), half swing "
    "(delivery, long only, held 2 to 60 sessions)."
)

SYSTEM = (
    "You are the research autopilot of a quant platform for NSE stocks. You write new trading "
    "rules as JSON specs for a fixed rule engine. You never see results before writing; every "
    "rule is pre-registered and tested once, with no tuning afterwards. Prefer rules with an "
    "economic reason (who is forced to trade, who under-reacts, what information arrives) over "
    "chart patterns: price-only stock rules have repeatedly died on the 12 bps intraday round "
    "trip here. Each rule must be a different idea from every rule already tried, not the same "
    "rule with other numbers. Answer with JSON only."
)


def vocabulary() -> str:
    lines = [
        f"- {name}: {info.what}; min lag {info.min_lag}; data from {info.first}"
        for name, info in engine.SIGNALS.items()
    ]
    return "\n".join(lines)


SPEC_HELP = """A spec (the `engine` object):
{"kind": "intraday" | "swing",
 "hold": 0 for intraday, 2-60 sessions for swing,
 "side": "long" | "short" (intraday only) | "against" | "with",
 "direction_of": {"signal": ..., "lag": ..., "n": ...}   (only for against/with: trade against/with its sign),
 "when": [ {"signal": ..., "lag": 0-5, "n": 1-260, "absolute": false, "op": ">=" | "<=" | ">" | "<", "value": number}, ... ]  (1-5 conditions, all must hold; omit op/value for a yes/no event),
 "rank_by": {"signal": ..., "lag": ..., "n": ..., "absolute": false, "order": "desc" | "asc"}}
lag is sessions before the entry session; entry is at the entry session's official open.
A signal that uses a close needs lag >= 1. Returns are fractions (0.03 = 3%).
Example (research 176, H-0168, already tried): {"kind": "intraday", "side": "against",
 "direction_of": {"signal": "gap"}, "when": [{"signal": "results_morning"},
 {"signal": "gap", "op": ">=", "value": 0.03, "absolute": true}],
 "rank_by": {"signal": "gap", "absolute": true, "order": "desc"}}"""


def tried(root: Path = HYPOTHESES, limit: int = 60) -> str:
    """Every engine rule tried, and the latest other cards, with their result lines."""
    lines = []
    for h, spec in engine.reference_specs().items():
        lines.append(f"{h} [{spec.kind}] {spec.describe()}")
    other = []
    for path in sorted(root.glob("H-*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        result = str(raw.get("result") or "")[:160].replace("\n", " ")
        if isinstance(raw.get("engine"), dict) or isinstance(raw.get("engine_v2"), dict):
            try:
                rule = spec_of(raw)
            except ValueError:  # pydantic's ValidationError and FormulaError are both
                continue
            lines.append(f"{path.stem} [{rule.kind}] {rule.describe()} :: {result}")
        else:
            other.append(f"{path.stem} {raw.get('title', '')} :: {result}")
    return "\n".join(lines + other[-limit:])


def papers(day: date, count: int = 12, root: Path = PAPERS) -> str:
    """A different dozen papers with a trade idea each day, seeded by the day."""
    found = []
    for path in sorted(root.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        idea = str(raw.get("trade_idea") or "").strip()
        if idea:
            found.append(f"[{raw.get('id', path.stem)}] {raw.get('title', '')}: {idea[:300]}")
    random.Random(day.toordinal()).shuffle(found)
    return "\n".join(found[:count])


def prompt(day: date, count: int, *, intraday: int | None = None, retry: str = "") -> str:
    half = count // 2 if intraday is None else intraday
    again = (
        f"\n\nYour last answer left these out (fix the cause, do not resend them):\n{retry}"
        if retry
        else ""
    )
    return (
        f"{SCOPE}\n\nSignals you may use:\n{vocabulary()}\n\n{SPEC_HELP}\n\n"
        f"Rules already tried (do not repeat them or vary their numbers):\n"
        f"{untrusted('tried', tried())}\n\n{novelty.REPEAT_RULE}\n\n"
        f"Papers in the library:\n{untrusted('papers', papers(day))}\n\n"
        f"Write {count} new rules: {half} intraday and {count - half} swing. Answer with "
        '{"cards": [{"title": "<under 90 characters>", "claim": "<one sentence a test can '
        'falsify>", "rationale": "<why it should earn money, naming the paper id or earlier '
        'card it builds on>", "paper": "<paper id or empty>", "replicates": <true only when '
        'the rule is the paper\'s own form, untouched>, "engine": {...}, '
        '"red_flags": ["<specific ways it could be fake>"]}]}' + again
    )


def parse(answer: str) -> list[dict[str, Any]]:
    """The cards in a model answer; anything that is not a JSON object list gives []."""
    text = answer.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    start = text.find("{")
    if start < 0:
        return []
    try:
        body = json.loads(text[start : text.rfind("}") + 1])
    except ValueError:
        return []
    cards = body.get("cards") if isinstance(body, dict) else None
    return [c for c in cards if isinstance(c, dict)] if isinstance(cards, list) else []


def spec_of(card: dict[str, Any]) -> engine.Rule:
    """A card's rule: its `engine_v2:` block (agent features expanded, ADR-191) or `engine:`."""
    if isinstance(card.get("engine_v2"), dict):
        from eulerlab.research import agent_tools

        return agent_tools.parse_formula_spec(card["engine_v2"])
    return engine.RuleSpec.model_validate(card.get("engine"))


def accept(
    raw: list[dict[str, Any]],
    known: dict[str, str],
    ideas: novelty.Seen | None = None,
    *,
    lessons_root: Path | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """(cards whose spec parses and is a new idea, why each other was dropped).

    `ideas` holds the idea keys already tried; a card whose key is in it, or
    that shares one with an earlier card of this answer, is dropped (ADR-209).
    `lessons_root` is the lesson store read (the agents' own by default); the
    generator eval passes a fixed one so it scores the same everywhere (#157)."""
    kept: list[dict[str, Any]] = []
    dropped: list[str] = []
    seen = dict(known)
    taken = ideas.copy() if ideas is not None else novelty.Seen()
    for card in raw:
        title = str(card.get("title") or "untitled")[:120]
        try:
            spec = spec_of(card)
        except ValidationError as exc:
            dropped.append(f"{title}: {exc.errors()[0].get('msg', 'invalid spec')}")
            continue
        except ValueError as exc:  # a formula that does not compile or reads ahead
            dropped.append(f"{title}: {str(exc)[:200]}")
            continue
        broken = lessons.violations(spec, root=lessons_root)
        if broken:
            dropped.append(f"{title}: breaks a lesson: {broken[0]}")
            continue
        fp = spec.fingerprint()
        if fp in seen:
            dropped.append(f"{title}: repeats {seen[fp]}")
            continue
        twin = taken.rule(spec)
        if twin is not None:
            dropped.append(
                f"{title}: the same idea as {twin} with other numbers (a variant, not a new rule)"
            )
            continue
        seen[fp] = title
        taken.add(novelty.rule_key(spec), title)
        kept.append({**card, "title": title, "spec": spec})
    return kept, dropped


GRID: tuple[tuple[str, dict[str, Any]], ...] = (
    ("gap", {"op": ">=", "value": 0.02, "absolute": True}),
    ("ret", {"lag": 1, "n": 5, "op": "<=", "value": -0.08}),
    ("ret", {"lag": 1, "n": 5, "op": ">=", "value": 0.08}),
    ("value_ratio", {"lag": 1, "op": ">=", "value": 3.0}),
    ("delivery_ratio", {"lag": 1, "op": ">=", "value": 1.5}),
    ("at_high", {"lag": 1, "n": 60}),
    ("at_low", {"lag": 1, "n": 60}),
    ("promoter_buy", {"op": ">", "value": 0.0}),
    ("results_morning", {}),
    ("day_return", {"lag": 1, "op": "<=", "value": -0.04}),
)
"""Fixed-rule building blocks for when the model cannot answer."""

EXPLORE_SYSTEM = (
    "You are the research autopilot of a quant platform for NSE stocks. You research before "
    "you write, with tools that read 2016 to 2023 only. Work like a researcher: open the "
    "`agenda` and pick an open question, or ask a new one with an economic reason (who is "
    "forced to trade, who under-reacts, what information arrives). Read `language` for the "
    "fields and operators. If a signal you need is missing, define it with `define_feature`; "
    "code checks it for look-ahead and refuses copies of what exists. Measure before you build: "
    "`feature_ic` for a score, `event_study` for an event, then `screen_formula` or "
    "`screen_rule` a few drafts and read the figures (net bps against the 12 bps intraday "
    "round trip, both halves, 2x costs, years positive, flags). Change your idea when they say "
    "it is weak. The screen tool refuses an idea already tried with other numbers, and a "
    "second screen of one idea in a run, because changing a number is tuning. Signals too "
    "weak to pay costs alone can be tested together with `combine_signals`. Every look and "
    "screen is recorded and raises the bar every rule must clear, so test only what is worth it and never tune a number to fit. Before you answer, write "
    "what you learned with `record_finding`, so the next night starts there. Rules you write "
    "are then tested on the whole window with no further changes. Price-only stock rules have "
    "repeatedly died here. When you are done, answer with the JSON the user message asks for, "
    "and nothing else."
)
"""The system prompt of the research loop (#162 ADR-190, #163 and #164 ADR-191)."""

EXPLORE_ROUNDS = 12
EXPLORE_SCREENS = 8
EXPLORE_LOOKS = 16

EXPLORE_ASK = (
    "\n\nBefore you answer, use the tools. A card may carry either an `engine` spec (see "
    "`signals`) or an `engine_v2` spec (see `language`; features agents defined may be used by "
    "name), never both. Name in each card's rationale the agenda question and the looks or "
    "screens that informed it. A card may be a rule you screened or a new one."
)


def fallback(
    count: int, seed: int, known: dict[str, str], ideas: novelty.Seen | None = None
) -> list[dict[str, Any]]:
    """Pairs of grid conditions, half intraday and half swing, new ideas only.

    Fewer than `count` come back once the grid's ideas are used up: a variant
    of a tried rule is not written to make up the number (ADR-209)."""
    rng = random.Random(seed)
    taken = ideas.copy() if ideas is not None else novelty.Seen()
    out: list[dict[str, Any]] = []
    tries = 0
    while len(out) < count and tries < 500:
        tries += 1
        (a, ca), (b, cb) = rng.sample(GRID, 2)
        swing = len(out) % 2 == 1
        when = [{"signal": a, **ca}, {"signal": b, **cb}]
        rank = next(
            (
                {"signal": s, **{k: v for k, v in c.items() if k in ("lag", "n", "absolute")}}
                for s, c in ((a, ca), (b, cb))
                if not engine.SIGNALS[s].boolean
            ),
            None,
        )
        if rank is None:
            continue
        body = {
            "kind": "swing" if swing else "intraday",
            "hold": rng.choice((5, 10, 20)) if swing else 0,
            "side": "long" if swing else rng.choice(("long", "short")),
            "when": when,
            "rank_by": {**rank, "order": "desc"},
        }
        try:
            spec = engine.RuleSpec.model_validate(body)
        except ValidationError:
            continue
        if spec.fingerprint() in known or taken.rule(spec) is not None:
            continue
        known = {**known, spec.fingerprint(): "fallback"}
        taken.add(novelty.rule_key(spec), "fallback")
        out.append(
            {
                "title": f"Fixed-rule combination: {spec.describe()[:80]}",
                "claim": f"{spec.describe()} earns more than costs in both halves and at 2x costs.",
                "rationale": "Written by fixed rules from the signal vocabulary, because the model "
                "could not answer. No paper behind it.",
                "paper": "",
                "red_flags": ["No economic reason was written before the test."],
                "spec": spec,
            }
        )
    return out


def next_ids(count: int, root: Path = HYPOTHESES) -> list[str]:
    numbers = [int(p.stem[2:]) for p in root.glob("H-*.yaml") if p.stem[2:].isdigit()]
    start = max(numbers, default=0) + 1
    return [f"H-{n:04d}" for n in range(start, start + count)]


def _dump(spec: engine.Rule) -> dict[str, Any]:
    assert isinstance(spec, BaseModel)  # both rule types are pydantic models
    return spec.model_dump(mode="json", exclude_defaults=True)


def card_yaml(h: str, card: dict[str, Any], *, day: date, model: str, tried_count: int) -> str:
    spec: engine.Rule = card["spec"]
    v2 = not isinstance(spec, engine.RuleSpec)
    flags = [str(f) for f in card.get("red_flags") or [] if str(f).strip()][:6]
    body = {
        "id": h,
        "title": card["title"],
        "status": "draft",
        "family": FAMILY,
        "source_kind": "paper" if card.get("paper") else "agent",
        "parent": "",
        "claim": str(card.get("claim") or spec.describe())[:400],
        "rationale": str(card.get("rationale") or "")[:800],
        "source": {
            "research": "autopilot",
            "paper": str(card.get("paper") or ""),
            "claim": knowledge.card_claim({"id": h, "source": {"paper": card.get("paper")}}),
            "replicates": bool(card.get("paper")) and card.get("replicates") is True,
            "written_by": f"the research autopilot ({model or 'fixed rules'}), ADR-150",
            "day": day.isoformat(),
        },
        "configurations": [
            {
                "shape": "engine_rule",
                "rule": spec.describe(),
                "universe": "the 500 most traded NSE stocks by 20-session traded value each day; "
                "stocks in series BE/BZ the previous session skipped (research 173, 174)",
                "costs": "cash intraday charges plus 2 bps a side, Rs 1 lakh a position, at most "
                "ten a day, official open to close"
                if spec.kind == "intraday"
                else "delivery charges plus 2 bps a side, Rs 1 lakh a position, at most ten open",
                "window": f"{spec.first.isoformat()} to {engine.END.isoformat()}",
            }
        ],
        ("engine_v2" if v2 else "engine"): _dump(spec),
        "red_flags": [
            *flags,
            "Daily bars: the official open and close stand in for real fills.",
            f"Written by the autopilot after {tried_count} cards were tried; the simple gate "
            "does not correct for that search.",
            "Screen as research 176: gated only if net positive in both halves, at twice the "
            "costs, and clean on the engine's bias checks.",
        ],
        "holdout": {"starts": HOLDOUT_START, "status": "unread"},
        "result": "",
    }
    explored = card.get("exploration")
    if explored:
        screens = explored.get("screens") or []
        own = next((x for x in screens if x.get("fingerprint") == spec.fingerprint()), None)
        looks = explored.get("looks") or []
        body["exploration"] = {
            "screens": len(screens),
            "looks": len(looks),
            "this_rule_screened": own is not None,
            "discovery_figures": own or {},
            "features_kept": list(explored.get("features") or []),
            "questions": list(explored.get("questions") or []),
            "traces": list(explored.get("traces") or []),
        }
        body["red_flags"].insert(
            len(flags),
            f"Written after {len(screens)} exploratory screen(s) and {len(looks)} look(s) (IC "
            "or event study) on 2016-2023 in the research loop (ADR-190, ADR-191); each is in "
            "the experiment store, and the screens count in the firewall's bar.",
        )
    return yaml.safe_dump(body, sort_keys=False, allow_unicode=True, width=100)


def explore(
    ctx: Context, count: int, day: date, ideas: novelty.Seen | None = None
) -> tuple[str, dict[str, Any]]:
    """The research loop: the model looks things up and screens drafts, then writes cards.

    Returns (answer, record): the record holds the screens it took and the traces
    of its requests, for the cards' `exploration` block. Raises what `converse`
    raises; `write_cards` falls back to the one-shot path."""
    from eulerlab import constitution
    from eulerlab.research import agent_tools

    tools = agent_tools.ResearchTools(
        asked_by=ctx.name,
        discovery_end=constitution.load().periods.discovery_end,
        now=ctx.now,
        max_screens=int(ctx.options.get("explore_screens", EXPLORE_SCREENS)),
        max_looks=int(ctx.options.get("explore_looks", EXPLORE_LOOKS)),
        engine=agent_tools.discovery_engine,
        ideas=ideas,
    )
    user = prompt(day, count) + EXPLORE_ASK
    answer = ctx.converse(
        EXPLORE_SYSTEM,
        user,
        tools,
        rounds=int(ctx.options.get("explore_rounds", EXPLORE_ROUNDS)),
    )
    return answer, {
        "screens": list(tools.screened),
        "looks": list(tools.looks),
        "features": [f["name"] for f in tools.features if f["kept"]],
        "questions": sorted(tools.questions),
        "traces": list(ctx.last_traces),
        "tool_calls": dict(tools.calls),
    }


def _ask(ctx: Context, user: str) -> tuple[str, str]:
    """(answer, provider): the agent's own provider first, then Groq."""
    try:
        return ctx.ask(SYSTEM, user), ctx.model
    except MonthBudgetSpent as exc:  # the month's rupees are gone: the free model writes
        ctx.notes.append(str(exc))
    except BudgetSpent:
        raise
    except Exception as exc:  # an outage or an empty Claude balance must not stop the night
        ctx.notes.append(f"{ctx.model or 'the model'} failed ({type(exc).__name__}); trying Groq")
    ctx.requests += 1
    return model_asker(FALLBACK_PROVIDER)(SYSTEM, user, None), FALLBACK_PROVIDER


def write_cards(ctx: Context, root: Path = HYPOTHESES) -> dict[str, Any]:
    """Write the night's cards. Returns {"cards": [{id, path, kind, rule}], "dropped": [...]}."""
    count = int(ctx.options.get("cards", DEFAULT_CARDS))
    day = ctx.now.date()
    known = engine.known_fingerprints(root)
    # Taken before the research loop screens anything, so a card may be a rule it
    # screened tonight; its other screens of that idea are refused by the tool.
    ideas = novelty.seen(root)
    model = ""
    kept: list[dict[str, Any]] = []
    dropped: list[str] = []
    asks = 0
    explored: dict[str, Any] = {}
    if ctx.options.get("explore") and ctx.can_ask():
        try:
            answer, explored = explore(ctx, count, day, ideas)
            model = ctx.model
            new, lost = accept(parse(answer), dict(known), ideas)
            dropped += lost
            for card in new:
                card["exploration"] = explored
            kept = _balance(new, count)
            asks += 1
            ctx.step(
                f"Research loop: {len(explored['screens'])} screen(s), "
                f"{len(explored['looks'])} look(s), {len(explored['features'])} feature(s) kept, "
                f"{len(new)} card(s) written, {len(kept)} of {count} kept"
            )
        except BudgetSpent as exc:
            ctx.notes.append(f"research loop skipped: {exc}")
        except Exception as exc:  # the one-shot path below still writes the night's cards
            ctx.notes.append(f"research loop failed ({type(exc).__name__}: {str(exc)[:200]})")
    while len(kept) < count and ctx.can_ask() and asks < MAX_ASKS:
        want = {"intraday": count // 2, "swing": count - count // 2}
        for c in kept:
            want[c["spec"].kind] -= 1
        missing = max(want["intraday"], 0) + max(want["swing"], 0)
        retry = "\n".join(dropped[-10:]) if asks else ""
        asks += 1
        try:
            answer, model = _ask(
                ctx, prompt(day, missing, intraday=max(want["intraday"], 0), retry=retry)
            )
        except BudgetSpent:
            ctx.notes.append("model budget spent for today")
            break
        except Exception as exc:
            ctx.notes.append(f"no model answered ({type(exc).__name__})")
            break
        raw = parse(answer)
        taken = {**known, **{c["spec"].fingerprint(): c["title"] for c in kept}}
        new, lost = accept(raw, taken, _with(ideas, kept))
        dropped += lost
        kept = _balance(kept + new, count)
        ctx.step(f"Request {asks}: the model wrote {len(raw)} card(s), {len(kept)} of {count} kept")
    if len(kept) < count:
        taken = {**known, **{c["spec"].fingerprint(): c["title"] for c in kept}}
        extra = fallback(count - len(kept), day.toordinal(), taken, _with(ideas, kept))
        if extra:
            ctx.notes.append(f"{len(extra)} card(s) written by fixed rules to make up {count}")
        kept += extra
    if len(kept) < count:
        ctx.notes.append(
            f"{len(kept)} new idea(s) tonight, not {count}: variants of tried rules are not "
            "written to make up the number (ADR-209)"
        )
    ids = next_ids(len(kept), root)
    tried_count = len(list(root.glob("H-*.yaml")))
    written = []
    for h, card in zip(ids, kept, strict=True):
        path = root / f"{h}.yaml"
        if path.exists():  # another session took the number meanwhile
            continue
        path.write_text(
            card_yaml(h, card, day=day, model=model, tried_count=tried_count), encoding="utf-8"
        )
        spec: engine.Rule = card["spec"]
        written.append(
            {
                "id": h,
                "path": str(path),
                "kind": spec.kind,
                "rule": spec.describe(),
                "title": card["title"],
                "model": model or "fixed rules",
            }
        )
    return {
        "cards": written,
        "dropped": dropped,
        "model": model,
        "explored": {k: v for k, v in explored.items() if k != "traces"} if explored else {},
    }


def _with(ideas: novelty.Seen, kept: list[dict[str, Any]]) -> novelty.Seen:
    """The ideas tried, plus tonight's kept cards."""
    out = ideas.copy()
    for c in kept:
        out.add(novelty.rule_key(c["spec"]), c["title"])
    return out


def _balance(cards: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    """At most half of `count` of each kind, model order kept."""
    half = {"intraday": count // 2, "swing": count - count // 2}
    out = []
    for card in cards:
        kind = card["spec"].kind
        if half[kind] > 0:
            half[kind] -= 1
            out.append(card)
    return out


def run(ctx: Context) -> WorkerResult:
    """Cards only; `make agents-autopilot` runs the full loop."""
    found = write_cards(ctx)
    items = [
        Item(kind="draft", title=f"{c['id']}: {c['title']}"[:200], body=c["rule"], ref=c["path"])
        for c in found["cards"]
    ]
    return WorkerResult(
        f"{len(found['cards'])} card(s) written, unscreened; {len(found['dropped'])} dropped",
        items=items,
        data=found,
    )
