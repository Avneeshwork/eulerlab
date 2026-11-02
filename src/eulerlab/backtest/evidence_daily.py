"""Four momentum and reversal refinements with published out-of-sample evidence.

Research 113, batch 3. Chosen because each has been replicated outside the US
and in emerging markets, unlike the textbook chart rules of batches 1 and 2:

- Frog-in-the-pan momentum: Da, Gurun & Warachka (2014), RFS 27(7); confirmed
  across developed and emerging markets by Goyal, Jegadeesh & Subrahmanyam
  (Review of Finance). ID as coded in abeer555/Trend-Radar `frog_in_pan.py`.
- Residual momentum: Blitz, Huij & Martens (2011), JEF 18(3); idiosyncratic
  momentum priced across developed and emerging markets in Blitz, Hanauer &
  Vidojevic (2020).
- Volatility-scaled momentum: Barroso & Santa-Clara (2015), JFE 116(1).
- Short-term residual reversal: Blitz, Huij, Lansdorp & Verbeek (2013), JFM 16(3).

Adaptations, all stated on the cards and in research 113: long only (no
Indian short leg overnight); the point-in-time 250 most-traded stocks
(`india_papers.liquid_universe`); "months" are 21 sessions counted back from
the decision; and the residual models use the market alone (NIFTYBEES), since
no point-in-time Indian size and value factor returns are held here.
"""

from __future__ import annotations

import functools
import math
import statistics
from collections.abc import Callable, Sequence
from datetime import date
from itertools import pairwise

from eulerlab.backtest.india_papers import (
    INDEX_ETF,
    MONTH,
    YEAR,
    PaperStrategy,
    liquid_universe,
)
from eulerlab.backtest.strategy import MarketView, Strategy
from eulerlab.features.panel import PanelRow

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


def information_discreteness(rows: Sequence[PanelRow]) -> float | None:
    """sign(12-1 return) x (% negative days - % positive days), same window."""
    past = momentum_12_1(rows)
    if past is None:
        return None
    window = [r.close for r in rows[-1 - YEAR : len(rows) - MONTH]]
    moves = [b / a - 1.0 for a, b in pairwise(window) if a > 0]
    if len(moves) < 100:
        return None
    up = sum(1 for m in moves if m > 0) / len(moves)
    down = sum(1 for m in moves if m < 0) / len(moves)
    return math.copysign(1.0, past) * (down - up) if past else 0.0


def _equal(chosen: Sequence[str]) -> dict[str, float]:
    return dict.fromkeys(chosen, 1.0 / len(chosen)) if chosen else {}


class FrogInThePan(Strategy):
    """The 30% best 12-1 performers, then the `HOLD` with the most continuous gains."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.rebalance_every = MONTH
        self.lookback = YEAR + 10

    def target_weights(self, view: MarketView) -> dict[str, float]:
        scored = []
        for symbol in liquid_universe(view):
            rows = view.history[symbol]
            past, discrete = momentum_12_1(rows), information_discreteness(rows)
            if past is not None and discrete is not None:
                scored.append((past, discrete, symbol))
        if len(scored) < 3 * HOLD:
            return {}
        scored.sort(key=lambda x: (-x[0], x[2]))
        winners = scored[: max(HOLD, round(0.3 * len(scored)))]
        winners.sort(key=lambda x: (x[1], x[2]))
        return _equal([s for _, _, s in winners[:HOLD]])


class ResidualMomentum(Strategy):
    """Rank on months t-12..t-2 of 36-month market-model residuals, over their s.d."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.rebalance_every = MONTH
        self.lookback = 36 * MONTH + 10

    def target_weights(self, view: MarketView) -> dict[str, float]:
        market = monthly_returns(view.history.get(INDEX_ETF) or [], 36)
        if market is None:
            return {}
        scored = []
        for symbol in liquid_universe(view):
            stock = monthly_returns(view.history[symbol], 36)
            found = residuals(stock, market) if stock else None
            if not found:
                continue
            formation = found[-12:-1]
            spread = statistics.stdev(formation)
            if spread > 0:
                scored.append((sum(formation) / spread, symbol))
        if len(scored) < 3 * HOLD:
            return {}
        scored.sort(key=lambda x: (-x[0], x[1]))
        return _equal([s for _, s in scored[:HOLD]])


