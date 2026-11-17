"""Many weak signals, one walk-forward forecast, traded only where it beats cost (#155, ADR-192).

Every rule here has had to pay a 12 bps round trip on its own, and 124 intraday
price rules never did. Most systematic equity desks do not trade one signal:
they turn many weak ones, each with a small IC, into one expected return per
stock and trade only where that forecast beats the cost (Grinold and Kahn's
IR ~ IC x sqrt(breadth); Kakushadze, arXiv 1603.05937). This module is that
step, below the allocator (#123), which combines strategies, not signals.

    signals (language-v2 formulas, agent features allowed)
        -> each cross-sectionally ranked and z-scored, per session
    target: open of t to close of t+h-1, net of the session's mean, and of its
            sector's mean when sectors are known (`lang._neutral`)
    walk-forward, monthly: weights fitted only on sessions whose target closed
            before the month began, then applied to that month
        ic     weight = mean IC of each signal on the past
        ridge  pooled ridge regression of the target on the z-scores
        both   shrunk halfway to equal size (`SHRINK`), then scaled to returns by a
               one-number fit on the same past
    trade: a stock only while |forecast| > the round trip's own cost that day
           (a no-trade band); swing long only; the rule engine's books, costs,
           halves, 2x costs and bias checks, unchanged

A combined book is one rule (`Combined`, with a fingerprint), screened once and
recorded as one experiment-store row with its daily returns, so the firewall
counts it. Its inputs' own looks are already rows of their own.

Per-session sums (X'X, X'y, IC) are computed once and accumulated, so a
month's fit costs nothing more than an addition, however long the history.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import warnings
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, Literal

import numpy as np

from eulerlab.features.formula import text_of
from eulerlab.intraday import cross_section as cs
from eulerlab.intraday import rule_engine
from eulerlab.research import feature_registry, lang
from eulerlab.strategies.studies import daily_more as dm
from eulerlab.strategies.studies import daily_universe as du
from eulerlab.strategies.studies import other_data as od

MIN_CROSS = 20
"""Stocks a session needs for its IC or its sums to count."""
MAX_INPUTS = 20
MIN_TRAIN = 250
"""Sessions of fitted history before the first forecast."""
SHRINK = 0.5
"""How far each fitted weight moves toward equal size (same sign) before use."""
RIDGE = 1.0
"""Ridge penalty as a multiple of X'X's mean diagonal."""
DECAY_HORIZONS = (1, 2, 5, 10, 20)

# ASSUMPTION: A-152 — the shrink, ridge penalty and warm-up were chosen by hand, not tuned.

Method = Literal["ic", "ridge"]
Kind = Literal["intraday", "swing"]


# --- targets and IC ------------------------------------------------------------------------


def forward_returns(store: Any, horizon: int) -> lang.Matrix:
    """Open of session t to close of session t+h-1, minus that session's cross-section mean.

    A score readable at session t's open (lang's convention) trades at that open.
    Moves outside the split guard (`du.SPLIT_LOW`, `du.SPLIT_HIGH`) are dropped,
    since the panel's prices are not split-adjusted."""
    opens = store.field("open_price", 1)
    closes = store.field("close_price", 1)
    later = np.full(closes.shape, np.nan)
    if horizon <= closes.shape[0]:
        later[: closes.shape[0] - horizon + 1] = closes[horizon - 1 :]
    with np.errstate(invalid="ignore", divide="ignore"):
        ratio = np.where(opens > 0, later / np.where(opens > 0, opens, 1.0), np.nan)
    ratio[(ratio < du.SPLIT_LOW) | (ratio > du.SPLIT_HIGH)] = np.nan
    raw = ratio - 1.0
    raw[~store.tradable] = np.nan
    with warnings.catch_warnings():  # a session with no returns has no mean: NaN is right
        warnings.simplefilter("ignore", RuntimeWarning)
        mean = np.nanmean(raw, axis=1, keepdims=True)
    return np.asarray(raw - mean, dtype=np.float64)


def _ic_series(score: lang.Matrix, ahead: lang.Matrix) -> lang.Matrix:
    rs, ra = lang._rank(score), lang._rank(ahead)
    out = np.full(rs.shape[0], np.nan)
    for t in range(rs.shape[0]):
        both = ~np.isnan(rs[t]) & ~np.isnan(ra[t])
        if both.sum() < MIN_CROSS:
            continue
        x, y = rs[t, both], ra[t, both]
        if x.std() and y.std():
            out[t] = float(np.corrcoef(x, y)[0, 1])
    return out


