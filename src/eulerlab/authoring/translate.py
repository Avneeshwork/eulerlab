"""Turning a description into something runnable — via validation, never trust.

The model is the least trusted component in this system, and the design says so
in three ways.

**It produces a draft, not a decision.** Every output goes through code that
can reject it: a composed spec is checked against the real feature library, and
source code is checked by the sandbox. A model that hallucinates a feature
called `momentum_9_2` gets a specific error naming the ten features that
actually exist, not a silent substitution.

**The operator sees it before it runs.** `draft()` returns the strategy; it
does not execute it. Nothing here starts a backtest.

**Two modes, and the safer one is the default.** `composed` restricts the model
to picking from vetted primitives — the ADR-027 path, where every component
already has tests behind it. `code` lets it write a strategy body, which is
more expressive and has nothing behind it but the sandbox. The difference is
worth stating plainly: in `composed` mode a bad draft is a bad *choice* among
correct pieces, and in `code` mode it can be an arithmetic bug that looks like
a finding.

Neither mode can produce lookahead. That is not a property of the prompt — it
is the `MarketView`, which contains no future rows for the code to reach.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from eulerlab.authoring.sandbox import SandboxedStrategy, UnsafeStrategy
from eulerlab.backtest.strategies import RankAndHold
from eulerlab.backtest.strategy import Strategy
from eulerlab.features.library import BY_NAME
from eulerlab.llm import client

MODES = ("composed", "code")


def library_summary() -> str:
    return "\n".join(f"  {f.name:<22} {f.description}" for f in BY_NAME.values())


COMPOSED_SYSTEM = f"""You translate a trading idea into a strategy specification for a \
backtesting system. You do not write code and you do not evaluate the idea.

Reply with ONE JSON object and nothing else. No prose, no markdown fence.

{{
  "feature": "<exactly one name from the list below>",
  "top_n": <integer 5-100, how many names to hold>,
  "rebalance": <integer 5-126, trading days between rebalances>,
  "min_turnover": <number, minimum median daily turnover in rupees, 0 for no filter>,
  "explanation": "<one or two sentences: what this holds and why it matches the request>"
}}

The ONLY features that exist:
{library_summary()}

Rules:
- "feature" must be copied exactly from the list. Do not invent one. If nothing
  fits, pick the closest and say so in "explanation".
- Every feature is oriented so HIGHER IS BETTER and the top N are held.
  "low_volatility" is already negated volatility, so a high value means calm.
- The system holds an equal-weighted long-only book. It cannot short.
"""

CODE_SYSTEM = """You write one Python function for a restricted backtesting sandbox.

Reply with ONLY the code. No markdown fence, no explanation outside comments.

The function signature is exactly:

    def weights(view):

`view` is everything you may see. It contains history up to the decision date
and NOTHING after it, so lookahead is impossible by construction:

    view.as_of                -> the decision date
    view.symbols()            -> sorted list of symbol strings
    view.history[symbol]      -> list of rows, OLDEST FIRST, ending on or before as_of
    view.close(symbol)        -> most recent close as a float, or None
    view.latest(symbol)       -> most recent row, or None

Each row has: .day  .close  .volume  .turnover  .symbol

Return {symbol: weight}. Weights are normalised by the engine so they need not
sum to 1. A symbol you leave out is held at zero. Return {} to hold nothing.

HARD CONSTRAINTS — code violating any of these is rejected before it runs:
- No imports. No `while`. No classes, `try`, `with`, `global`, `del`, `lambda`
  decorators, or generators.
- Available builtins ONLY: len min max sum abs round sorted reversed enumerate
  zip list dict set tuple float int str bool any all pow divmod range.
  There is no `open`, `getattr`, `eval`, `type`, or `numpy`.
- Attributes are restricted to those listed above plus ordinary dict/list
  methods (.items .keys .values .get .append .sort).
- Always guard for short history: `if len(rows) < N: continue`.
- Guard against division by zero and prices <= 0.