class ScaledMomentum(Strategy):
    """The `HOLD` best 12-1 performers, exposure scaled by long-run over 6-month vol.

    Long only, so the paper's scaled long-short portfolio becomes a scaled long
    book with the rest in cash. The target is the selection's own three-year
    volatility rather than a chosen number, so nothing here is tuned; the
    scale is capped at 1 (no leverage).
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self.rebalance_every = MONTH
        self.lookback = 3 * YEAR + 10

    def target_weights(self, view: MarketView) -> dict[str, float]:
        scored = []
        for symbol in liquid_universe(view):
            past = momentum_12_1(view.history[symbol])
            if past is not None:
                scored.append((past, symbol))
        if len(scored) < 3 * HOLD:
            return {}
        scored.sort(key=lambda x: (-x[0], x[1]))
        chosen = [s for _, s in scored[:HOLD]]
        book = _book_returns(view, chosen, 3 * YEAR)
        if len(book) < YEAR:
            return {}
        recent, long_run = statistics.pstdev(book[-126:]), statistics.pstdev(book)
        scale = min(1.0, long_run / recent) if recent > 0 else 1.0
        return {s: scale / len(chosen) for s in chosen}


def _book_returns(view: MarketView, chosen: Sequence[str], days: int) -> list[float]:
    """Daily returns of an equal-weight book of `chosen`, over the last `days`."""
    by_day: dict[object, list[float]] = {}
    for symbol in chosen:
        rows = view.history[symbol][-days - 1 :]
        for a, b in pairwise(rows):
            if a.close > 0:
                by_day.setdefault(b.day, []).append(b.close / a.close - 1.0)
    return [statistics.fmean(v) for _, v in sorted(by_day.items())]


class ResidualReversal(Strategy):
    """Buy the `HOLD` stocks whose last month's residual, over its 36-month s.d., is lowest."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.rebalance_every = MONTH
        self.lookback = 37 * MONTH + 10

    def target_weights(self, view: MarketView) -> dict[str, float]:
        market = monthly_returns(view.history.get(INDEX_ETF) or [], 37)
        if market is None:
            return {}
        scored = []
        for symbol in liquid_universe(view):
            stock = monthly_returns(view.history[symbol], 37)
            found = residuals(stock, market) if stock else None
            if not found:
                continue
            spread = statistics.stdev(found[:-1])
            if spread > 0:
                scored.append((found[-1] / spread, symbol))
        if len(scored) < 3 * HOLD:
            return {}
        scored.sort(key=lambda x: (x[0], x[1]))
        return _equal([s for _, s in scored[:HOLD]])


# --- batch 4: moving-average distance, high-volume premium, industry momentum ------


def ma_distance(rows: Sequence[PanelRow]) -> float | None:
    """Avramov, Kaplanski & Subrahmanyam: the 21-day over the 200-day average close."""
    if len(rows) < 200:
        return None
    closes = [r.close for r in rows[-200:]]
    long_run = statistics.fmean(closes)
    return statistics.fmean(closes[-21:]) / long_run if long_run > 0 else None


class MovingAverageDistance(Strategy):
    """Each month, the `hold` stocks with the highest MA(21) / MA(200)."""

    def __init__(self, name: str, *, hold: int = HOLD) -> None:
        self.name = name
        self.hold = hold
        self.rebalance_every = MONTH
        self.lookback = 210

    def target_weights(self, view: MarketView) -> dict[str, float]:
        scored = []
        for symbol in liquid_universe(view):
            distance = ma_distance(view.history[symbol])
            if distance is not None:
                scored.append((distance, symbol))
        if len(scored) < 3 * self.hold:
            return {}
        scored.sort(key=lambda x: (-x[0], x[1]))
        return _equal([s for _, s in scored[: self.hold]])


WEEK = 5
REFERENCE_WEEKS = 10
HOLD_WEEKS = 4


def high_volume_week(rows: Sequence[PanelRow], weeks_ago: int) -> bool:
    """Kaniel, Ozoguz & Starks: the week's volume is the highest of itself and the
    ten weeks before it (top decile of eleven). Rupee turnover, not shares, so a
    split cannot look like a volume spike."""
    end = len(rows) - weeks_ago * WEEK
    start = end - (REFERENCE_WEEKS + 1) * WEEK
    if start < 0:
        return False
    weekly = [
        sum(r.turnover for r in rows[start + k * WEEK : start + (k + 1) * WEEK])
        for k in range(REFERENCE_WEEKS + 1)
    ]
    return weekly[-1] > 0 and weekly[-1] > max(weekly[:-1])


