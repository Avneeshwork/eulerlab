"""Turning a hypothesis card into runnable strategies.

**It composes vetted primitives. It does not write Python.**

That is the whole design and it is a deliberate refusal. The obvious reading of
"codegen" in a research loop is an agent emitting strategy source that then
gets executed, and there are three reasons not to do that here:

1. **Executing generated code discards every guarantee below it.** Sprint 4's
   lookahead firewall works because a `Strategy` receives a `MarketView` and
   can physically see nothing else. Arbitrary code can open the panel file
   directly. The firewall is structural precisely so that nothing has to
   remember to respect it, and `exec` of generated source is the one thing
   that breaks that property.
2. **Every primitive here is already tested.** The feature library has 45
   tests behind it; a generated `momentum_14_2` would have none, and its bugs
   would be indistinguishable from findings.
3. **A composition is reviewable and diffable.** `{feature: low_volatility,
   top_n: 30}` can be read in a card, checked by the critic, and compared
   against a previous submission. A block of generated Python cannot be
   meaningfully diffed against another block of generated Python.

The cost is real and worth stating: **this cannot express a genuinely novel
strategy shape.** Anything outside "rank the cross-section by a known feature
and hold the top N" needs a new primitive, written and tested by hand, before
a card can reference it. That is a deliberate brake on the loop's throughput,
and given what Sprint 15 measured about the cost of searching, throughput is
not the constraint worth relaxing.

Since ADR-097 a card's `feature:` may also be `formula:<expression>` in the
formula language (`features/formula.py`). That is still composition, not code:
the expression is parsed into a tree of tested, past-only operators and
interpreted. It widens what a feature can be; it does not widen the shapes.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from eulerlab.backtest.strategies import BuyAndHold, RankAndHold
from eulerlab.backtest.strategy import Strategy
from eulerlab.features.formula import is_known, resolve
from eulerlab.features.library import BY_NAME


class UnknownPrimitive(ValueError):
    """A card referenced something the library does not provide.

    Raised rather than skipped. A card that silently produced fewer strategies
    than it declared would be evaluated on a different set of configurations
    from the one it pre-registered, which defeats pre-registration.
    """


@dataclass(frozen=True)
class Built:
    """One realised configuration from a card."""

    label: str
    strategy: Strategy
    rebalance: int


SHAPES = {
    "rank_and_hold": "rank the cross-section by a feature, hold the top N equal-weighted",
    "buy_and_hold": "hold the N most liquid names, never rebalance",
}


def _one(config: dict[str, Any]) -> Built:
    shape = str(config.get("shape", "rank_and_hold"))
    if shape not in SHAPES:
        msg = f"unknown shape {shape!r}; the library provides {sorted(SHAPES)}"
        raise UnknownPrimitive(msg)

    rebalance = int(str(config.get("rebalance", 21)))
    top_n = int(str(config.get("top_n", 30)))

    if shape == "buy_and_hold":
        return Built(f"buy_and_hold|top{top_n}", BuyAndHold(top_n=top_n), rebalance)

    name = str(config.get("feature", ""))
    if not is_known(name):
        msg = (
            f"unknown feature {name!r}. The library provides {sorted(BY_NAME)}, or write "
            f"`formula:<expression>` in the formula language (features/formula.py, ADR-097). "
            f"Generated Python is never accepted — it would have no tests behind it."
        )
        raise UnknownPrimitive(msg)

    min_turnover = float(config.get("min_turnover", 0.0) or 0.0)
    strategy = RankAndHold(resolve(name), top_n=top_n, min_turnover=min_turnover)
    label = f"{name}|top{top_n}|rb{rebalance}"
    if min_turnover:
        label += f"|liq{min_turnover:.0f}"
    return Built(label, strategy, rebalance)


def build_one(config: dict[str, Any]) -> Built:
    """One configuration, as the lab and validation both build it (formula features, liquidity floor)."""
    return _one(config)


def build_from_card(path: Path) -> list[Built]:
    """Realise every configuration a card declares.

    All of them, in the declared order, with no filtering. The card fixed this
    list in advance and PBO is computed across exactly it — quietly dropping
    one because it looks unpromising is the selection effect the whole
    apparatus exists to measure.
    """
    spec = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    configs = spec.get("configurations") or []
    if not configs:
        msg = f"{path} declares no configurations"
        raise UnknownPrimitive(msg)
    return [_one(c) for c in configs]


def describe_library() -> str:
    """What a card may reference. Printed so a card author is not guessing."""
    lines = ["shapes:"]
    lines.extend(f"  {name:<16} {text}" for name, text in sorted(SHAPES.items()))
    lines.append("\nfeatures:")
    lines.extend(f"  {f.name:<22} {f.description}" for f in BY_NAME.values())
    lines.append(
        "\nAnything else needs a new primitive, written and tested by hand. This is\n"
        "a brake on throughput and it is intentional: Sprint 15 measured that\n"
        "generating more hypotheses raises the bar for all of them."
    )
    return "\n".join(lines)