def information_coefficient(score: lang.Matrix, ahead: lang.Matrix, horizon: int) -> dict[str, Any]:
    """Mean rank IC across sessions, its t-stat on non-overlapping sessions, share positive."""
    series = _ic_series(score, ahead)
    valid = series[~np.isnan(series)]
    apart = series[::horizon]
    apart = apart[~np.isnan(apart)]
    t_stat = (
        float(apart.mean() / apart.std(ddof=1) * np.sqrt(len(apart)))
        if len(apart) > 2 and apart.std(ddof=1) > 0
        else None
    )
    return {
        "horizon": horizon,
        "sessions": len(valid),
        "mean_ic": round(float(valid.mean()), 4) if len(valid) else None,
        "t_stat_non_overlapping": round(t_stat, 2) if t_stat is not None else None,
        "share_positive": round(float((valid > 0).mean()), 3) if len(valid) else None,
    }


def ic_decay(
    score: lang.Matrix, store: Any, horizons: Sequence[int] = DECAY_HORIZONS
) -> dict[int, float | None]:
    """Mean IC by horizon: where a signal's information runs out, so a hold comes from evidence."""
    return {
        h: information_coefficient(score, forward_returns(store, h), h)["mean_ic"] for h in horizons
    }


# --- the walk-forward fit ------------------------------------------------------------------


def _z(x: lang.Matrix) -> lang.Matrix:
    return lang._zscore(lang._rank(x))


@dataclass
class Forecast:
    values: lang.Matrix
    """Expected return (net of the session's mean) per stock-session; NaN where none."""
    first: int
    """The first session with a forecast."""
    months: list[dict[str, Any]] = field(default_factory=list)
    """Each month's fit: its weights, scale and training sessions."""


def _sums(z: lang.Matrix, y: lang.Matrix) -> tuple[lang.Matrix, lang.Matrix, lang.Matrix]:
    """Per session: X'X (T, k, k), X'y (T, k) and each signal's rank IC (T, k)."""
    k, t_len, _ = z.shape
    xtx = np.zeros((t_len, k, k))
    xty = np.zeros((t_len, k))
    ics = np.full((t_len, k), np.nan)
    ry = lang._rank(y)
    for t in range(t_len):
        ok = ~np.isnan(y[t])
        if ok.sum() < MIN_CROSS:
            continue
        x = np.nan_to_num(z[:, t, ok]).T
        xtx[t] = x.T @ x
        xty[t] = x.T @ y[t, ok]
        for j in range(k):
            both = ok & ~np.isnan(z[j, t])
            if both.sum() >= MIN_CROSS:
                a, b = z[j, t, both], ry[t, both]
                if a.std() and b.std():
                    ics[t, j] = float(np.corrcoef(a, b)[0, 1])
    return xtx, xty, ics


def _months(days: Sequence[date]) -> list[tuple[int, int]]:
    """(start, end) session indices of each calendar month, end exclusive."""
    out: list[tuple[int, int]] = []
    for i, d in enumerate(days):
        if i == 0 or (d.year, d.month) != (days[i - 1].year, days[i - 1].month):
            out.append((i, i))
        out[-1] = (out[-1][0], i + 1)
    return out


def _shrink(w: lang.Matrix, shrink: float) -> lang.Matrix:
    equal = np.sign(w) * np.abs(w).mean()
    return np.asarray((1 - shrink) * w + shrink * equal, dtype=np.float64)


