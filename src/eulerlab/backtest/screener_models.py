"""Models for the stock screener: long-term and swing, each one strategy on the common engine (ADR-136).

Built on what already works here, as the operator asked: the long-term models
start from Sharpe momentum and 12-1 momentum (the best stored daily strategies,
HISTORY #44) and add what research 150 says momentum lacks in India: quality
(Jacob, Pradeep and Varma 2022), value (Asness, Moskowitz and Pedersen 2013),
the F-score (Piotroski 2000), and a tree model over all of them (Gu, Kelly and
Xiu 2020). The swing models add a trend filter to the RSI-2 dip (Connors) and
volume to the 52-week high (George and Hwang 2004). Long-term models rebalance
monthly (21 sessions, Piotroski quarterly as its paper does) and swing models
weekly (5 sessions), as the operator set. All settings were fixed on
2026-11-04 before any result was seen; each configuration is one hypothesis
(H-0030 to H-0035).

Every model trades only the 250 most-traded stocks as of each date
(`india_papers.liquid_universe`) and decides on the view the engine hands it,
which holds only the past: fundamentals enter through
`fundamentals.annual.known`, i.e. 90 days after each year end (A-107), with
per-share values put into the decision date's units by `units`.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from collections.abc import Mapping, Sequence
from datetime import date
from functools import cache
from statistics import median
from typing import Any

from eulerlab.backtest.event_driven import FAR_FUTURE
from eulerlab.backtest.india_papers import (
    MONTH,
    YEAR,
    PaperStrategy,
    liquid_universe,
    momentum,
    sharpe_momentum_over,
)
from eulerlab.backtest.strategy import MarketView, Strategy
from eulerlab.features.panel import PanelRow
from eulerlab.fundamentals import annual

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


# --- long-term models -----------------------------------------------------------------------------


class QualityMomentum(Strategy):
    """Sharpe momentum among the better half on quality (H-0030)."""

    rebalance_every = MONTH
    lookback = YEAR + 10

    def __init__(self) -> None:
        self.name = "screen_quality_momentum"
        self.score = sharpe_momentum_over(YEAR)

    def target_weights(self, view: MarketView) -> dict[str, float]:
        _, f = _universe_facts(view)
        q = quality(f)
        if len(q) < 40:
            return {}
        good = [s for s in q if q[s] >= median(q.values())]
        scores = {s: v for s in good if (v := self.score(view.history[s])) is not None}
        return _top(scores)


class ValueMomentumQuality(Strategy):
    """Equal blend of value, quality and 12-1 momentum ranks (H-0031)."""

    rebalance_every = MONTH
    lookback = YEAR + 10

    def __init__(self) -> None:
        self.name = "screen_value_momentum_quality"
        self.mom = momentum(YEAR, MONTH)

    def target_weights(self, view: MarketView) -> dict[str, float]:
        _, f = _universe_facts(view)
        if len(f) < 40:
            return {}
        value = _mean_of(
            [
                _z({s: v["earnings_yield"] for s, v in f.items() if "earnings_yield" in v}),
                _z({s: v["book_yield"] for s, v in f.items() if "book_yield" in v}),
            ],
            f,
        )
        mom = _z({s: m for s in f if (m := self.mom(view.history[s])) is not None})
        blend = _mean_of([value, quality(f), mom], f)
        return _top(blend)


class Piotroski(Strategy):
    """Cheapest 30% on book yield with an F-score of 6 or more of 8 (H-0032)."""

    rebalance_every = 3 * MONTH
    lookback = 70

    def __init__(self) -> None:
        self.name = "screen_piotroski"

    def target_weights(self, view: MarketView) -> dict[str, float]:
        _, f = _universe_facts(view)
        cheap = sorted(
            (s for s in f if "book_yield" in f[s] and f[s]["book_yield"] > 0),
            key=lambda s: (-f[s]["book_yield"], s),
        )
        cheap = cheap[: max(1, round(len(cheap) * 0.3))]
        held = [s for s in cheap if f[s].get("fscore", 0) >= 6]
        if not held:
            return {}
        held = held[: TOP + 10]
        return dict.fromkeys(held, 1.0 / len(held))


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


def features(rows: Sequence[PanelRow], f: Mapping[str, float] | None) -> list[float] | None:
    """The tree model's inputs at the last row; NaN where a value is missing."""
    if len(rows) < YEAR + 1:
        return None
    c = [r.close for r in rows]
    rets = [b / a - 1 for a, b in zip(c[-61:-1], c[-60:], strict=True) if a > 0]
    vol = (sum(x * x for x in rets) / len(rets)) ** 0.5 if rets else math.nan
    turn = sorted(r.turnover for r in rows[-60:])
    hi = max(c[-YEAR:])
    nan = math.nan
    g = f or {}
    return [
        c[-1] / c[-1 - MONTH] - 1,
        c[-1] / c[-1 - 6 * MONTH] - 1,
        c[-1 - MONTH] / c[-1 - YEAR] - 1,
        vol,
        math.log(turn[len(turn) // 2] + 1),
        c[-1] / hi if hi > 0 else nan,
        g.get("roe", nan),
        g.get("op_assets", nan),
        g.get("leverage", nan),
        g.get("earnings_yield", nan),
        g.get("book_yield", nan),
    ]


class TreeRanker(Strategy):
    """Gradient-boosted trees on price and fundamental features, refit each month (H-0033).

    Pure: the training set is built from the view alone. At each decision date
    the model learns, on the previous 24 month-ends in the view, the
    cross-sectional rank of each liquid stock's next-month return from its
    features at that month-end, then ranks today's stocks. Fixed settings,
    `random_state=0`.
    """

    rebalance_every = MONTH
    lookback = 3 * YEAR + 30
    TRAIN_MONTHS = 24

    def __init__(self) -> None:
        self.name = "screen_tree_ranker"

    def _snapshot(self, view: MarketView, end: int) -> dict[str, tuple[list[float], PanelRow]]:
        """Features for each liquid stock using its rows up to `end` sessions before the view's last."""
        out: dict[str, tuple[list[float], PanelRow]] = {}
        for s in liquid_universe(view):
            rows = view.history[s]
            past = rows[: len(rows) - end] if end else rows
            if len(past) < YEAR + 1:
                continue
            last = past[-1]
            x = features(past, facts(last.isin, last.day, last.close))
            if x is not None:
                out[s] = (x, last)
        return out

    def target_weights(self, view: MarketView) -> dict[str, float]:
        try:
            from sklearn.ensemble import HistGradientBoostingRegressor
        except ImportError:
            return {}
        X: list[list[float]] = []
        y: list[float] = []
        for k in range(1, self.TRAIN_MONTHS + 1):
            then, after = self._snapshot(view, k * MONTH), self._snapshot(view, (k - 1) * MONTH)
            fwd = {
                s: after[s][1].close / then[s][1].close - 1
                for s in then
                if s in after and then[s][1].close > 0
            }
            ranks = _z(fwd)
            for s, r in ranks.items():
                X.append(then[s][0])
                y.append(r)
        now = self._snapshot(view, 0)
        if len(y) < 1000 or len(now) < 40:
            return {}
        model = HistGradientBoostingRegressor(
            max_iter=200, learning_rate=0.05, max_leaf_nodes=15, min_samples_leaf=50, random_state=0
        )
        model.fit(X, y)
        names = sorted(now)
        pred = model.predict([now[s][0] for s in names])
        return _top({s: float(p) for s, p in zip(names, pred, strict=True)})


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


# --- blends (ADR-137) ----------------------------------------------------------------------------


class Blend(Strategy):
    """Fixed-weight blend of registered strategies, decided together at one cadence.

    Each part decides on the view narrowed to its own lookback, as the engine
    would give it; the blend's weights are the parts' long weights times their
    shares, summed. The shares are fixed when the blend is declared, never fitted.
    """

    def __init__(self, name: str, parts: Sequence[tuple[str, float]], rebalance_every: int) -> None:
        from eulerlab.backtest.published import BUILDERS

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


class Consensus(Strategy):
    """Hold, equal-weighted, the stocks at least `min_votes` of the parts pick (research 152)."""

    def __init__(
        self, name: str, parts: Sequence[str], min_votes: int, rebalance_every: int
    ) -> None:
        from eulerlab.backtest.published import BUILDERS

        self.name = name
        self.parts = [(pid, BUILDERS[pid]()) for pid in parts]
        self.min_votes = min_votes
        self.rebalance_every = rebalance_every
        self.lookback = max(int(getattr(s, "lookback", 0) or 0) for _, s in self.parts)

    def picks(self, view: MarketView) -> dict[str, list[str]]:
        """Each part's picks on this view, by part id."""
        from eulerlab.backtest.strategy import decide

        out: dict[str, list[str]] = {}
        for pid, strategy in self.parts:
            lookback = int(getattr(strategy, "lookback", 0) or 0)
            narrowed = MarketView(
                as_of=view.as_of,
                history={s: h[-lookback:] if lookback else h for s, h in view.history.items()},
            )
            longs, _ = decide(strategy, narrowed)
            out[pid] = sorted(s for s, w in longs.items() if w > 0)
        return out

    def votes(self, view: MarketView) -> dict[str, int]:
        counts: dict[str, int] = {}
        for chosen in self.picks(view).values():
            for s in chosen:
                counts[s] = counts.get(s, 0) + 1
        return counts

    def target_weights(self, view: MarketView) -> dict[str, float]:
        held = sorted(s for s, n in self.votes(view).items() if n >= self.min_votes)
        return dict.fromkeys(held, 1.0 / len(held)) if held else {}


CONSENSUS_PARTS = (
    "nse_github_stocks_on_the_move",
    "india_sharpe_momentum",
    "nse_github_weinstein_stage2",
    "screen_quality_momentum",
    "india_physical_momentum",
)


BLENDS: tuple[tuple[str, str, str, tuple[tuple[str, float], ...], int], ...] = (
    (
        "screen_long_blend",
        "Long-term blend: quality momentum 70%, tree ranker 30%",
        LONG,
        (("screen_quality_momentum", 0.7), ("screen_tree_ranker", 0.3)),
        MONTH,
    ),
    (
        "screen_stock_mix",
        "Stock mix: momentum, low volatility, value and quality, a third each",
        LONG,
        (
            ("nse_github_stocks_on_the_move", 1 / 3),
            ("india_low_tvol36", 1 / 3),
            ("screen_value_momentum_quality", 1 / 3),
        ),
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


# --- the registry ---------------------------------------------------------------------------------


SPECS: tuple[tuple[PaperStrategy, str], ...] = (
    (
        PaperStrategy(
            id="screen_quality_momentum",
            title="Quality momentum",
            paper="jacob-pradeep-varma-2022-quality-india",
            citation="Jacob, Pradeep and Varma (2022); Sharpe momentum from this platform",
            summary="Sharpe momentum over a year, among the better half of the liquid 250 on quality; top 20, monthly.",
            logic=(
                "Quality: mean rank of ROE, operating profit over assets, low leverage, payout.",
                "Keep the better half; rank by 12-month return over volatility.",
                "Hold the top 20 equally; rebalance every 21 sessions.",
            ),
            lookback=YEAR + 10,
            build=QualityMomentum,
        ),
        LONG,
    ),
    (
        PaperStrategy(
            id="screen_value_momentum_quality",
            title="Value, momentum and quality",
            paper="asness-moskowitz-pedersen-2013-value-momentum-everywhere",
            citation="Asness, Moskowitz and Pedersen (2013); Novy-Marx (2013)",
            summary="Equal blend of value, quality and 12-1 momentum ranks; top 20, monthly.",
            logic=(
                "Value: mean rank of earnings yield and book yield.",
                "Blend with quality and 12-1 month momentum ranks, equally.",
                "Hold the top 20 equally; rebalance every 21 sessions.",
            ),
            lookback=YEAR + 10,
            build=ValueMomentumQuality,
        ),
        LONG,
    ),
    (
        PaperStrategy(
            id="screen_piotroski",
            title="Piotroski value",
            paper="piotroski-2000-fscore",
            citation="Piotroski (2000)",
            summary="The cheapest 30% on book yield with an F-score of 6 or more of 8; quarterly.",
            logic=(
                "Book yield from the last annual statement known 90 days after the year end.",
                "F-score from 8 of Piotroski's 9 signals.",
                "Hold up to 30 equally; rebalance every 63 sessions.",
            ),
            lookback=70,
            build=Piotroski,
        ),
        LONG,
    ),
    (
        PaperStrategy(
            id="screen_tree_ranker",
            title="Tree ranker",
            paper="gu-kelly-xiu-2020-ml-asset-pricing",
            citation="Gu, Kelly and Xiu (2020)",
            summary="Gradient-boosted trees on 11 price and fundamental features, refit monthly on 24 months; top 20.",
            logic=(
                "Learn next-month return rank from features at each of the last 24 month-ends.",
                "Rank today's liquid 250; hold the top 20 equally; rebalance every 21 sessions.",
            ),
            lookback=3 * YEAR + 30,
            build=TreeRanker,
        ),
        LONG,
    ),
    (
        PaperStrategy(
            id="screen_trend_pullback",
            title="Trend pullback",
            paper="github-2021-connors-rsi2-bot",
            citation="Connors RSI(2) with a 200-day trend filter",
            summary="Weekly: RSI(2) under 10 above a rising 200-day trend; out above 70 or after 10 sessions.",
            logic=(
                "Close above the 200-day average and the 50-day above the 200-day.",
                "Decided weekly: hold a stock whose RSI(2) closed under 10 in the last 10 sessions",
                "and has not closed above 70 since.",
                "Each position is a tenth of capital, or equal shares when more qualify.",
            ),
            lookback=230,
            build=TrendPullback,
        ),
        SWING,
    ),
    (
        PaperStrategy(
            id="screen_52w_breakout",
            title="52-week breakout",
            paper="george-hwang-2004-52-week-high",
            citation="George and Hwang (2004), with a volume filter",
            summary="Weekly: a close at a new 52-week high on twice the usual volume in the last 20 sessions.",
            logic=(
                "Close at or above the prior 251-session high.",
                "Volume at least twice its 50-session median.",
                "Decided weekly; held while the breakout is within 20 sessions.",
                "A tenth of capital each, or equal shares when more qualify.",
            ),
            lookback=YEAR + 30,
            build=BreakoutVolume,
        ),
        SWING,
    ),
)

LONG_LOOKBACK = 3 * YEAR + 30
SPECS = SPECS + tuple(
    (
        PaperStrategy(
            id=bid,
            title=title,
            paper="gu-kelly-xiu-2020-ml-asset-pricing"
            if kind == LONG
            else "github-2026-trend-radar-minervini",
            citation="Fixed-weight blend of registered strategies (ADR-137)",
            summary=f"{title}; one book, rebalanced every {every} sessions.",
            logic=(
                *(f"{pid}: {share:.0%} of capital" for pid, share in parts),
                f"Rebalanced every {every} sessions; shares fixed, not fitted.",
            ),
            lookback=LONG_LOOKBACK,
            build=_blend_builder(bid, parts, every),
        ),
        kind,
    )
    for bid, title, kind, parts, every in BLENDS
)

SPECS = (
    *SPECS,
    (
        PaperStrategy(
            id="screen_consensus_3of5",
            title="Consensus: stocks 3 of the top 5 long-term models pick",
            paper="jacob-pradeep-varma-2022-quality-india",
            citation="Consensus of five stored strategies (research 152)",
            summary="Every 21 sessions, hold equally the stocks that at least 3 of the top 5 long-term models pick.",
            logic=(
                *(f"Part: {pid}" for pid in CONSENSUS_PARTS),
                "A stock is held when 3 or more parts pick it; equal weights; none means cash.",
                "Rebalanced every 21 sessions.",
            ),
            lookback=LONG_LOOKBACK,
            build=lambda: Consensus("screen_consensus_3of5", CONSENSUS_PARTS, 3, MONTH),
        ),
        LONG,
    ),
)

STRATEGIES = tuple(s for s, _ in SPECS)
KIND = {s.id: k for s, k in SPECS}
BY_ID = {s.id: s for s in STRATEGIES}
BUILDERS = {s.id: s.build for s in STRATEGIES}
