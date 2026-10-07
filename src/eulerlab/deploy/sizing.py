"""Fit a strategy's targets to the capital actually allocated to it.

Operator, 2026-10-07: "if amount is less for strategy allocation make a model
to cut position in lowest ranked instruments like if strategy say to invest in
20 and i can buy top 5 only buy them and leave other".

A backtest on ₹10 lakh can hold thirty ₹33,000 positions. A deployment with
₹50,000 cannot: a ₹5,000 slice buys nothing of a ₹12,000 share, and the
engine's truncation would silently leave that slice in cash while still
holding the cheap names further down the list. That is neither the strategy
nor a choice anyone made.

So the list is cut from the bottom. The strategy's names are ranked — by weight,
then by the order the strategy listed them (`RankTop` lists its best first) —
and the largest `k` is kept such that every one of the top `k`, given its share
of the money, can buy at least `min_shares` shares at today's close. The kept
names are re-weighted to the same total exposure. Nothing below the cut is
bought.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping


def ranked(targets: Mapping[str, float]) -> list[str]:
    """Names best first: higher weight first, then the strategy's own order."""
    order = {symbol: i for i, symbol in enumerate(targets)}
    return sorted(targets, key=lambda s: (-abs(targets[s]), order[s]))


def fit_to_capital(
    targets: Mapping[str, float],
    equity: float,
    price_of: Callable[[str], float | None],
    *,
    min_shares: int = 1,
) -> dict[str, float]:
    """The top `k` names the money can actually buy, re-weighted.

    Unchanged when every name is affordable. A name with no price cannot be
    sized and is dropped, as `target_quantities` would drop it. Returns an empty
    dict when not even the best-ranked name is affordable.
    """
    names = [s for s in ranked(targets) if (p := price_of(s)) is not None and p > 0]
    if not names or equity <= 0:
        return {}
    gross = sum(abs(targets[s]) for s in names)
    for k in range(len(names), 0, -1):
        kept = names[:k]
        share = sum(abs(targets[s]) for s in kept)
        scale = gross / share if share else 0.0
        if all(
            equity * abs(targets[s]) * scale * (1 + 1e-9) >= min_shares * (price_of(s) or 0.0)
            for s in kept
        ):
            if k == len(targets):
                return dict(targets)
            return {s: targets[s] * scale for s in kept}
    return {}


def affordable_count(
    targets: Mapping[str, float], equity: float, price_of: Callable[[str], float | None]
) -> int:
    return len(fit_to_capital(targets, equity, price_of))
