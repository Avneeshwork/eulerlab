"""Shared pieces of the screener strategies: helpers used by more than one, and the types they share."""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Mapping, Sequence
from datetime import date
from functools import cache
from typing import Any

from eulerlab.backtest import topdown
from eulerlab.backtest.event_driven import FAR_FUTURE
from eulerlab.backtest.strategy import MarketView, Strategy
from eulerlab.features.panel import PanelRow
from eulerlab.fundamentals import annual
from eulerlab.strategies.daily.india_papers import MONTH, YEAR, liquid_universe

TOP = 20
SLOTS = 10
LONG = "long"
SWING = "swing"


# --- corporate-action units -----------------------------------------------------------------------


@cache
def _factors() -> dict[str, tuple[list[date], list[float]]]:
    """Per ISIN, the action dates and the running product of factors after each, for `units`."""
    from eulerlab.features.panel import load_price_factor_store

    events: dict[str, list[tuple[date, float]]] = {}
    for record in load_price_factor_store().query(as_of=FAR_FUTURE):
        events.setdefault(record.key, []).append((record.event_time.date(), float(record.value)))
    out: dict[str, tuple[list[date], list[float]]] = {}
    for isin, ev in events.items():
        ev.sort()
        after = [1.0] * (len(ev) + 1)
        for i in range(len(ev) - 1, -1, -1):
            after[i] = after[i + 1] * ev[i][1]
        out[isin] = ([d for d, _ in ev], after)
    return out


def units(isin: str, day: date) -> float:
    """Today's per-share figures times this are in `day`'s units: the product of later actions' factors."""
    got = _factors().get(isin)
    if not got:
        return 1.0
    days, after = got
    return after[bisect_right(days, day)]


# --- fundamentals as of a date --------------------------------------------------------------------


def _div(a: float | None, b: float | None) -> float | None:
    return a / b if a is not None and b not in (None, 0.0) else None


def facts(isin: str, day: date, price: float) -> dict[str, float] | None:
    """Quality, value and F-score inputs from the last two years published by `day`."""
    years = annual.known(annual.load().get(isin, []), day)
    if not years or price <= 0:
        return None
    y = years[-1]
    p = years[-2] if len(years) > 1 else None
    equity = (y.get("equity_capital") or 0.0) + (y.get("reserves") or 0.0)
    eps = y.get("eps")
    out: dict[str, float] = {}
    if equity > 0:
        roe = _div(y.get("net_profit"), equity)
        lev = _div(y.get("borrowings"), equity)
        if roe is not None:
            out["roe"] = roe
        if lev is not None:
            out["leverage"] = lev
    if (opa := _div(y.get("op_profit"), y.get("total_assets"))) is not None:
        out["op_assets"] = opa
    if (payout := y.get("payout")) is not None:
        out["payout"] = payout / 100
    if eps:
        k = units(isin, day)
        out["earnings_yield"] = eps * k / price
        shares = _div(y.get("net_profit"), eps)
        if shares and shares > 0 and equity > 0:
            out["book_yield"] = equity / shares * k / price
    if p is not None:
        out["fscore"] = float(fscore(y, p))
    return out


def fscore(y: annual.Year, p: annual.Year) -> int:
    """Piotroski's signals that screener.in data allows: 8 of 9 (no current ratio)."""

    def ratio(year: annual.Year, a: str, b: str) -> float | None:
        return _div(year.get(a), year.get(b))

    roa, roa0 = ratio(y, "net_profit", "total_assets"), ratio(p, "net_profit", "total_assets")
    lev, lev0 = ratio(y, "borrowings", "total_assets"), ratio(p, "borrowings", "total_assets")
    mar, mar0 = ratio(y, "op_profit", "sales"), ratio(p, "op_profit", "sales")
    turn, turn0 = ratio(y, "sales", "total_assets"), ratio(p, "sales", "total_assets")
    cfo, np_ = y.get("cfo"), y.get("net_profit")
    cap, cap0 = y.get("equity_capital"), p.get("equity_capital")
    signals = [
        roa is not None and roa > 0,
        cfo is not None and cfo > 0,
        roa is not None and roa0 is not None and roa > roa0,
        cfo is not None and np_ is not None and cfo > np_,
        lev is not None and lev0 is not None and lev < lev0,
        cap is not None and cap0 is not None and cap <= cap0,
        mar is not None and mar0 is not None and mar > mar0,
        turn is not None and turn0 is not None and turn > turn0,
    ]
    return sum(signals)


def _z(values: Mapping[str, float]) -> dict[str, float]:
    """Cross-sectional ranks scaled to -1..+1: robust to the outliers accounting ratios have."""
    order = sorted(values, key=lambda s: (values[s], s))
    n = len(order)
    return {s: (2 * i / (n - 1) - 1 if n > 1 else 0.0) for i, s in enumerate(order)}


