"""Is this idea new, or a re-tuned copy of one already tried? (ADR-209)

A rule's fingerprint changes when any number in it changes, so the old repeat
check let through a gap fade at 2.5% after one at 3%, or a 126-day momentum
after a 63-day one. Each of those burns a trial in the multiple-testing budget
(1,342 by 2026-11-16) without testing anything new. Here every rule gets an
**idea key** that leaves the numbers out:

    dropped    thresholds and constants, windows, lags (`delay`), the hold,
               top N and the rebalance, and for an event rule what it ranks by
    kept       the kind (intraday or swing), the shape (event or cross-section),
               the side (long, short, against or with what), every field and
               operator, and the direction of each comparison (>= and > are one,
               <= and < another)

Two rules with one key are one idea. Commutative operators (`and`, `or`,
`add`, `mul`) sort their arguments, so the order a condition is written in does
not make a new idea. A sign is part of the idea: `neg(ret(21))` (reversal) and
`ret(126)` (momentum) are two ideas, and so are long and short. The one
exception is the idea lab's exact reverse: ranking by `neg(x)` after `x` reads
the same IC with its sign changed, so it is a repeat.

`Seen` holds the key of everything already tried: every card in `hypotheses/`,
research 176's reference rules, every screen or sweep in the experiment store
that kept its spec, and the idea lab's memory. The autopilot, the research
loop's screen tool, the idea lab and the evolutionary search ask it before they
spend a trial.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from eulerlab.features import formula
from eulerlab.features.formula import Node
from eulerlab.intraday import rule_engine as engine
from eulerlab.research import lang

HYPOTHESES = Path("hypotheses")

_COMMUTATIVE = frozenset({"and", "or", "add", "mul"})
_DIRECTION = {"gt": "ge", "ge": "ge", "lt": "le", "le": "le"}
_MIRROR = {"ge": "le", "le": "ge"}
_ORDER_ONLY = frozenset({"rank", "zscore"})
"""Cross-section wrappers that keep a score's order: `rank(x)` picks the same stocks as `x`."""


def shape(node: Node) -> str:
    """A tree's text with every number left out: `ge(abs(gap), #)`, `ret(#)`."""
    if node.op == "const":
        return "#"
    if node.op == "delay" and node.args:  # a lag is a parameter of the idea, not a new one
        return shape(node.args[0])
    op = node.op
    args = list(node.args)
    if op in _DIRECTION and len(args) == 2:
        op = _DIRECTION[op]
        if args[0].op == "const" and args[1].op != "const":  # ge(0.03, x) is le(x, 0.03)
            op, args = _MIRROR[op], [args[1], args[0]]
    if op in _COMMUTATIVE:
        parts = sorted(set(_flatten(op, node)))
        return f"{op}({', '.join(parts)})"
    if not args:
        return op if not node.params else f"{op}(#)"
    inner = [shape(a) for a in args] + ["#" for _ in node.params]
    return f"{op}({', '.join(inner)})"


def _flatten(op: str, node: Node) -> list[str]:
    """The arguments of a chain of one commutative operator: and(a, and(b, c)) -> a, b, c."""
    out: list[str] = []
    for a in node.args:
        out.extend(_flatten(op, a) if a.op == op else [shape(a)])
    return out


def _score(node: Node) -> str:
    while node.op in _ORDER_ONLY and node.args:
        node = node.args[0]
    return shape(node)


def rule_key(rule: engine.Rule) -> str:
    """The idea key of an engine rule (`engine:` or `engine_v2:`)."""
    if isinstance(rule, engine.RuleSpec):
        rule = lang.from_rule(rule)
    if not isinstance(rule, lang.Spec):
        return f"exact:{rule.fingerprint()}"
    trees = rule.trees
    side: str = rule.side
    if "side_by" in trees:
        side = f"{side} {shape(trees['side_by'])}"
    parts = [rule.kind, rule.shape, side, f"when {shape(trees['when'])}"]
    if rule.shape == "cross_section":  # the score is the whole idea; an event rule's only orders
        parts.append(f"best {_score(trees['score'])}")
    return "rule:" + "; ".join(parts)