def walk_forward(
    store: Any,
    trees: Sequence[Any],
    *,
    horizon: int,
    method: Method = "ic",
    shrink: float = SHRINK,
    min_train: int = MIN_TRAIN,
    neutral: bool = True,
    names: Sequence[str] = (),
) -> Forecast:
    """Fit each month on what had closed before it, and forecast that month."""
    ev = lang.Evaluator(store)
    tradable = store.tradable
    z = np.stack([_z(np.where(tradable, ev.value(tree), np.nan)) for tree in trees])
    y = forward_returns(store, horizon)
    groups = store.groups()
    if neutral and (groups >= 0).any():
        y = lang._neutral(y, groups)
    xtx, xty, ics = _sums(z, y)
    cum_xtx = np.concatenate([np.zeros((1, *xtx.shape[1:])), np.cumsum(xtx, axis=0)])
    cum_xty = np.concatenate([np.zeros((1, xty.shape[1])), np.cumsum(xty, axis=0)])
    cum_ic = np.concatenate([np.zeros((1, ics.shape[1])), np.cumsum(np.nan_to_num(ics), axis=0)])
    cum_n = np.concatenate([np.zeros((1, ics.shape[1])), np.cumsum(~np.isnan(ics), axis=0)])
    k = z.shape[0]
    labels = list(names) or [f"s{j}" for j in range(k)]
    values = np.full(y.shape, np.nan)
    months: list[dict[str, Any]] = []
    first = -1
    for start, end in _months(store.days):
        cut = start - horizon + 1  # targets of sessions before `cut` closed before `start`
        if cut < min_train:
            continue
        a, b = cum_xtx[cut], cum_xty[cut]
        if method == "ic":
            n = np.maximum(cum_n[cut], 1)
            w = cum_ic[cut] / n
        else:
            alpha = RIDGE * float(np.trace(a)) / k
            w = np.linalg.solve(a + alpha * np.eye(k), b)
        if not np.any(w):
            continue
        w = _shrink(w, shrink)
        den = float(w @ a @ w)
        scale = float(w @ b) / den if den > 0 else 0.0
        block = z[:, start:end, :]
        known = ~np.all(np.isnan(block), axis=0)
        combined = np.einsum("k,ktn->tn", w, np.nan_to_num(block)) * scale
        values[start:end] = np.where(known & tradable[start:end], combined, np.nan)
        first = start if first < 0 else first
        months.append(
            {
                "month": store.days[start].strftime("%Y-%m"),
                "trained_on": cut,
                "weights": {labels[j]: round(float(w[j]), 4) for j in range(k)},
                "scale": round(scale, 6),
            }
        )
    return Forecast(values, first, months)


# --- the book ------------------------------------------------------------------------------


@dataclass(frozen=True)
class Combined:
    """A combined book as a rule: what the engine's screen and the store need of it."""

    kind: Kind
    hold: int
    first: date
    inputs: tuple[str, ...]
    method: str
    shrink: float
    min_train: int

    def fingerprint(self) -> str:
        body = {**asdict(self), "first": self.first.isoformat(), "shape": "combined"}
        return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:16]

    def describe(self) -> str:
        hold = "open to close" if self.kind == "intraday" else f"hold {self.hold} sessions"
        return (
            f"{self.kind}: combined forecast of {len(self.inputs)} signal(s) ({self.method}, "
            f"walk-forward monthly), traded where it beats the round trip; {hold}"
        )


class _Book(rule_engine.Engine):
    """The engine's books and checks on entries chosen outside it."""

    def __init__(self, data: rule_engine.Data, chosen: list[rule_engine.Event]) -> None:
        super().__init__(data)
        self._chosen = chosen

    def events(self, spec: rule_engine.Rule) -> list[rule_engine.Event]:
        return self._chosen


def cost_band(kind: Kind, day: date) -> float:
    """The round trip's cost on ₹1 lakh at ₹100 a share that day, as a fraction of the notional."""
    quantity = int(dm.TRADE / 100.0)
    notional = 100.0 * quantity
    if kind == "intraday":
        trade = cs.Trade("X", day, 1, quantity, 0, 100.0, 374, 100.0, "close")
        return trade.costs / notional
    swing = od.Swing("X", day, day, quantity, 100.0, 100.0, ())
    return sum(swing.costs_at()) / notional


def entries(
    forecast: Forecast, store: Any, kind: Kind, band: Callable[[date], float] | None = None
) -> list[rule_engine.Event]:
    """Every stock-session whose forecast beats the band; best first; swing long only."""
    price = band or (lambda d: cost_band(kind, d))
    out: list[rule_engine.Event] = []
    cached: dict[tuple[int, int], float] = {}
    values = forecast.values
    for t, day in enumerate(store.days):
        if t < max(forecast.first, 0) or not store.ok_day[t]:
            continue
        row = values[t]
        cut = cached.setdefault((day.year, day.month), price(day))
        for j in np.flatnonzero(~np.isnan(row)):
            f = float(row[j])
            if abs(f) <= cut or (kind == "swing" and f <= 0):
                continue
            out.append((day, store.symbols[j], 1 if f > 0 else -1, -abs(f)))
    return out