def quality(f: Mapping[str, Mapping[str, float]]) -> dict[str, float]:
    """Mean rank of ROE, operating profit over assets, low leverage and payout."""
    parts = [
        _z({s: v["roe"] for s, v in f.items() if "roe" in v}),
        _z({s: v["op_assets"] for s, v in f.items() if "op_assets" in v}),
        _z({s: -v["leverage"] for s, v in f.items() if "leverage" in v}),
        _z({s: v["payout"] for s, v in f.items() if "payout" in v}),
    ]
    return _mean_of(parts, f)


def _mean_of(parts: Sequence[Mapping[str, float]], names: Mapping[str, Any]) -> dict[str, float]:
    out = {}
    for s in names:
        got = [p[s] for p in parts if s in p]
        if len(got) >= max(1, len(parts) // 2):
            out[s] = sum(got) / len(got)
    return out


def _universe_facts(view: MarketView) -> tuple[list[str], dict[str, dict[str, float]]]:
    names = liquid_universe(view)
    f: dict[str, dict[str, float]] = {}
    for s in names:
        row = view.history[s][-1]
        got = facts(row.isin, view.as_of, row.close)
        if got:
            f[s] = got
    return names, f


def _top(scores: Mapping[str, float], n: int = TOP) -> dict[str, float]:
    chosen = sorted(scores, key=lambda s: (-scores[s], s))[:n]
    return dict.fromkeys(chosen, 1.0 / len(chosen)) if chosen else {}


FEATURES = (
    "mom_1",
    "mom_6",
    "mom_12_1",
    "vol_60",
    "turnover",
    "near_high",
    "roe",
    "op_assets",
    "leverage",
    "earnings_yield",
    "book_yield",
)


# --- swing models ---------------------------------------------------------------------------------


def rsi(closes: Sequence[float], n: int = 2) -> float | None:
    if len(closes) < n + 1:
        return None
    gains = losses = 0.0
    for a, b in zip(closes[-n - 1 : -1], closes[-n:], strict=True):
        d = b - a
        gains += max(d, 0.0)
        losses += max(-d, 0.0)
    return 100.0 if losses == 0 else 100 - 100 / (1 + gains / losses)


def _sma(closes: Sequence[float], n: int) -> float | None:
    return sum(closes[-n:]) / n if len(closes) >= n else None


class TrendPullback(Strategy):
    """RSI(2) under 10 in a stock above its rising 200-day trend; out above 70 or after 10 sessions (H-0034).

    Decided weekly (operator, 2026-11-04: swing trades rebalance weekly).
    Stateless: at each weekly decision a stock is held when an entry fired
    within the last `hold` sessions and RSI(2) has not closed above 70 since.
    """

    rebalance_every = 5
    lookback = 230
    hold = 10

    def __init__(self) -> None:
        self.name = "screen_trend_pullback"
        self.hold_unchanged = True

    @staticmethod
    def entry(c: Sequence[float]) -> bool:
        s50, s200 = _sma(c, 50), _sma(c, 200)
        r = rsi(c)
        return bool(s50 and s200 and r is not None and c[-1] > s200 and s50 > s200 and r < 10)

    def held(self, rows: Sequence[PanelRow]) -> bool:
        c = [r.close for r in rows]
        for back in range(self.hold):
            end = len(c) - back
            if end < 201 or not self.entry(c[:end]):
                continue
            after = [rsi(c[: end + j]) for j in range(1, back + 1)]
            return not any(x is not None and x > 70 for x in after)
        return False

    def target_weights(self, view: MarketView) -> dict[str, float]:
        held = [s for s in liquid_universe(view) if self.held(view.history[s])]
        return dict.fromkeys(held, 1.0 / max(len(held), SLOTS)) if held else {}


class BreakoutVolume(Strategy):
    """A close at a new 52-week high on twice the usual volume; held while it is within 20 sessions (H-0035).

    Decided weekly, like every swing model here.
    """

    rebalance_every = 5
    lookback = YEAR + 30
    hold = 20

    def __init__(self) -> None:
        self.name = "screen_52w_breakout"
        self.hold_unchanged = True

    @staticmethod
    def breakout(rows: Sequence[PanelRow], i: int) -> bool:
        if i < YEAR:
            return False
        prior = max(r.close for r in rows[i - YEAR + 1 : i])
        vols = sorted(r.volume for r in rows[i - 50 : i])
        usual = vols[len(vols) // 2]
        return rows[i].close >= prior and usual > 0 and rows[i].volume >= 2 * usual

    def target_weights(self, view: MarketView) -> dict[str, float]:
        held = []
        for s in liquid_universe(view):
            rows = view.history[s]
            n = len(rows)
            if any(self.breakout(rows, i) for i in range(max(0, n - self.hold), n)):
                held.append(s)
        return dict.fromkeys(held, 1.0 / max(len(held), SLOTS)) if held else {}


# --- top-down models (research 182) ---------------------------------------------------------------

SECTOR_CAP = 6


def _capped(
    scores: Mapping[str, float], sector_of: Mapping[str, str], n: int = TOP, cap: int = SECTOR_CAP
) -> dict[str, float]:
    """The best `n` by score, at most `cap` from one sector; equal weights."""
    chosen: list[str] = []
    count: dict[str, int] = {}
    for s in sorted(scores, key=lambda s: (-scores[s], s)):
        sec = sector_of.get(s, "")
        if count.get(sec, 0) >= cap:
            continue
        chosen.append(s)
        count[sec] = count.get(sec, 0) + 1
        if len(chosen) == n:
            break
    return dict.fromkeys(chosen, 1.0 / len(chosen)) if chosen else {}


class TopSectorsOnly(Strategy):
    """Another strategy's targets, kept only for stocks in the top 5 sectors (weights unchanged)."""

    def __init__(self, name: str, inner: Strategy) -> None:
        self.name = name
        self.inner = inner
        self.rebalance_every = int(getattr(inner, "rebalance_every", 1))
        self.lookback = max(int(inner.lookback or 0), topdown.FORMATION + 10)
        self.hold_unchanged = getattr(inner, "hold_unchanged", False)

    def target_weights(self, view: MarketView) -> dict[str, float]:
        got = self.inner.target_weights(view)
        if not got:
            return {}
        rk = topdown.rank(view, liquid_universe(view))
        return {s: w for s, w in got.items() if rk.in_top_sectors(s)}


# --- blends (ADR-137) ----------------------------------------------------------------------------


class Blend(Strategy):
    """Fixed-weight blend of registered strategies, decided together at one cadence.

    Each part decides on the view narrowed to its own lookback, as the engine
    would give it; the blend's weights are the parts' long weights times their
    shares, summed. The shares are fixed when the blend is declared, never fitted.
    """

    def __init__(self, name: str, parts: Sequence[tuple[str, float]], rebalance_every: int) -> None:
        from eulerlab.strategies.daily.published import BUILDERS

        self.name = name
        self.parts = [(BUILDERS[pid](), share) for pid, share in parts]
        self.rebalance_every = rebalance_every
        self.lookback = max(int(getattr(s, "lookback", 0) or 0) for s, _ in self.parts)

    def target_weights(self, view: MarketView) -> dict[str, float]:
        from eulerlab.backtest.strategy import decide

        total: dict[str, float] = {}
        for strategy, share in self.parts:
            lookback = int(getattr(strategy, "lookback", 0) or 0)
            narrowed = MarketView(
                as_of=view.as_of,
                history={s: h[-lookback:] if lookback else h for s, h in view.history.items()},
            )
            longs, _ = decide(strategy, narrowed)
            for symbol, weight in longs.items():
                total[symbol] = total.get(symbol, 0.0) + share * weight
        return total


BLENDS: tuple[tuple[str, str, str, tuple[tuple[str, float], ...], int], ...] = (
    (
        "screen_long_blend",
        "Long-term blend: quality momentum 70%, tree ranker 30%",
        LONG,
        (("screen_quality_momentum", 0.7), ("screen_tree_ranker", 0.3)),
        MONTH,
    ),
    (
        "screen_swing_mom_weinstein",
        "Swing A: volatility-adjusted momentum + Weinstein stage 2",
        SWING,
        (("india_sharpe_momentum", 0.5), ("nse_github_weinstein_stage2", 0.5)),
        5,
    ),
    (
        "screen_swing_breakout_weinstein",
        "Swing B: 52-week breakout + Weinstein stage 2",
        SWING,
        (("screen_52w_breakout", 0.5), ("nse_github_weinstein_stage2", 0.5)),
        5,
    ),
    (
        "screen_swing_three",
        "Swing C: momentum, breakout and Weinstein, a third each",
        SWING,
        (
            ("india_sharpe_momentum", 1 / 3),
            ("screen_52w_breakout", 1 / 3),
            ("nse_github_weinstein_stage2", 1 / 3),
        ),
        5,
    ),
)


def _blend_builder(bid: str, parts: tuple[tuple[str, float], ...], every: int) -> Any:
    return lambda: Blend(bid, parts, every)


LONG_LOOKBACK = 3 * YEAR + 30

_TOPDOWN_FUNNEL = (
    "Sectors and industries: equal-weighted 126-session return of their liquid members "
    "(3 or more); top 5 sectors, industries above the median (backtest.topdown).",
    "Sector tags are today's, applied backwards (A-128).",
)