def _formula(feature: str) -> Node:
    text = feature.removeprefix(formula.PREFIX)
    for entry in formula.ZOO:
        if entry.name == feature:
            text = entry.text
    return formula.parse(text)


def formula_key(feature: str) -> str:
    """The idea key of an idea-lab ranking formula (`formula:...` or a library feature name)."""
    try:
        return "rank:" + shape(_formula(feature))
    except formula.FormulaError:
        return "rank:?" + feature


def _exact_keys(feature: str) -> list[str]:
    """A formula and its exact reverse: ranking by `neg(x)` is the IC test of `x` read upside down."""
    try:
        node = _formula(feature)
    except formula.FormulaError:
        return []
    flipped = node.args[0] if node.op == "neg" else Node(op="neg", args=(node,))
    return ["exact:" + formula.text_of(node), "exact:" + formula.text_of(flipped)]


@dataclass
class Seen:
    """Every idea key already tried, with where it was first seen."""

    keys: dict[str, str] = field(default_factory=dict)

    def add(self, key: str, where: str) -> None:
        self.keys.setdefault(key, where)

    def rule(self, rule: engine.Rule) -> str | None:
        """Where an idea with this rule's key was tried, or None when it is new."""
        return self.keys.get(rule_key(rule))

    def feature(self, feature: str) -> str | None:
        """Where this formula's idea, or its exact reverse, was tried; None when it is new."""
        for key in (formula_key(feature), *_exact_keys(feature)[:1]):
            if key in self.keys:
                return self.keys[key]
        return None

    def add_feature(self, feature: str, where: str) -> None:
        self.add(formula_key(feature), where)
        for key in _exact_keys(feature):
            self.add(key, where)

    def copy(self) -> Seen:
        return Seen(dict(self.keys))

    def __len__(self) -> int:
        return len(self.keys)


def _spec_from(raw: Mapping[str, Any]) -> engine.Rule | None:
    for model in (engine.RuleSpec, lang.Spec):
        try:
            return model.model_validate(raw)
        except (ValidationError, ValueError):
            continue
    return None


def seen(
    root: Path = HYPOTHESES,
    *,
    screens: Iterable[Mapping[str, Any]] | None = None,
    features: Iterable[str] = (),
) -> Seen:
    """The keys of every card in `root`, the reference rules, `screens` and `features`.

    `screens` defaults to the experiment store's screen and sweep rows (the
    evolutionary search's candidates are sweeps); pass `()` to skip it.
    `features` are formulas the idea lab has tested (its memory)."""
    out = Seen()
    for h, ref in engine.reference_specs().items():
        out.add(rule_key(ref), h)
    for path in sorted(root.glob("H-*.yaml")):
        try:
            spec = engine.card_spec(path.stem, root)
        except ValueError:  # a card whose block no longer parses is still a card
            spec = None
        if spec is not None:
            out.add(rule_key(spec), path.stem)
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            continue
        for config in raw.get("configurations") or []:
            if isinstance(config, dict) and isinstance(config.get("feature"), str):
                out.add_feature(config["feature"], path.stem)
    if screens is None:
        from eulerlab.research import experiments

        screens = [*experiments.rows(purpose="screen"), *experiments.rows(purpose="sweep")]
    for row in screens:
        raw_spec = row.get("spec")
        rule = _spec_from(raw_spec) if isinstance(raw_spec, Mapping) else None
        if rule is not None:
            out.add(rule_key(rule), str(row.get("hypothesis") or f"screen {row.get('id', '')}"))
    for f in features:
        out.add_feature(f, "the idea lab's memory")
    return out


REPEAT_RULE = (
    "A rule is a repeat, and code refuses it, when it uses the same fields in the same "
    "conditions, with the same side and kind, as a rule already tried, whatever its "
    "thresholds, windows, lags, hold or ranking. Changing a number is tuning, not a new idea. "
    "Each card must test a mechanism no earlier card tested."
)
"""The sentence every idea prompt carries, so the model knows what code will refuse."""