def combine(
    engine: Any,
    formulas: Sequence[str],
    *,
    kind: Kind,
    hold: int = 0,
    method: Method = "ic",
    shrink: float = SHRINK,
    min_train: int = MIN_TRAIN,
    neutral: bool = True,
) -> dict[str, Any]:
    """Fit, forecast and screen one combined book. Returns its rule, screen, daily returns,
    monthly weights, each input's IC decay, turnover and cost share."""
    if kind == "intraday" and hold:
        msg = "an intraday book closes the same session: hold must be 0"
        raise ValueError(msg)
    if kind == "swing" and not 2 <= hold <= 60:
        msg = "a swing book holds 2 to 60 sessions"
        raise ValueError(msg)
    if not 2 <= len(formulas) <= MAX_INPUTS:
        msg = f"combine 2 to {MAX_INPUTS} signals"
        raise ValueError(msg)
    store = engine.store
    trees = [lang.compile_text(feature_registry.expand(f)) for f in formulas]
    texts = tuple(text_of(t) for t in trees)
    horizon = 1 if kind == "intraday" else hold + 1
    fit = walk_forward(
        store,
        trees,
        horizon=horizon,
        method=method,
        shrink=shrink,
        min_train=min_train,
        neutral=neutral,
        names=texts,
    )
    if fit.first < 0:
        msg = f"under {min_train} sessions of history: nothing to fit"
        raise ValueError(msg)
    rule = Combined(kind, hold, store.days[fit.first], texts, method, shrink, min_train)
    chosen = entries(fit, store, kind)
    book = _Book(engine.data, chosen)
    screen = book.screen(rule)
    daily = book.returns.pop(rule.fingerprint(), {})
    pieces = book.pieces(rule)
    gross = sum(p.gross for p in pieces)
    costs = sum(p.costs for p in pieces)
    window = book.window(rule)
    ev = lang.Evaluator(store)
    decay = {
        text: ic_decay(np.where(store.tradable, ev.value(tree), np.nan), store)
        for text, tree in zip(texts, trees, strict=True)
    }
    return {
        "rule": rule,
        "screen": screen,
        "daily": daily,
        "months": fit.months,
        "ic_decay": decay,
        "entries_per_session": round(screen.get("count", 0) / len(window), 2) if window else 0,
        "cost_share": round(costs / gross, 3) if gross > 0 else None,
    }


def summary(found: dict[str, Any]) -> dict[str, Any]:
    """What a researcher reads first: the brief figures plus turnover, cost share and weights."""
    from eulerlab.research.agent_tools import brief

    last = found["months"][-1] if found["months"] else {}
    return {
        "rule": found["rule"].describe(),
        "out_of_sample_from": found["rule"].first.isoformat(),
        **brief(found["screen"]),
        "entries_per_session": found["entries_per_session"],
        "cost_share": found["cost_share"],
        "latest_weights": last.get("weights"),
        "ic_decay": {k[:80]: v for k, v in found["ic_decay"].items()},
    }


def record(found: dict[str, Any], *, asked_by: str, now: Any = None) -> str:
    """One experiment-store row with the book's daily returns: one trial, in the firewall's bar."""
    from eulerlab.research import experiments

    rule: Combined = found["rule"]
    fields = sorted(set(lang.complexity([lang.compile_text(t) for t in rule.inputs])["fields"]))
    daily = found["daily"]
    return experiments.record(
        purpose="screen",
        fingerprint=rule.fingerprint(),
        family=f"combined:{rule.kind}:{'+'.join(fields)}",
        first=rule.first,
        end=max(daily) if daily else rule.first,
        metrics={**summary(found), "inputs": list(rule.inputs), "method": rule.method},
        daily=daily,
        asked_by=asked_by,
        now=now,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="make combine", description=__doc__)
    parser.add_argument("--formula", action="append", default=[], help="a signal; repeat it")
    parser.add_argument("--kind", choices=["intraday", "swing"], default="swing")
    parser.add_argument("--hold", type=int, default=5)
    parser.add_argument("--method", choices=["ic", "ridge"], default="ic")
    args = parser.parse_args(argv)
    from eulerlab import constitution
    from eulerlab.research import agent_tools

    # Recorded as a screen, so the book is built on discovery data only (#152).
    engine = agent_tools.discovery_engine(constitution.load().periods.discovery_end)
    hold = 0 if args.kind == "intraday" else args.hold
    found = combine(engine, args.formula, kind=args.kind, hold=hold, method=args.method)
    row = record(found, asked_by="operator")
    print(json.dumps({"experiment": row, **summary(found)}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
