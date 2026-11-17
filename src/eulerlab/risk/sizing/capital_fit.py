"""Fit a strategy's targets to the capital actually allocated to it.

Operator, 2026-10-07: "if amount is less for strategy allocation make a model
to cut position in lowest ranked instruments like if strategy say to invest in
20 and i can buy top 5 only buy them and leave other".

Operator, 2026-11-02: "in top 10 no stock can be more than 25%, similarly in 20
stocks no stocks more than 15% weight, in 5 stocks no stocks more than 35% ...
ranking and weight allocation both should be respected while taking trade"
(ADR-120).

A backtest on ₹10 lakh can hold thirty ₹33,000 positions. A deployment with
₹50,000 cannot: a ₹5,000 slice buys nothing of a ₹12,000 share, and the
engine's truncation would silently leave that slice in cash while still
holding the cheap names further down the list. That is neither the strategy
nor a choice anyone made.

So the book is fitted in three rules:

1. **Rank.** Names best first. By default that is the higher weight first,
   then the order the strategy listed them (`RankTop` lists its best first).
   A strategy whose weights are sizes, not ranks, sets `ranked_by_order` and
   is ranked by its own order alone: Clenow's book weights by inverse
   volatility, so its largest weight is its calmest stock, not its best trend.
2. **Cap.** No name may hold more than `max_weight(k)` of a `k`-name book
   (`CAPS`), and the excess is spread over the rest in proportion to their
   own weights. Every cap is at least 1/k, so a capped book is always fully
   invested.
3. **Fit.** The largest `k` is kept such that every one of `k` names, at its
   capped weight, buys at least `min_shares` shares. A name that cannot is
   skipped and the next-ranked name takes its place, as Clenow skips a stock
   he cannot afford and moves down the list. Before 2026-11-02 the list was
   cut below such a name instead, which put a ₹50,000 Clenow book into one
   ₹47,589 BOSCHLTD share (HISTORY #60).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from eulerlab.risk.sizing.caps import capped, max_weight


def ranked(targets: Mapping[str, float], *, by_order: bool = False) -> list[str]:
    """Names best first: the strategy's own order when `by_order`, otherwise
    higher weight first, then the strategy's own order."""
    if by_order:
        return list(targets)
    order = {symbol: i for i, symbol in enumerate(targets)}
    return sorted(targets, key=lambda s: (-abs(targets[s]), order[s]))


def _fit_k(
    k: int,
    names: Sequence[str],
    targets: Mapping[str, float],
    budget: Mapping[str, float],
) -> dict[str, float] | None:
    """The top `k` affordable names and their capped weights, or None.

    `budget[s]` is the money one buy of `s` needs as a fraction of equity.
    Takes the top `k`; any name its capped weight cannot buy is skipped and
    the next name in rank takes its place, one at a time, worst shortfall
    first, until the `k` all fit or the list runs out.
    """
    cap = max_weight(k)
    pool = [s for s in names if budget[s] <= cap * (1 + 1e-9)]
    skipped: set[str] = set()
    while True:
        kept = [s for s in pool if s not in skipped][:k]
        if len(kept) < k:
            return None
        weights = capped({s: targets[s] for s in kept}, cap)
        short = [s for s in kept if weights[s] * (1 + 1e-9) < budget[s]]
        if not short:
            return weights
        worst = max(short, key=lambda s: (budget[s] / weights[s], -kept.index(s)))
        skipped.add(worst)


def fit_to_capital(
    targets: Mapping[str, float],
    equity: float,
    price_of: Callable[[str], float | None],
    *,
    min_shares: int = 1,
    by_order: bool = False,
) -> dict[str, float]:
    """The largest book the money can buy: ranked, capped and re-weighted.

    Returns weights summing to the targets' gross exposure, in rank order. A
    name with no price cannot be sized and is dropped, as `target_quantities`
    would drop it. Returns an empty dict when no single name is affordable.
    """
    names = [s for s in ranked(targets, by_order=by_order) if (p := price_of(s)) and p > 0]
    if not names or equity <= 0:
        return {}
    gross = sum(abs(targets[s]) for s in names)
    if gross <= 0:
        return {}
    # Money one buy needs, as a fraction of the gross book.
    budget = {s: min_shares * (price_of(s) or 0.0) / (equity * gross) for s in names}
    for k in range(len(names), 0, -1):
        weights = _fit_k(k, names, targets, budget)
        if weights is not None:
            return {s: weights[s] * gross for s in sorted(weights, key=names.index)}
    return {}
