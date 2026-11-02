"""The one `Strategy` interface.

`CLAUDE.md`: *One `Strategy` interface, used unchanged by Tier A backtest,
Tier B backtest, paper and live. If those diverge, stop and fix the
abstraction.*

That rule is easy to write and easy to lose. The reference system in
`~/Documents/Trade` shows exactly how it goes: its `run_backtest()` reached
636 lines and branches on strategy *class names* —
`if strategy_cls.__name__ in ("XauusdOrbFvgStrategy", ...)` — building a
different parameter dict for each one. Once the engine knows which strategy it
is running, there is no interface left; there is a switch statement wearing
one. Every later divergence between backtest and live hides in that switch.

So the contract here is deliberately narrow, and narrow in a specific way:

**A strategy is handed what it may see, and returns what it wants to hold.**
It does not fetch data, so it cannot reach past its `as_of`. It does not place
orders, so the same object can drive a vectorised backtest, an event-driven
one, or a live session without knowing which. It does not compute its own
costs, so there is exactly one cost path in the system — the reference system
had two and had to disable one of them with a comment.

**Target weights, not orders.** A weight is what a strategy *means*; an order
is how a particular venue achieves it. Returning orders would bake the
execution model into the strategy and immediately break the "unchanged across
tiers" rule, because Tier A has no order book to speak of.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from eulerlab.features.panel import PanelRow


@dataclass(frozen=True)
class MarketView:
    """Everything a strategy is allowed to see on one decision date.

    Frozen, and containing only history up to `as_of`. The firewall is
    structural rather than a convention: a strategy physically cannot look
    forward because the forward rows are not in the object it was given.
    """

    as_of: date
    history: Mapping[str, Sequence[PanelRow]]
    """Per symbol, oldest first, ending on or before `as_of`."""

    def symbols(self) -> list[str]:
        return sorted(self.history)

    def latest(self, symbol: str) -> PanelRow | None:
        rows = self.history.get(symbol)
        return rows[-1] if rows else None

    def close(self, symbol: str) -> float | None:
        row = self.latest(symbol)
        return row.close if row else None


class Strategy(ABC):
    """Turns a market view into target weights.

    Implementations must be **pure**: same view in, same weights out, no
    hidden state carried between calls. Determinism is a project-wide rule,
    and a strategy that remembers things between bars silently becomes
    path-dependent — which makes Tier A and Tier B disagree for reasons no
    test can localise.
    """

    name: str = "unnamed"

    lookback: int | None = None
    """How many trailing rows per symbol this strategy actually needs.

    `None` means "everything", which is the safe default but is rarely true and
    is expensive: measured on the real panel, building a full-history view for
    4,002 symbols costs 0.84s, and a backtest rebalances ~100 times. Handing a
    feature 2,869 days when it looks back 253 wastes more than 90% of that.

    Declared by the strategy rather than inferred by the engine, because the
    engine must never learn a strategy's internals (ADR-021). A strategy that
    understates it will silently see less history than it needs, so the value
    belongs with the code that knows the answer.
    """

    hold_unchanged: bool = False
    """Leave a holding alone while its target weight has not changed.

    Off by default, which is the rebalancing every strategy here was built on:
    each decision trades every position back to its exact target, so a winner
    is trimmed and a loser topped up. That is right for a monthly ranked book
    and wrong for a signal strategy deciding daily, where "still 10%" means
    "keep holding" — rebalancing it every day turned a golden cross with ten
    slots into 1,853 small round trips in 800 days, paying costs on drift.

    Read by both engines through the same rule, so Tier A and Tier B still
    agree: a symbol held at the decision, whose normalised target equals its
    target at the previous decision, keeps its current quantity. Entries,
    exits and changed weights trade exactly as before.
    """

    ranked_by_order: bool = False
    """`target_weights` lists its names best first, and its weights are sizes,
    not ranks. Read when a deployment's capital cannot buy every name
    (`deploy.sizing.fit_to_capital`): the list is ranked by this order, not by
    weight. Clenow's book weights by inverse volatility, so ranking it by
    weight kept its calmest stock first, not its strongest trend (ADR-120).
    """

    sizing: str = "equal"
    """How the money is split over the names `target_weights` returns
    (`deploy.sizing_models`, ADR-122): ``equal`` (the default: the gross
    exposure split equally, so a slot strategy's idle cash stays idle),
    ``strategy`` (these weights as they are: set it when the weights are part
    of the idea), or a model: ``inverse_vol``, ``hrp``, ``min_variance``.
    The caps of `deploy.sizing.max_weight` apply to every rule. A model needs
    `lookback` of at least `sizing_models.HISTORY_NEEDED` rows, else it falls
    back to equal. Changing a strategy's rule is a new trial for the gate.
    """

    @abstractmethod
    def target_weights(self, view: MarketView) -> dict[str, float]:
        """Desired portfolio weights on `view.as_of`.

        Positive is long and the engine normalises. Negative (short) weights
        are dropped by the daily engines and the paper runner (`long_only`):
        Indian delivery equity cannot be held short overnight (T-4363). A
        symbol left out means zero — absence and zero must mean the same thing
        so a strategy cannot accidentally hold something by forgetting it.
        """

    def describe(self) -> str:
        return self.name


def long_only(weights: Mapping[str, float]) -> tuple[dict[str, float], list[str]]:
    """Split a strategy's weights into the longs kept and the shorts refused.

    The daily engines trade cash equity. An Indian delivery position cannot be
    short overnight (shorts must be squared off the same day), and Tier B's
    cash accounting would book a short sale's proceeds as profit. So a negative
    weight is not traded: it is dropped here, before normalising, and the
    engine counts it on its result so a report can say so (T-4363).
    """
    kept: dict[str, float] = {}
    refused: list[str] = []
    for symbol, weight in weights.items():
        if weight < 0:
            refused.append(symbol)
        else:
            kept[symbol] = weight
    return kept, sorted(refused)


def normalise(weights: Mapping[str, float], *, gross_cap: float = 1.0) -> dict[str, float]:
    """Scale weights so gross exposure is at most `gross_cap`.

    Scaled rather than rejected when a strategy asks for more than it has:
    rejecting would make the engine's behaviour depend on a strategy's
    arithmetic, and the point of the cap is that leverage is the engine's
    decision, never the strategy's.

    Non-finite and zero weights are dropped, so a strategy that produces a NaN
    from a division cannot silently become a position.
    """
    import math

    clean = {
        symbol: weight
        for symbol, weight in weights.items()
        if math.isfinite(weight) and weight != 0.0
    }
    gross = sum(abs(w) for w in clean.values())
    if gross <= gross_cap or gross == 0:
        return clean
    scale = gross_cap / gross
    return {symbol: weight * scale for symbol, weight in clean.items()}


def decide(strategy: Strategy, view: MarketView) -> tuple[dict[str, float], list[str]]:
    """The strategy's longs, split by its declared `sizing`, and the shorts refused.

    The one path from a strategy to its book, shared by Tier A, Tier B and the
    paper/live runner, so a sizing rule cannot hold in one and not another.
    """
    from eulerlab.deploy.sizing_models import rule_of, size_book

    longs, refused = long_only(strategy.target_weights(view))
    return size_book(longs, view, rule_of(strategy)), refused