class HighVolumePremium(Strategy):
    """Hold a stock for four weeks after a week of unusually high volume.

    Weekly decisions, up to `HOLD` names at 1/`HOLD` each (an equal share when
    more qualify). Gervais, Kaniel & Mingelgrin (2001) measured the premium
    over the following weeks; four is the month the house holds for.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self.rebalance_every = WEEK
        self.lookback = (REFERENCE_WEEKS + HOLD_WEEKS + 2) * WEEK + 60
        self.hold_unchanged = True

    def target_weights(self, view: MarketView) -> dict[str, float]:
        # Fixed 1/HOLD weights, the earliest-flagged kept when more qualify: an
        # equal share of every flagged stock re-sized them all each week
        # (research 113, 2026-10-18).
        flagged: list[tuple[int, str]] = []
        for symbol in liquid_universe(view):
            weeks = [w for w in range(HOLD_WEEKS) if high_volume_week(view.history[symbol], w)]
            if weeks:
                flagged.append((max(weeks), symbol))
        flagged.sort(key=lambda x: (-x[0], x[1]))
        return {s: 1.0 / HOLD for _, s in flagged[:HOLD]}


def industries() -> dict[str, str]:
    """Symbol to industry (level 2 of NSE's classification), as it stands today.

    ASSUMPTION: A-061 — today's industry stands for the past; companies rarely
    change industry, but a few have, and the backtest cannot see when.
    """
    from eulerlab.features import company

    return {symbol: c.industry for symbol, c in company.load_digest().items() if c.industry}


class IndustryMomentum(Strategy):
    """Each month, the liquid members of the three industries with the best
    six-month equal-weight return (Moskowitz & Grinblatt 1999). Industries
    need three liquid members to be ranked."""

    def __init__(self, name: str, *, top: int = 3, members: int = 3) -> None:
        self.name = name
        self.top = top
        self.members = members
        self.rebalance_every = MONTH
        self.lookback = 6 * MONTH + 10
        self._industries: dict[str, str] | None = None

    def target_weights(self, view: MarketView) -> dict[str, float]:
        if self._industries is None:
            self._industries = industries()
        groups: dict[str, list[tuple[str, float]]] = {}
        for symbol in liquid_universe(view):
            rows = view.history[symbol]
            industry = self._industries.get(symbol)
            if industry is None or len(rows) <= 6 * MONTH or rows[-1 - 6 * MONTH].close <= 0:
                continue
            past = rows[-1].close / rows[-1 - 6 * MONTH].close - 1.0
            groups.setdefault(industry, []).append((symbol, past))
        ranked = sorted(
            (
                (statistics.fmean(p for _, p in members), industry)
                for industry, members in groups.items()
                if len(members) >= self.members
            ),
            key=lambda x: (-x[0], x[1]),
        )
        chosen = [s for _, industry in ranked[: self.top] for s, _ in groups[industry]]
        return _equal(sorted(chosen))


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


class ConservativeFormula(Strategy):
    """Van Vliet & Blitz: the lower-volatility half by 36-month volatility, then
    the average of momentum and payout ranks, top `HOLD`, quarterly.

    Payout is the trailing 12-month dividend yield: buybacks are not held here.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self.rebalance_every = 3 * MONTH
        self.lookback = 36 * MONTH + 10

    def target_weights(self, view: MarketView) -> dict[str, float]:
        candidates: list[tuple[float, str]] = []
        for symbol in liquid_universe(view):
            months = monthly_returns(view.history[symbol], 36)
            if months:
                candidates.append((statistics.stdev(months), symbol))
        if len(candidates) < 3 * HOLD:
            return {}
        candidates.sort()
        calm = [s for _, s in candidates[: len(candidates) // 2]]
        momentum = {s: m for s in calm if (m := momentum_12_1(view.history[s])) is not None}
        payout = {s: dividend_yield(s, view.history[s]) for s in momentum}
        mom_rank, pay_rank = _percentiles(momentum), _percentiles(payout)
        score = sorted(momentum, key=lambda s: (-(mom_rank[s] + pay_rank[s]), s))
        return _equal(score[:HOLD])


def clenow_score(rows: Sequence[PanelRow], days: int = 125) -> float | None:
    """skyte/momentum `momentum`: annualised exponential-regression slope x R^2,
    or None when the close is under its 100-day average or a day moved 15%."""
    if len(rows) < max(days, 100) + 1:
        return None
    closes = [r.close for r in rows[-days:]]
    if min(closes) <= 0 or closes[-1] < statistics.fmean(r.close for r in rows[-100:]):
        return None
    moves = [abs(b / a - 1.0) for a, b in pairwise(closes)]
    if max(moves) > 0.15:
        return None
    logs = [math.log(c) for c in closes]
    xs = list(range(days))
    mean_x, mean_y = statistics.fmean(xs), statistics.fmean(logs)
    sxx = sum((x - mean_x) ** 2 for x in xs)
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, logs, strict=True))
    syy = sum((y - mean_y) ** 2 for y in logs)
    if sxx <= 0 or syy <= 0:
        return None
    slope = sxy / sxx
    r2 = sxy * sxy / (sxx * syy)
    return (math.exp(slope) ** 252 - 1.0) * r2


def _atr20(rows: Sequence[PanelRow]) -> float | None:
    bars = [r.ohlc() for r in rows[-21:]]
    if len(bars) < 21:
        return None
    ranges = [
        max(h - lo, abs(h - prev[3]), abs(lo - prev[3])) for prev, (_, h, lo, _) in pairwise(bars)
    ]
    return statistics.fmean(ranges)


class StocksOnTheMove(Strategy):
    """Clenow's ranking (skyte/momentum), top 25, weekly, weights by inverse ATR.

    The repository sizes each position to risk the same rupees per ATR
    (risk parity); here that becomes weights proportional to close / ATR(20),
    normalised to the whole book. Clenow's book adds an index filter (stop
    buying when the index is under its 200-day average); the repository does
    not, and neither does this.

    Names are listed best score first and the weights are sizes, so a
    deployment too small for all 25 keeps them in score order
    (`ranked_by_order`, ADR-120).
    """

    ranked_by_order = True
    sizing = "strategy"  # inverse ATR is Clenow's own sizing (ADR-122)

    def __init__(self, name: str, *, hold: int = 25, universe: int = 250) -> None:
        self.name = name
        self.hold = hold
        self.universe = universe
        self.rebalance_every = WEEK
        self.lookback = 135

    def target_weights(self, view: MarketView) -> dict[str, float]:
        scored = []
        for symbol in liquid_universe(view, self.universe):
            rows = view.history[symbol]
            score = clenow_score(rows)
            atr = _atr20(rows) if score is not None else None
            if score is not None and atr and atr > 0:
                scored.append((score, symbol, rows[-1].close / atr))
        if len(scored) < self.hold:
            return {}
        scored.sort(key=lambda x: (-x[0], x[1]))
        chosen = scored[: self.hold]
        total = sum(w for _, _, w in chosen)
        return {s: w / total for _, s, w in chosen}


class AlphaLowVolatility(Strategy):
    """NSE Nifty Alpha Low-Volatility 30: the equal-weight blend of alpha and
    low-volatility percentiles over the last year, top 30, every six months.

    Universe: the 150 most-traded (Nifty 100 + Midcap 50 by size; turnover
    stands in, as market caps are not held). Alpha is Jensen's alpha on daily
    returns against NIFTYBEES with the risk-free rate set to zero (MIBOR is not
    held; a constant rate shifts every alpha by about the same amount). Equal
    weights: the index tilts free-float weights, which are not held.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self.rebalance_every = 6 * MONTH
        self.lookback = YEAR + 10

    def target_weights(self, view: MarketView) -> dict[str, float]:
        market_rows = view.history.get(INDEX_ETF) or []
        market = {
            b.day: b.close / a.close - 1.0
            for a, b in pairwise(market_rows[-YEAR - 1 :])
            if a.close > 0
        }
        alpha: dict[str, float] = {}
        calm: dict[str, float] = {}
        for symbol in liquid_universe(view, 150):
            rows = view.history[symbol][-YEAR - 1 :]
            pairs = [
                (b.close / a.close - 1.0, market[b.day])
                for a, b in pairwise(rows)
                if a.close > 0 and b.day in market
            ]
            if len(pairs) < 200:
                continue
            stock, index = [p[0] for p in pairs], [p[1] for p in pairs]
            var_m = statistics.pvariance(index)
            if var_m <= 0:
                continue
            mean_s, mean_m = statistics.fmean(stock), statistics.fmean(index)
            beta = sum((x - mean_s) * (y - mean_m) for x, y in pairs) / (len(pairs) * var_m)
            alpha[symbol] = mean_s - beta * mean_m
            calm[symbol] = -statistics.pstdev(stock)
        if len(alpha) < 2 * HOLD:
            return {}
        a_rank, v_rank = _percentiles(alpha), _percentiles(calm)
        ordered = sorted(alpha, key=lambda s: (-(a_rank[s] + v_rank[s]), s))
        return _equal(ordered[:HOLD])


# --- batch 7: Weinstein Stage 2 with Mansfield relative strength -------------------


def mansfield_rs(rows: Sequence[PanelRow], market: dict[date, float]) -> float | None:
    """abeer555/Trend-Radar `compute_mansfield`: (stock / benchmark) now over the
    same ratio 52 weeks ago, less 1. NIFTYBEES stands in for the Nifty 50."""
    if len(rows) <= YEAR:
        return None
    now, then = rows[-1], rows[-1 - YEAR]
    m_now, m_then = market.get(now.day), market.get(then.day)
    if not m_now or not m_then or then.close <= 0:
        return None
    return (now.close / m_now) / (then.close / m_then) - 1.0


def stage_two(rows: Sequence[PanelRow], rising_over: int = MONTH) -> bool:
    """Weinstein's Stage 2: the close above a rising 30-week (150-day) average."""
    if len(rows) < 150 + rising_over:
        return False
    closes = [r.close for r in rows]
    now = statistics.fmean(closes[-150:])
    before = statistics.fmean(closes[-150 - rising_over : -rising_over])
    return closes[-1] > now > before


class WeinsteinStageTwo(Strategy):
    """Weekly, the `hold` Stage-2 stocks with the highest positive Mansfield RS.

    Fixed 1/`hold` weights. "Rising" is the average over a month ago, as
    Trend-Radar's stage test compares the 30-week average with its earlier
    value; the exact look-back there was not read.
    """

    def __init__(self, name: str, *, hold: int = 20) -> None:
        self.name = name
        self.hold = hold
        self.rebalance_every = WEEK
        self.lookback = YEAR + 30
        self.hold_unchanged = True

    def target_weights(self, view: MarketView) -> dict[str, float]:
        market = {r.day: r.close for r in view.history.get(INDEX_ETF) or []}
        scored = []
        for symbol in liquid_universe(view):
            rows = view.history[symbol]
            rs = mansfield_rs(rows, market)
            if rs is not None and rs > 0 and stage_two(rows):
                scored.append((rs, symbol))
        scored.sort(key=lambda x: (-x[0], x[1]))
        return {s: 1.0 / self.hold for _, s in scored[: self.hold]}


# --- batch 8: Halloween, volatility targeting, dividend yield ---------------------

SAFE = "LIQUIDBEES"
WINTER = (11, 12, 1, 2, 3, 4)


class Halloween(Strategy):
    """Jacobsen & Zhang (2018): NIFTYBEES from November to April, LIQUIDBEES from
    May to October. Decided at each close: the engine fills at the next close,
    so the switch lands on the first session of the new season."""

    rebalance_every = 1

    def __init__(self, name: str) -> None:
        self.name = name
        self.lookback = 2
        # The target is the same 100% every day within a season; without this
        # the engine would trim the position to equity every day.
        self.hold_unchanged = True

    def target_weights(self, view: MarketView) -> dict[str, float]:
        return {INDEX_ETF if view.as_of.month in WINTER else SAFE: 1.0}


class VolatilityTarget(Strategy):
    """NIFTYBEES scaled by its 3-year over its 1-month daily volatility, capped
    at 1, the rest in LIQUIDBEES; monthly. The target is the index's own
    long-run volatility, so no number is chosen (Harvey et al. 2018 target a
    fixed level)."""

    sizing = "strategy"  # the index/cash split is the strategy (ADR-122)

    def __init__(self, name: str) -> None:
        self.name = name
        self.rebalance_every = MONTH
        self.lookback = 3 * YEAR + 5

    def target_weights(self, view: MarketView) -> dict[str, float]:
        rows = view.history.get(INDEX_ETF) or []
        closes = [r.close for r in rows]
        moves = [b / a - 1.0 for a, b in pairwise(closes) if a > 0]
        if len(moves) < YEAR:
            return {SAFE: 1.0}
        recent, long_run = statistics.pstdev(moves[-MONTH:]), statistics.pstdev(moves)
        weight = min(1.0, long_run / recent) if recent > 0 else 1.0
        return {INDEX_ETF: weight, SAFE: 1.0 - weight} if weight < 1.0 else {INDEX_ETF: 1.0}


class DividendYield(Strategy):
    """The `hold` highest trailing 12-month dividend yields among the 250
    most-traded, every six months. Yields above 15% are left out: they are
    one-off special dividends or a price that has collapsed, not a yield."""

    def __init__(self, name: str, *, hold: int = HOLD) -> None:
        self.name = name
        self.hold = hold
        self.rebalance_every = 6 * MONTH
        self.lookback = 10

    def target_weights(self, view: MarketView) -> dict[str, float]:
        scored = []
        for symbol in liquid_universe(view):
            found = dividend_yield(symbol, view.history[symbol])
            if 0 < found <= 0.15:
                scored.append((found, symbol))
        scored.sort(key=lambda x: (-x[0], x[1]))
        return _equal([s for _, s in scored[: self.hold]])


STRATEGIES: tuple[PaperStrategy, ...] = (
    PaperStrategy(
        "india_frog_in_the_pan",
        "Frog-in-the-pan momentum, continuous winners (India)",
        "da-gurun-warachka-2014-frog-in-the-pan",
        "Da, Gurun & Warachka (2014), RFS 27(7); Goyal, Jegadeesh & Subrahmanyam, Review of Finance",
        "Of the 30% best 12-1 performers, hold the 30 whose gains came most steadily (lowest information discreteness).",
        (
            "ID = sign(12-1 return) x (% negative days - % positive days) over the same "
            "window; low ID = many small gains, the paper's 'continuous information'.",
            "Monthly, equal weight, point-in-time 250 most-traded stocks. Long only.",
        ),
        YEAR + 10,
        lambda: FrogInThePan("india_frog_in_the_pan"),
    ),
    PaperStrategy(
        "india_residual_momentum",
        "Residual momentum, market-model residuals (India)",
        "blitz-huij-martens-2011-residual-momentum",
        "Blitz, Huij & Martens (2011), JEF 18(3); Blitz, Hanauer & Vidojevic (2020)",
        "Hold the 30 stocks with the highest 12-1 residual return over its volatility, residuals from a 36-month market model.",
        (
            "Monthly returns regressed on NIFTYBEES over 36 months; score = sum of residuals "
            "in months t-12..t-2 over their standard deviation.",
            "The paper uses the three Fama-French factors; only the market is available here. "
            "Monthly, equal weight, point-in-time 250 most-traded.",
        ),
        36 * MONTH + 10,
        lambda: ResidualMomentum("india_residual_momentum"),
    ),
    PaperStrategy(
        "india_scaled_momentum",
        "Volatility-scaled momentum, long only (India)",
        "barroso-santa-clara-2015-momentum-moments",
        "Barroso & Santa-Clara (2015), JFE 116(1)",
        "Hold the 30 best 12-1 performers, cutting exposure when their 6-month volatility runs above its 3-year level.",
        (
            "Scale = 3-year / 6-month (126-day) volatility of the equal-weight selection, "
            "capped at 1; the remainder stays in cash.",
            "The paper scales a long-short portfolio to a target; here the target is the "
            "book's own long-run volatility, so no number is chosen. Monthly.",
        ),
        3 * YEAR + 10,
        lambda: ScaledMomentum("india_scaled_momentum"),
    ),
    PaperStrategy(
        "india_residual_reversal",
        "Short-term residual reversal, losers (India)",
        "blitz-huij-lansdorp-verbeek-2013-residual-reversal",
        "Blitz, Huij, Lansdorp & Verbeek (2013), JFM 16(3)",
        "Buy the 30 stocks whose last month's market-model residual, over its 36-month s.d., is the most negative.",
        (
            "Residuals from 36 months of a market model on NIFTYBEES; the paper uses three "
            "Fama-French factors.",
            "Monthly, equal weight, point-in-time 250 most-traded. Long only: the loser leg.",
        ),
        37 * MONTH + 10,
        lambda: ResidualReversal("india_residual_reversal"),
    ),
    PaperStrategy(
        "india_ma_distance",
        "Moving-average distance, 21 over 200 days (India)",
        "avramov-kaplanski-subrahmanyam-2021-ma-distance",
        "Avramov, Kaplanski & Subrahmanyam (2021), Review of Financial Economics 39(2)",
        "Each month, hold the 30 stocks whose 21-day average is highest relative to their 200-day average.",
        (
            "MAD = MA(21) / MA(200) of the close; the paper buys the top decile and finds "
            "the effect beyond momentum and the 52-week high, also outside the US.",
            "Monthly, equal weight, point-in-time 250 most-traded. Long only.",
        ),
        210,
        lambda: MovingAverageDistance("india_ma_distance"),
    ),
    PaperStrategy(
        "india_high_volume_premium",
        "High-volume return premium, held four weeks (India)",
        "kaniel-ozoguz-starks-2012-high-volume-premium",
        "Kaniel, Ozoguz & Starks (2012), JFE 103(2); Gervais, Kaniel & Mingelgrin (2001), JF 56(3)",
        "Buy stocks whose weekly turnover is the highest of their last eleven weeks; hold four weeks.",
        (
            "A high-volume week: rupee turnover above every one of the ten weeks before it. "
            "Found in 41 countries, developed and emerging, and not a risk or liquidity effect.",
            "Weekly decisions, up to 30 names, point-in-time 250 most-traded. Long only.",
        ),
        (REFERENCE_WEEKS + HOLD_WEEKS + 2) * WEEK + 60,
        lambda: HighVolumePremium("india_high_volume_premium"),
    ),
    PaperStrategy(
        "india_industry_momentum",
        "Industry momentum, top three industries (India)",
        "moskowitz-grinblatt-1999-industry-momentum",
        "Moskowitz & Grinblatt (1999), JF 54(4)",
        "Each month, hold the liquid stocks of the three industries with the best six-month return.",
        (
            "Industries: level 2 of NSE's classification (39 industries) as it stands today, "
            "applied to the past (A-061). An industry needs three liquid members.",
            "Six-month equal-weight industry return, monthly, members equal-weighted. No Indian "
            "test of industry momentum was found; stock momentum in India is well documented.",
        ),
        6 * MONTH + 10,
        lambda: IndustryMomentum("india_industry_momentum"),
    ),
    PaperStrategy(
        "india_conservative_formula",
        "Conservative Formula: low volatility, momentum, dividends (India)",
        "van-vliet-blitz-2018-conservative-formula",
        "Van Vliet & Blitz (2018); India: 'The Conservative Formula: Evidence from India' (SSRN 4163613)",
        "Of the calmer half of stocks, hold the 30 with the best combined momentum and dividend-yield ranks; quarterly.",
        (
            "Calm: below-median 36-month volatility of monthly returns. Then the average "
            "percentile of 12-1 momentum and trailing 12-month dividend yield.",
            "The paper's payout adds buybacks, not held here. Quarterly, equal weight, "
            "point-in-time 250 most-traded. The Indian study reports +12.6% a year over the BSE 100.",
        ),
        36 * MONTH + 10,
        lambda: ConservativeFormula("india_conservative_formula"),
    ),
    PaperStrategy(
        "nse_github_stocks_on_the_move",
        "Clenow's Stocks on the Move, top 25 (GitHub rule)",
        "github-2021-skyte-clenow-momentum",
        "skyte/momentum (GitHub); Clenow (2015), Stocks on the Move",
        "Weekly, hold the 25 stocks with the steepest, smoothest 125-day trend, sized by inverse ATR.",
        (
            "Score: annualised slope of a 125-day regression of log price, times R^2. Out "
            "if under the 100-day average or any day moved more than 15%.",
            "Weights proportional to close / ATR(20), the repository's risk parity. No index "
            "filter, as in the repository. Point-in-time 250 most-traded.",
        ),
        135,
        lambda: StocksOnTheMove("nse_github_stocks_on_the_move"),
    ),
    PaperStrategy(
        "india_alpha_low_volatility_30",
        "Alpha and low volatility, NSE index rules (India)",
        "nse-2020-alpha-low-volatility-30",
        "NSE Indices (2020), Nifty Alpha Low-Volatility 30 whitepaper",
        "Every six months, hold the 30 stocks with the best blend of one-year alpha and low volatility.",
        (
            "Alpha: Jensen's alpha on a year of daily returns against NIFTYBEES (risk-free "
            "set to zero); volatility: a year of daily returns. Equal-weight percentile blend.",
            "Universe: the 150 most-traded (the index uses Nifty 100 + Midcap 50 and F&O "
            "eligibility). Equal weights; the index tilts free-float weights.",
        ),
        YEAR + 10,
        lambda: AlphaLowVolatility("india_alpha_low_volatility_30"),
    ),
    PaperStrategy(
        "nse_github_weinstein_stage2",
        "Weinstein Stage 2 with Mansfield RS (GitHub rule)",
        "github-2026-trend-radar-minervini",
        "abeer555/Trend-Radar `mansfield.py` (GitHub); Weinstein (1988), Secrets for Profiting in Bull and Bear Markets",
        "Weekly, hold the 20 stocks above a rising 30-week average that have beaten the Nifty most over a year.",
        (
            "Stage 2: close above the 150-day average, itself above its level a month ago. "
            "Mansfield RS: stock/NIFTYBEES now over the same ratio 52 weeks ago, less 1; above 0.",
            "Top 20 by RS, fixed twentieths, point-in-time 250 most-traded.",
        ),
        YEAR + 30,
        lambda: WeinsteinStageTwo("nse_github_weinstein_stage2"),
    ),
    PaperStrategy(
        "india_halloween_nifty",
        "Halloween effect: Nifty in winter, cash in summer (India)",
        "jacobsen-zhang-2018-halloween-everywhere",
        "Jacobsen & Zhang (2018), The Halloween Indicator, 'Sell in May and Go Away': Everywhere and All the Time",
        "Hold NIFTYBEES from November to April and LIQUIDBEES from May to October.",
        (
            "Winter returns beat summer returns by about 4.5 points a year across 114 "
            "markets over 320 years, significant in 42; India's own figure was not read.",
            "Two switches a year; LIQUIDBEES stands in for cash.",
        ),
        2,
        lambda: Halloween("india_halloween_nifty"),
        "all",
        (INDEX_ETF, SAFE),
    ),
    PaperStrategy(
        "india_volatility_target_nifty",
        "Volatility-targeted Nifty, rest in cash (India)",
        "harvey-et-al-2018-volatility-targeting",
        "Harvey, Hoyle, Korgaonkar, Rattray, Sargaison & Van Hemert (2018), The Impact of Volatility Targeting, JPM",
        "Monthly, hold NIFTYBEES at its 3-year over 1-month volatility (at most 100%), the rest in LIQUIDBEES.",
        (
            "Volatility from daily returns; weight = min(1, 3-year vol / 1-month vol). The "
            "paper targets a fixed level and allows leverage; neither here.",
            "Monthly; LIQUIDBEES stands in for cash.",
        ),
        3 * YEAR + 5,
        lambda: VolatilityTarget("india_volatility_target_nifty"),
        "all",
        (INDEX_ETF, SAFE),
    ),
    PaperStrategy(
        "india_dividend_yield_30",
        "High dividend yield, top 30 (India)",
        "tripathi-aggarwal-2013-dividend-opportunity-india",
        "Tripathi & Aggarwal (2013), Dividend Opportunity Index: An Opportunity for Small Investors (SSRN 2258327)",
        "Every six months, hold the 30 highest trailing-yield stocks among the 250 most-traded.",
        (
            "Yield: dividends with an ex-date in the past year (NSE corporate actions) over "
            "the close; yields above 15% left out as one-offs.",
            "The Indian study found high-yield stocks beat the market at lower risk in "
            "2007-2012; later comparisons with the Nifty are mixed.",
        ),
        10,
        lambda: DividendYield("india_dividend_yield_30"),
    ),
)

BUILDERS: dict[str, Callable[[], Strategy]] = {s.id: s.build for s in STRATEGIES}
BY_ID: dict[str, PaperStrategy] = {s.id: s for s in STRATEGIES}
