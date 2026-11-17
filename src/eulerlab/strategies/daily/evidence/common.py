"""Shared pieces of the evidence strategies: helpers used by more than one, and the types they share."""

from __future__ import annotations

import functools
import statistics
from collections.abc import Sequence
from datetime import date
from itertools import pairwise

from eulerlab.features.panel import PanelRow
from eulerlab.strategies.daily.india_papers import MONTH, YEAR

HOLD = 30
"""Names held, the size of the house momentum strategies (`india_papers`)."""


def monthly_returns(rows: Sequence[PanelRow], months: int) -> list[float] | None:
    """The last `months` 21-session returns, oldest first, or None if short."""
    if len(rows) < months * MONTH + 1:
        return None
    closes = [rows[-1 - k * MONTH].close for k in range(months + 1)][::-1]
    if min(closes) <= 0:
        return None
    return [b / a - 1.0 for a, b in pairwise(closes)]


def residuals(stock: Sequence[float], market: Sequence[float]) -> list[float] | None:
    """Residuals of a one-factor regression of `stock` on `market`."""
    if len(stock) != len(market) or len(stock) < 12:
        return None
    mean_s, mean_m = statistics.fmean(stock), statistics.fmean(market)
    var_m = sum((m - mean_m) ** 2 for m in market)
    if var_m <= 0:
        return None
    beta = sum((s - mean_s) * (m - mean_m) for s, m in zip(stock, market, strict=True)) / var_m
    alpha = mean_s - beta * mean_m
    return [s - alpha - beta * m for s, m in zip(stock, market, strict=True)]


def momentum_12_1(rows: Sequence[PanelRow]) -> float | None:
    if len(rows) <= YEAR or rows[-1 - YEAR].close <= 0:
        return None
    return rows[-1 - MONTH].close / rows[-1 - YEAR].close - 1.0


def _equal(chosen: Sequence[str]) -> dict[str, float]:
    return dict.fromkeys(chosen, 1.0 / len(chosen)) if chosen else {}


WEEK = 5


# --- batch 6: Conservative Formula, Clenow, NSE Alpha Low-Volatility 30 ------------


@functools.cache
def dividends() -> dict[str, tuple[tuple[date, float], ...]]:
    """Symbol to (ex-date, rupees per share), from NSE's corporate-actions feed.

    Read from the landing zone (B2 when pruned locally). A dividend counts from
    its ex-date, when it is certain; its announcement came earlier, so using the
    ex-date only ever learns it late, never early.
    """
    import json

    from eulerlab.corp_actions.build_factors import ACTIONS_GLOB
    from eulerlab.corp_actions.parse import parse_rows
    from eulerlab.ingest import landing_reader

    segment, pattern = ACTIONS_GLOB.split("/", 1)
    rows: list[dict[str, object]] = []
    for name in landing_reader.available(segment, pattern, stale_ok=True):
        rows.extend(json.loads(landing_reader.read(name, cache=False)))
    actions, _ = parse_rows(rows)
    out: dict[str, list[tuple[date, float]]] = {}
    for action in actions:
        paid = sum(c.dividend_amount or 0.0 for c in action.components)
        if paid > 0 and action.symbol:
            out.setdefault(action.symbol, []).append((action.ex_date, paid))
    return {s: tuple(sorted(v)) for s, v in out.items()}


def dividend_yield(symbol: str, rows: Sequence[PanelRow]) -> float:
    """Dividends with an ex-date in the last 365 days, over today's close."""
    if not rows or rows[-1].close <= 0:
        return 0.0
    today = rows[-1].day
    paid = sum(a for d, a in dividends().get(symbol, ()) if 0 <= (today - d).days < 365)
    return paid / rows[-1].close


def _percentiles(values: dict[str, float]) -> dict[str, float]:
    """Rank 0..1, highest value highest; ties by symbol."""
    ordered = sorted(values, key=lambda s: (values[s], s))
    n = max(len(ordered) - 1, 1)
    return {s: i / n for i, s in enumerate(ordered)}


# --- batch 8: Halloween, volatility targeting, dividend yield ---------------------

SAFE = "LIQUIDBEES"
