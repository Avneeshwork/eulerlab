"""What a builder strategy is, as data.

The shape follows the research in `docs/RESEARCH/062-strategy-builders.md`:
QuantConnect's split of a strategy into universe, signal, sizing and risk;
Streak's rule rows ("RSI(14) crosses below 30") with a stop and a target; and
Composer's "rank and keep the top N". It is a declaration, not code, so it can
be validated field by field, shown back in plain English, stored as a small
JSON file and hashed — and so a saved strategy cannot do anything the compiler
in `compile.py` does not already do.

Long-only. A short side is a different risk model (borrow, margin, the
asymmetry of a stop on a short), and Indian cash equities cannot be held short
overnight at all.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from eulerlab.builder.indicators import BY_NAME

ID_PREFIX = "b_"
"""Every builder strategy id starts with this, so it can never collide with a
registered strategy and the batch runner can tell the two apart by name."""

Comparator = Literal["above", "below", "crosses_above", "crosses_below"]

COMPARATOR_WORDS: dict[str, str] = {
    "above": "is above",
    "below": "is below",
    "crosses_above": "crosses above",
    "crosses_below": "crosses below",
}


class Operand(BaseModel):
    """An indicator on the instrument, or a fixed number."""

    kind: Literal["indicator", "value"] = "indicator"
    name: str = "close"
    params: dict[str, float] = Field(default_factory=dict)
    multiplier: float = Field(default=1.0, gt=0, le=10)
    """Scales an indicator, for rules like "close above 1.02 x SMA(50)"."""

    value: float = 0.0

    @model_validator(mode="after")
    def _known(self) -> Operand:
        if self.kind == "value":
            return self
        definition = BY_NAME.get(self.name)
        if definition is None:
            known = ", ".join(sorted(BY_NAME))
            msg = f"unknown indicator {self.name!r}. Known: {known}"
            raise ValueError(msg)
        filled: dict[str, float] = {}
        for param in definition.params:
            raw = self.params.get(param.name, param.default)
            if not param.minimum <= raw <= param.maximum:
                msg = (
                    f"{definition.label} {param.label.lower()} must be between "
                    f"{param.minimum:g} and {param.maximum:g}, not {raw:g}"
                )
                raise ValueError(msg)
            filled[param.name] = float(int(raw)) if param.integer else float(raw)
        extra = set(self.params) - {p.name for p in definition.params}
        if extra:
            msg = f"{definition.label} has no parameter {min(extra)!r}"
            raise ValueError(msg)
        self.params = filled
        return self

    def key(self) -> str:
        """Identity of the running series, shared between rules that use it."""
        if self.kind == "value":
            return f"value:{self.value}"
        args = ",".join(f"{k}={v:g}" for k, v in sorted(self.params.items()))
        return f"{self.name}({args})"

    def warmup(self) -> int:
        if self.kind == "value":
            return 0
        return BY_NAME[self.name].warmup(self.params)

    def describe(self) -> str:
        if self.kind == "value":
            return f"{self.value:g}"
        definition = BY_NAME[self.name]
        args = ", ".join(f"{v:g}" for v in self.params.values())
        text = f"{definition.label}({args})" if args else definition.label
        return f"{self.multiplier:g}x {text}" if self.multiplier != 1.0 else text


class Rule(BaseModel):
    left: Operand
    op: Comparator
    right: Operand

    @model_validator(mode="after")
    def _sensible(self) -> Rule:
        if self.left.kind == "value":
            msg = "the left side of a rule must be an indicator, not a number"
            raise ValueError(msg)
        if self.left.key() == self.right.key() and self.left.multiplier == self.right.multiplier:
            msg = f"{self.left.describe()} is compared with itself, so this rule never changes"
            raise ValueError(msg)
        return self

    def describe(self) -> str:
        return f"{self.left.describe()} {COMPARATOR_WORDS[self.op]} {self.right.describe()}"


class RuleGroup(BaseModel):
    match: Literal["all", "any"] = "all"
    rules: list[Rule] = Field(default_factory=list, max_length=8)

    def describe(self) -> str:
        if not self.rules:
            return ""
        joiner = " and " if self.match == "all" else " or "
        return joiner.join(rule.describe() for rule in self.rules)


class Universe(BaseModel):
    asset_class: str = "equity"
    universe: str = "nifty100"
    instruments: list[str] = Field(default_factory=list, max_length=200)
    min_price: float = Field(default=0.0, ge=0)
    max_price: float = Field(default=0.0, ge=0)
    """Zero means no upper limit."""

    min_turnover: float = Field(default=0.0, ge=0)
    """Minimum 20-day average traded value, in the instrument's currency."""

    @field_validator("instruments")
    @classmethod
    def _upper(cls, value: list[str]) -> list[str]:
        return sorted({v.strip().upper() for v in value if v.strip()})


class Ranking(BaseModel):
    by: Operand
    order: Literal["highest", "lowest"] = "highest"


class Sizing(BaseModel):
    method: Literal["equal", "volatility_scaled"] = "equal"
    max_positions: int = Field(default=10, ge=1, le=100)
    vol_target_pct: float = Field(default=20.0, ge=1, le=200)
    """For `volatility_scaled`: a slot is filled in full only when the
    instrument's annualised volatility at entry is at or below this, and
    proportionally less above it. Fixed at entry, so a held position is not
    resized every day as its volatility moves."""

    ranking: Ranking | None = None
    """When more instruments signal than there are slots, which to hold.
    Without it the earliest entries keep their slots."""