Write plainly. Prefer an obvious loop to a clever comprehension.
"""


@dataclass
class Draft:
    """What the model proposed, after validation. Not yet run."""

    mode: str
    explanation: str = ""
    spec: dict[str, Any] = field(default_factory=dict)
    source: str = ""
    provider: str = ""
    model: str = ""
    warnings: list[str] = field(default_factory=list)

    def build(self) -> Strategy:
        """Realise it as a `Strategy`. The same interface everything else uses."""
        if self.mode == "code":
            return SandboxedStrategy(self.source, name=self.spec.get("name", "authored"))
        feature = BY_NAME[str(self.spec["feature"])]
        return RankAndHold(
            feature,
            top_n=int(self.spec["top_n"]),
            min_turnover=float(self.spec.get("min_turnover", 0.0)),
        )

    def label(self) -> str:
        if self.mode == "code":
            return "authored code"
        return f"{self.spec.get('feature')} | top {self.spec.get('top_n')}"


def _strip_fence(text: str) -> str:
    """Models wrap output in ``` fences despite being asked not to.

    Tolerated rather than rejected. Refusing a reply that is correct apart from
    three backticks would make the whole feature feel broken for a cosmetic
    reason, and the content is validated either way.
    """
    fenced = re.search(r"```(?:json|python)?\s*\n(.*?)```", text, re.DOTALL)
    return (fenced.group(1) if fenced else text).strip()


def parse_composed(text: str) -> tuple[dict[str, Any], list[str]]:
    """Validate a composed spec against the library that actually exists."""
    cleaned = _strip_fence(text)
    # A model sometimes emits a sentence before the object. Take the outermost
    # braces rather than failing on a leading pleasantry.
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end == -1:
        msg = f"the model did not return a JSON object. It said: {cleaned[:200]}"
        raise UnsafeStrategy(msg)

    try:
        spec = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as exc:
        msg = f"the model's JSON did not parse ({exc.msg}): {cleaned[:200]}"
        raise UnsafeStrategy(msg) from exc

    feature = str(spec.get("feature", ""))
    if feature not in BY_NAME:
        msg = (
            f"the model chose a feature that does not exist: {feature!r}.\n"
            f"The library has exactly these: {', '.join(sorted(BY_NAME))}.\n"
            f"A new feature has to be written and tested by hand first (ADR-027)."
        )
        raise UnsafeStrategy(msg)

    warnings: list[str] = []
    top_n = int(spec.get("top_n", 30) or 30)
    if not 5 <= top_n <= 100:
        warnings.append(f"top_n was {top_n}; clamped into 5-100")
        top_n = max(5, min(100, top_n))

    rebalance = int(spec.get("rebalance", 21) or 21)
    if not 5 <= rebalance <= 126:
        warnings.append(f"rebalance was {rebalance}; clamped into 5-126")
        rebalance = max(5, min(126, rebalance))

    return (
        {
            "feature": feature,
            "top_n": top_n,
            "rebalance": rebalance,
            "min_turnover": float(spec.get("min_turnover", 0.0) or 0.0),
        },
        warnings,
    )


def _compiles(text: str) -> None:
    SandboxedStrategy(_strip_fence(text), name="draft")


def draft(
    description: str,
    *,
    mode: str = "composed",
    provider_name: str | None = None,
    privacy_safe: bool = False,
    model_name: str = "",
) -> Draft:
    """Ask the model, validate what comes back, return it unrun."""
    if mode not in MODES:
        msg = f"mode must be one of {MODES}, got {mode!r}"
        raise ValueError(msg)

    system = COMPOSED_SYSTEM if mode == "composed" else CODE_SYSTEM
    if privacy_safe:
        from eulerlab.assistant import chat

        chat_reply = chat.complete_any(
            system,
            description.strip(),
            name=provider_name or "",
            model=model_name,
            # A draft the sandbox rejects sends the request on to the next model.
            accept=None if mode == "composed" else _compiles,
        )
        answer_text, answer_provider, answer_model = (
            chat_reply.text,
            chat_reply.provider,
            chat_reply.model,
        )
    else:
        client_reply = client.complete(system, description.strip(), provider_name=provider_name)
        answer_text, answer_provider, answer_model = (
            client_reply.text,
            client_reply.provider,
            client_reply.model,
        )

    if mode == "composed":
        spec, warnings = parse_composed(answer_text)
        explanation = ""
        try:
            raw = json.loads(_strip_fence(answer_text)[_strip_fence(answer_text).find("{") :])
            explanation = str(raw.get("explanation", ""))
        except (json.JSONDecodeError, ValueError):
            explanation = ""
        return Draft(
            mode=mode,
            spec=spec,
            explanation=explanation,
            warnings=warnings,
            provider=answer_provider,
            model=answer_model,
        )

    source = _strip_fence(answer_text)
    # Compiled here, immediately, so an invalid draft fails now rather than
    # after the operator has approved it and a backtest has started.
    SandboxedStrategy(source, name="draft")
    return Draft(
        mode=mode,
        source=source,
        spec={"name": "authored"},
        explanation="Validated by the sandbox. Read it before running it.",
        provider=answer_provider,
        model=answer_model,
    )


def from_code(source: str, *, name: str = "authored") -> Draft:
    """The no-model path: the operator pasted code themselves.

    Same validation, same sandbox. Whether a human or a model wrote it changes
    nothing about what it is allowed to reach.
    """
    SandboxedStrategy(source, name=name)
    return Draft(mode="code", source=source, spec={"name": name}, provider="none", model="none")


def from_spec(
    feature: str, top_n: int = 30, rebalance: int = 21, min_turnover: float = 0.0
) -> Draft:
    """The no-model path for a composed strategy: pick from the library directly."""
    if feature not in BY_NAME:
        msg = f"unknown feature {feature!r}. The library has: {', '.join(sorted(BY_NAME))}"
        raise UnsafeStrategy(msg)
    return Draft(
        mode="composed",
        spec={
            "feature": feature,
            "top_n": int(top_n),
            "rebalance": int(rebalance),
            "min_turnover": float(min_turnover),
        },
        provider="none",
        model="none",
    )
