"""Shared pieces of the github strategies: helpers used by more than one, and the types they share."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from eulerlab.backtest.strategy import MarketView, Strategy
from eulerlab.features.panel import PanelRow
from eulerlab.strategies.daily.india_papers import liquid_universe

STATE_WINDOW = 250
"""Sessions replayed to know whether a position rule is in a trade today."""

Signal = Callable[[int], bool]


def in_trade(n: int, enter: Signal, leave: Signal, *, start: int) -> int | None:
    """The bar a still-open trade was entered on, or None when flat at bar n-1.

    Walks bars `start..n-1`: flat until `enter(i)`, then in until `leave(i)`.
    A bar that enters cannot also leave.
    """
    entered: int | None = None
    for i in range(start, n):
        if entered is None:
            if enter(i):
                entered = i
        elif leave(i):
            entered = None
    return entered


def _closes(rows: Sequence[PanelRow]) -> list[float]:
    return [r.close for r in rows]


Age = int | None
"""Sessions since a rule entered its open trade (0 = entered today), or None when flat."""


def _age(n: int, entered: int | None) -> Age:
    return None if entered is None else n - 1 - entered


class PositionRule(Strategy):
    """Hold up to `slots` stocks a per-stock entry/exit rule says are in a trade.

    Each holding is a fixed 1/`slots` of capital. When more than `slots` are in,
    the longest-held are kept, as a trader holding positions to their exit
    would. Until 2026-10-18 every in-trade stock got an equal share instead:
    with a hundred names above a golden cross, each day's change in the count
    re-sized all of them, and the bill for those trims (122,004 fills for the
    golden cross) was charged to the rule. Research 113 states both runs.
    """

    rebalance_every = 1

    def __init__(
        self,
        name: str,
        rule: Callable[[Sequence[PanelRow]], Age],
        *,
        lookback: int,
        slots: int,
        instruments: tuple[str, ...] = (),
    ) -> None:
        self.name = name
        self.rule = rule
        self.lookback = lookback
        self.slots = slots
        self.instruments = instruments
        self.hold_unchanged = True

    def target_weights(self, view: MarketView) -> dict[str, float]:
        names = list(self.instruments) or liquid_universe(view)
        aged: list[tuple[int, str]] = []
        for s in names:
            rows = view.history.get(s)
            if rows and rows[-1].day == view.as_of and (age := self.rule(rows)) is not None:
                aged.append((age, s))
        aged.sort(key=lambda item: (-item[0], item[1]))
        return {s: 1.0 / self.slots for _, s in aged[: self.slots]}


# --- batch 2 (research 113): golden cross, Supertrend, MACD, Faber TAA -------------


def crossing_rule(fast: Sequence[float | None], slow: Sequence[float | None], n: int) -> Age:
    """In from a cross of `fast` above `slow`, out at the cross back below."""

    def above(i: int) -> bool | None:
        a, b = fast[i], slow[i]
        return None if a is None or b is None else a > b

    def enter(i: int) -> bool:
        return i > 0 and above(i) is True and above(i - 1) is False

    def leave(i: int) -> bool:
        return i > 0 and above(i) is False and above(i - 1) is True

    return _age(n, in_trade(n, enter, leave, start=max(1, n - STATE_WINDOW)))