class Risk(BaseModel):
    stop_loss_pct: float = Field(default=0.0, ge=0, le=90)
    take_profit_pct: float = Field(default=0.0, ge=0, le=1000)
    trailing_stop_pct: float = Field(default=0.0, ge=0, le=90)
    max_hold_days: int = Field(default=0, ge=0, le=2000)
    """Trading days. Zero means no limit."""


class BuilderSpec(BaseModel):
    id: str = ""
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=600)
    universe: Universe = Field(default_factory=Universe)
    entry: RuleGroup
    exit: RuleGroup = Field(default_factory=RuleGroup)
    sizing: Sizing = Field(default_factory=Sizing)
    risk: Risk = Field(default_factory=Risk)

    @model_validator(mode="after")
    def _complete(self) -> BuilderSpec:
        if not self.entry.rules:
            msg = "add at least one entry rule — without one the strategy never buys"
            raise ValueError(msg)
        exits = self.exit.rules or any(
            (
                self.risk.stop_loss_pct,
                self.risk.take_profit_pct,
                self.risk.trailing_stop_pct,
                self.risk.max_hold_days,
            )
        )
        if not exits:
            msg = (
                "add an exit rule, a stop, a target or a holding limit — "
                "without one every position is held to the end of the backtest"
            )
            raise ValueError(msg)
        if self.universe.max_price and self.universe.max_price <= self.universe.min_price:
            msg = "the maximum price must be above the minimum price"
            raise ValueError(msg)
        if not self.id:
            self.id = make_id(self.name)
        if not re.fullmatch(rf"{ID_PREFIX}[a-z0-9_]{{1,60}}", self.id):
            msg = f"strategy id must look like {ID_PREFIX}name_in_lowercase, not {self.id!r}"
            raise ValueError(msg)
        return self

    def operands(self) -> list[Operand]:
        out = [r.left for r in self.entry.rules] + [r.right for r in self.entry.rules]
        out += [r.left for r in self.exit.rules] + [r.right for r in self.exit.rules]
        if self.sizing.ranking is not None:
            out.append(self.sizing.ranking.by)
        return out

    def warmup(self) -> int:
        """Bars before every rule can be evaluated."""
        base = max((operand.warmup() for operand in self.operands()), default=0)
        if self.sizing.method == "volatility_scaled":
            base = max(base, VOLATILITY_PERIOD + 1)
        return max(base, TURNOVER_PERIOD if self.universe.min_turnover else 0)

    def digest(self) -> str:
        """A hash of what the strategy does, not what it is called.

        Name and description are left out, so renaming a strategy does not make
        its backtest a different configuration.
        """
        material = self.model_dump(exclude={"id", "name", "description"})
        encoded = json.dumps(material, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode()).hexdigest()[:16]


VOLATILITY_PERIOD = 20
TURNOVER_PERIOD = 20


def make_id(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:60] or "strategy"
    return f"{ID_PREFIX}{slug}"


def is_builder_id(strategy_id: str) -> bool:
    return strategy_id.startswith(ID_PREFIX)


def _conditions(group: RuleGroup) -> str:
    if len(group.rules) == 1:
        return group.describe()
    which = "all of" if group.match == "all" else "any of"
    return f"{which}: {group.describe()}"


def summarise(spec: BuilderSpec) -> list[str]:
    """The strategy in plain sentences, in the order it acts."""
    u = spec.universe
    where = (
        f"{len(u.instruments)} chosen instruments"
        if u.instruments
        else f"the {u.universe} universe"
    )
    lines = [f"Trades {where} ({u.asset_class}), long only, deciding on each day's close."]
    filters = []
    if u.min_price:
        filters.append(f"price at least {u.min_price:g}")
    if u.max_price:
        filters.append(f"price at most {u.max_price:g}")
    if u.min_turnover:
        filters.append(f"20-day average turnover at least {u.min_turnover:,.0f}")
    if filters:
        lines.append("Only buys when " + ", ".join(filters) + ".")
    lines.append(f"Buys when {_conditions(spec.entry)}.")
    exits = []
    if spec.exit.rules:
        exits.append(_conditions(spec.exit))
    r = spec.risk
    if r.stop_loss_pct:
        exits.append(f"it falls {r.stop_loss_pct:g}% below the entry")
    if r.take_profit_pct:
        exits.append(f"it rises {r.take_profit_pct:g}% above the entry")
    if r.trailing_stop_pct:
        exits.append(f"it falls {r.trailing_stop_pct:g}% from its highest close since entry")
    if r.max_hold_days:
        exits.append(f"it has been held {r.max_hold_days} trading days")
    lines.append("Sells when " + "; or when ".join(exits) + ".")
    s = spec.sizing
    sizing = (
        f"Holds at most {s.max_positions}, each {100 / s.max_positions:.1f}% of equity"
        if s.method == "equal"
        else (
            f"Holds at most {s.max_positions}, each up to {100 / s.max_positions:.1f}% of "
            f"equity, scaled down when 20-day volatility at entry is above "
            f"{s.vol_target_pct:g}% a year"
        )
    )
    if s.ranking is not None:
        sizing += (
            f"; when more signal than that, keeps the {s.ranking.order} {s.ranking.by.describe()}"
        )
    else:
        sizing += "; when more signal than that, the earliest entries keep their places"
    lines.append(sizing + ".")
    lines.append(f"Needs {spec.warmup()} trading days of history before its first decision.")
    return lines
