"""Strategies from papers on Indian equities, built as their papers state them.

Each builder at the bottom cites one paper in `research/papers/` and follows its
stated rules as far as this platform's data allows. Where a paper's design
cannot be run here, the adaptation is stated in the paper's red flags and in
the builder's docstring, never silently:

- **Long only.** Every long-short factor in these papers is tested on its long
  leg. Cash equities cannot be held short overnight in India; a short leg
  would need single-stock futures, which exist for about 200 names and which
  the daily engine does not trade.
- **Equal weights.** The panel has no share counts, so market-cap weights and
  size buckets are unavailable. Papers that value-weight are run equal-weighted.
- **The universe is point-in-time.** Cross-sectional papers run on the 250
  most-traded stocks *as of each decision date* (median turnover over the
  previous 60 sessions), chosen from the whole panel. The named `nifty250`
  universe is today's list applied to all of history, which hands every past
  backtest the stocks that later became liquid — and those are largely the
  stocks that rose. Run on it, the illiquid decile returned +4,200% over ten
  years; see HISTORY #16.
- **ETFs are excluded** from every cross-sectional rank: an index fund is not a
  stock, and the most-traded list would otherwise include NIFTYBEES.

Calendar strategies trade NIFTYBEES, the Nifty 50 ETF, as the investable
stand-in for the index the paper studied. They read the exchange calendar from
the panel's own trading days, which is known in advance in reality (the
exchange publishes it) but here also includes any unscheduled closure.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from functools import cache
from itertools import pairwise

from eulerlab.backtest.strategy import MarketView, Strategy, normalise
from eulerlab.features.panel import PanelRow

INDEX_ETF = "NIFTYBEES"
MONTH = 21
YEAR = 252

Score = Callable[[Sequence[PanelRow]], float | None]


def _returns(rows: Sequence[PanelRow]) -> list[float]:
    return [b.close / a.close - 1.0 for a, b in pairwise(rows) if a.close > 0]


def _is_fund(row: PanelRow) -> bool:
    return row.isin.startswith("INF")


LIQUID_TOP = 250
LIQUIDITY_WINDOW = 60


def liquid_universe(view: MarketView, top: int = LIQUID_TOP) -> list[str]:
    """The `top` most-traded stocks on `view.as_of`, by median turnover over
    the previous 60 sessions. Funds, and stocks that did not trade today, are
    out. Computed from the view alone, so it cannot know who becomes liquid."""
    ranked: list[tuple[float, str]] = []
    for symbol in view.symbols():
        rows = view.history[symbol]
        if not rows or _is_fund(rows[-1]) or rows[-1].day != view.as_of:
            continue
        values = sorted(r.turnover for r in rows[-LIQUIDITY_WINDOW:])
        if len(values) < LIQUIDITY_WINDOW // 2:
            continue
        ranked.append((values[len(values) // 2], symbol))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return [symbol for _, symbol in ranked[:top]]


def _monthly_closes(rows: Sequence[PanelRow]) -> list[float]:
    """The last close of each calendar month, oldest first."""
    out: list[float] = []
    current: tuple[int, int] | None = None
    for row in rows:
        key = (row.day.year, row.day.month)
        if key != current:
            out.append(row.close)
            current = key
        else:
            out[-1] = row.close
    return out


def _sd(values: Sequence[float]) -> float | None:
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    return math.sqrt(sum((v - mean) ** 2 for v in values) / (len(values) - 1))


# --- scores -----------------------------------------------------------------


def momentum(formation_days: int, skip_days: int) -> Score:
    """Return over `formation_days`, ending `skip_days` before the last close."""

    def score(rows: Sequence[PanelRow]) -> float | None:
        if len(rows) < formation_days + skip_days + 1:
            return None
        first = rows[-formation_days - skip_days - 1].close
        last = rows[-skip_days - 1].close
        return last / first - 1.0 if first > 0 and last > 0 else None

    return score


def nearness_to_52w_high(rows: Sequence[PanelRow]) -> float | None:
    window = rows[-YEAR:]
    if len(window) < YEAR:
        return None
    high = max(r.close for r in window)
    return rows[-1].close / high if high > 0 else None


def max_last5(rows: Sequence[PanelRow]) -> float | None:
    """MAX(L5): the largest daily return in the last 5 trading days of the
    previous month (Sehgal, Vasishth & Deisting 2024). Needs 3 of the 5."""
    if len(rows) < 30:
        return None
    this_month = (rows[-1].day.year, rows[-1].day.month)
    end = len(rows)
    while end > 0 and (rows[end - 1].day.year, rows[end - 1].day.month) == this_month:
        end -= 1
    window = rows[max(0, end - 6) : end]
    rets = _returns(window)
    return max(rets) if len(rets) >= 3 else None


def amihud_illiquidity(rows: Sequence[PanelRow]) -> float | None:
    """Mean |daily return| per rupee traded over the past year (Amihud 2002).
    Needs 50 trading days with turnover, the paper's activity filter."""
    window = rows[-YEAR - 1 :]
    ratios = [
        abs(b.close / a.close - 1.0) / b.turnover
        for a, b in pairwise(window)
        if a.close > 0 and b.turnover > 0
    ]
    return sum(ratios) / len(ratios) if len(ratios) >= 50 else None


def monthly_volatility(months: int, minimum: int) -> Score:
    """Standard deviation of monthly log returns over the past `months`."""

    def score(rows: Sequence[PanelRow]) -> float | None:
        closes = _monthly_closes(rows)[-(months + 1) :]
        rets = [math.log(b / a) for a, b in pairwise(closes) if a > 0 and b > 0]
        return _sd(rets) if len(rets) >= minimum else None

    return score


# --- strategies --------------------------------------------------------------


class RankTop(Strategy):
    """Hold the top fraction of the cross-section by a score, equal-weighted.

    `highest=False` holds the lowest scores. `rebalance_every` is read by the
    batch runner, so each paper's own holding period is the one run.
    """

    def __init__(
        self,
        name: str,
        score: Score,
        *,
        fraction: float,
        highest: bool,
        rebalance_every: int,
        lookback: int,
        min_names: int = 30,
    ) -> None:
        self.name = name
        self.score = score
        self.fraction = fraction
        self.highest = highest
        self.rebalance_every = rebalance_every
        self.lookback = lookback
        self.min_names = min_names

    def target_weights(self, view: MarketView) -> dict[str, float]:
        scored: list[tuple[float, str]] = []
        for symbol in liquid_universe(view):
            rows = view.history[symbol]
            value = self.score(rows)
            if value is not None and math.isfinite(value):
                scored.append((value, symbol))
        if len(scored) < self.min_names:
            return {}
        scored.sort(key=lambda item: (-item[0] if self.highest else item[0], item[1]))
        keep = max(1, round(len(scored) * self.fraction))
        chosen = [symbol for _, symbol in scored[:keep]]
        return dict.fromkeys(chosen, 1.0 / len(chosen))


class DoubleSort(Strategy):
    """Sort on one score, then within the selection on a second.

    `first` keeps the top `first_fraction` (highest), then `second` keeps the
    top `second_fraction` of those (highest, or lowest with `second_low`).
    Equal-weighted, long only.
    """

    def __init__(
        self,
        name: str,
        first: Score,
        second: Score,
        *,
        first_fraction: float,
        second_fraction: float,
        second_low: bool,
        rebalance_every: int,
        lookback: int,
    ) -> None:
        self.name = name
        self.first = first
        self.second = second
        self.first_fraction = first_fraction
        self.second_fraction = second_fraction
        self.second_low = second_low
        self.rebalance_every = rebalance_every
        self.lookback = lookback

    def target_weights(self, view: MarketView) -> dict[str, float]:
        firsts: list[tuple[float, str]] = []
        for symbol in liquid_universe(view):
            value = self.first(view.history[symbol])
            if value is not None and math.isfinite(value):
                firsts.append((value, symbol))
        if len(firsts) < 30:
            return {}
        firsts.sort(key=lambda item: (-item[0], item[1]))
        kept = [s for _, s in firsts[: max(1, round(len(firsts) * self.first_fraction))]]
        seconds: list[tuple[float, str]] = []
        for symbol in kept:
            value = self.second(view.history[symbol])
            if value is not None and math.isfinite(value):
                seconds.append((value, symbol))
        if not seconds:
            return {}
        seconds.sort(key=lambda item: (item[0] if self.second_low else -item[0], item[1]))
        chosen = [s for _, s in seconds[: max(1, round(len(seconds) * self.second_fraction))]]
        return dict.fromkeys(chosen, 1.0 / len(chosen))


def sharpe_momentum(rows: Sequence[PanelRow]) -> float | None:
    """12-month return divided by 12-month daily volatility (annualised)."""
    if len(rows) < YEAR + 1:
        return None
    window = rows[-YEAR - 1 :]
    first, last = window[0].close, window[-1].close
    sd = _sd(_returns(window))
    if first <= 0 or not sd:
        return None
    return (last / first - 1.0) / (sd * math.sqrt(YEAR))


def median_turnover(rows: Sequence[PanelRow]) -> float | None:
    values = sorted(r.turnover for r in rows[-3 * MONTH :] if r.turnover > 0)
    return values[len(values) // 2] if len(values) >= MONTH else None


class AbsoluteMomentum(Strategy):
    """Time-series momentum, long leg: hold every stock whose own past return
    is positive, equal-weighted. With `market_filter`, go to cash in a
    "bearish abnormal" month (Singh et al. 2022): the index's 1-month move is
    larger than its 24-month move, and down."""

    def __init__(self, name: str, score: Score, *, market_filter: bool, lookback: int) -> None:
        self.name = name
        self.score = score
        self.market_filter = market_filter
        self.rebalance_every = MONTH
        self.lookback = lookback

    def _bearish_abnormal(self, view: MarketView) -> bool:
        market = view.history.get(INDEX_ETF)
        if not market or len(market) < 24 * MONTH + 1:
            return False
        last = market[-1].close
        one = last / market[-MONTH - 1].close - 1.0
        two_years = last / market[-24 * MONTH - 1].close - 1.0
        return abs(one) >= abs(two_years) and one < 0

    def target_weights(self, view: MarketView) -> dict[str, float]:
        if self.market_filter and self._bearish_abnormal(view):
            return {}
        chosen = []
        for symbol in liquid_universe(view):
            value = self.score(view.history[symbol])
            if value is not None and value > 0:
                chosen.append(symbol)
        if len(chosen) < 5:
            return {}
        return dict.fromkeys(chosen, 1.0 / len(chosen))


class BigFallReversal(Strategy):
    """Parthasarathy & Sendilvelu (2022), long side: hold large stocks for six
    months after a calendar month in which they fell 20% or more, counting an
    event only if there was none in the six months before it."""

    rebalance_every = MONTH

    def __init__(self, *, threshold: float = -0.20, months: int = 6, top: int = 50) -> None:
        self.name = "india_big_fall_reversal"
        self.threshold = threshold
        self.months = months
        self.top = top
        self.lookback = (2 * months + 2) * MONTH

    def _held(self, rows: Sequence[PanelRow]) -> bool:
        closes = _monthly_closes(rows)
        # Monthly returns, oldest first; the last element is the month in progress.
        rets = [b / a - 1.0 for a, b in pairwise(closes[:-1]) if a > 0]
        events: list[bool] = []
        for k, value in enumerate(rets):
            fresh = not any(events[max(0, k - self.months) : k])
            events.append(value <= self.threshold and fresh)
        return any(events[-self.months :])

    def target_weights(self, view: MarketView) -> dict[str, float]:
        chosen = [s for s in liquid_universe(view, self.top) if self._held(view.history[s])]
        if not chosen:
            return {}
        return dict.fromkeys(chosen, 1.0 / max(len(chosen), 5))


def mean_over_sd(days: int) -> Score:
    """Mean daily log return over its standard deviation (physical momentum's
    inverse-volatility p3, Tripurana & Devulapally 2023)."""

    def score(rows: Sequence[PanelRow]) -> float | None:
        window = rows[-days - 1 :]
        rets = [
            math.log(b.close / a.close) for a, b in pairwise(window) if a.close > 0 and b.close > 0
        ]
        sd = _sd(rets)
        return (sum(rets) / len(rets)) / sd if sd and len(rets) >= days // 2 else None

    return score


class LeadLag(Strategy):
    """Hold the follower ETF for a week after the leader rose over the week
    before (Sahoo & Kumar 2022: large caps lead mid and small caps)."""

    rebalance_every = 5
    lookback = 10

    def __init__(self, name: str, leader: str, follower: str) -> None:
        self.name = name
        self.leader = leader
        self.follower = follower
        self.hold_unchanged = True

    def target_weights(self, view: MarketView) -> dict[str, float]:
        lead = view.history.get(self.leader)
        follow = view.history.get(self.follower)
        if not lead or not follow or len(lead) < 6 or follow[-1].day != view.as_of:
            return {}
        return {self.follower: 1.0} if lead[-1].close > lead[-6].close else {}


class LiquidBuilt(Strategy):
    """A Strategy Builder spec run over the point-in-time top 250 only, so a
    stock-level rule from a paper is not run on every listed name."""

    def __init__(self, inner: Strategy) -> None:
        self.inner = inner
        self.name = inner.name
        self.rebalance_every = getattr(inner, "rebalance_every", 1)
        self.hold_unchanged = getattr(inner, "hold_unchanged", False)
        self.lookback = inner.lookback

    def target_weights(self, view: MarketView) -> dict[str, float]:
        keep = set(liquid_universe(view))
        narrowed = MarketView(
            as_of=view.as_of, history={s: r for s, r in view.history.items() if s in keep}
        )
        return self.inner.target_weights(narrowed)


class LowBeta(Strategy):
    """The long leg of Betting Against Beta (Agarwalla et al. 2014).

    Beta = correlation of 3-day overlapping returns over 5 years (at least 750
    days) times the ratio of 1-year daily volatilities (at least 120 days),
    shrunk 0.6 toward 1. The market is NIFTYBEES, standing in for the Sensex.
    Stocks below the median beta are held with the paper's rank weights,
    unlevered.
    """

    rebalance_every = MONTH
    lookback = 5 * YEAR + 5

    def __init__(self) -> None:
        self.name = "india_bab_low_beta"

    @staticmethod
    def _three_day(rows: Sequence[PanelRow]) -> dict[date, float]:
        return {
            rows[i].day: rows[i].close / rows[i - 3].close - 1.0
            for i in range(3, len(rows))
            if rows[i - 3].close > 0
        }

    def target_weights(self, view: MarketView) -> dict[str, float]:
        market = view.history.get(INDEX_ETF)
        if not market or len(market) < 750:
            return {}
        market_3d = self._three_day(market[-5 * YEAR :])
        market_daily = dict(zip([r.day for r in market[1:]], _returns(market), strict=False))
        market_sd = _sd(
            [market_daily[d] for d in [r.day for r in market[-YEAR:]] if d in market_daily]
        )
        if not market_sd:
            return {}

        betas: list[tuple[float, str]] = []
        for symbol in liquid_universe(view):
            rows = view.history[symbol]
            own_3d = self._three_day(rows[-5 * YEAR :])
            common = [d for d in own_3d if d in market_3d]
            if len(common) < 750:
                continue
            xs = [own_3d[d] for d in common]
            ys = [market_3d[d] for d in common]
            mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
            cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
            vx = sum((x - mx) ** 2 for x in xs)
            vy = sum((y - my) ** 2 for y in ys)
            if vx <= 0 or vy <= 0:
                continue
            rho = cov / math.sqrt(vx * vy)
            own_sd = _sd(_returns(rows[-YEAR - 1 :]))
            if own_sd is None or len(rows) < 121:
                continue
            beta = rho * own_sd / market_sd
            betas.append((0.6 * beta + 0.4, symbol))
        if len(betas) < 30:
            return {}
        betas.sort()
        ranks = {symbol: i + 1 for i, (_, symbol) in enumerate(betas)}
        mean_rank = (len(betas) + 1) / 2
        low = {s: mean_rank - r for s, r in ranks.items() if r < mean_rank}
        total = sum(low.values())
        return normalise({s: w / total for s, w in low.items()})


class IndexCalendar(Strategy):
    """Hold the index ETF over the trading days a calendar rule selects.

    `holds(calendar, i)` says whether to be long over trading day `i` — from the
    close of day i-1 to the close of day i. The engine fills a decision on the
    next trading day's close, so the decision on day d sets the position held
    over day d+2: this asks about `i = index(d) + 2`.
    """

    rebalance_every = 1
    lookback = 5

    def __init__(
        self,
        name: str,
        calendar: Sequence[date] | Callable[[], Sequence[date]],
        holds: Callable[[Sequence[date], int], bool],
    ) -> None:
        self.name = name
        # A loader is called on first use, not at construction: building a
        # strategy must not need the 550 MB panel (the registry builds every
        # strategy to check it can be invoked, in CI where there is no panel).
        self._calendar = calendar
        self.holds = holds
        self.hold_unchanged = True

    @property
    def calendar(self) -> list[date]:
        if callable(self._calendar):
            self._calendar = list(self._calendar())
        return list(self._calendar)

    def target_weights(self, view: MarketView) -> dict[str, float]:
        calendar = self.calendar
        position = bisect_right(calendar, view.as_of) - 1
        target = position + 2
        if position < 0 or target >= len(calendar):
            return {}
        return {INDEX_ETF: 1.0} if self.holds(calendar, target) else {}


class PairRatio(Strategy):
    """Sen (2022), long-only: hold whichever leg the price ratio says is cheap.

    The ratio a/b is z-scored over the past year. Above +1, a is rich: hold b.
    Below -1, hold a. In between, keep the last side, as the paper's always-in
    rule does. The paper's short leg is dropped.
    """

    rebalance_every = 1
    lookback = YEAR + 5

    def __init__(self, name: str, a: str, b: str) -> None:
        self.name = name
        self.a, self.b = a, b
        self.hold_unchanged = True

    def _side(self, ratios: Sequence[float]) -> str | None:
        """Replay the band crossings over the history in view, with running
        sums so each day's z-score costs O(1)."""
        side: str | None = None
        total = squares = 0.0
        for k, value in enumerate(ratios):
            total += value
            squares += value * value
            if k >= YEAR:
                old = ratios[k - YEAR]
                total -= old
                squares -= old * old
            if k < YEAR - 1:
                continue
            mean = total / YEAR
            variance = (squares - YEAR * mean * mean) / (YEAR - 1)
            if variance <= 0:
                continue
            z = (value - mean) / math.sqrt(variance)
            if z > 1:
                side = self.b
            elif z < -1:
                side = self.a
        return side

    def target_weights(self, view: MarketView) -> dict[str, float]:
        ra, rb = view.history.get(self.a), view.history.get(self.b)
        if not ra or not rb:
            return {}
        by_day = {r.day: r.close for r in rb}
        ratios = [r.close / by_day[r.day] for r in ra[-2 * YEAR :] if by_day.get(r.day)]
        if len(ratios) < YEAR:
            return {}
        side = self._side(ratios)
        return {side: 1.0} if side else {}


# --- calendar rules ----------------------------------------------------------


def turn_of_month(calendar: Sequence[date], i: int) -> bool:
    """Days -1 to +2 around the month end: the last trading day of the month
    and the first two of the next (Maher & Parikh 2013, window unverified)."""
    day = calendar[i]
    next_day = calendar[i + 1] if i + 1 < len(calendar) else None
    if next_day is not None and next_day.month != day.month:
        return True
    first = i
    while first > 0 and calendar[first - 1].month == day.month:
        first -= 1
    # A month the calendar does not see the start of has no known first days.
    return first > 0 and i - first < 2


def monday_or_wednesday(calendar: Sequence[date], i: int) -> bool:
    """Srinivasan & Kalaivani (2013): positive Monday and Wednesday returns."""
    return calendar[i].weekday() in (0, 2)


def _expiry_weekday(day: date) -> int:
    """Nifty monthly expiry: last Thursday, moved to last Tuesday from
    September 2025 (NSE circular FAOP68747)."""
    return 1 if day >= date(2025, 9, 1) else 3


def is_monthly_expiry(calendar: Sequence[date], i: int) -> bool:
    """The month's expiry: the last trading day on or before the month's last
    expiry weekday, since a holiday moves expiry to the previous trading day."""
    import calendar as cal

    day = calendar[i]
    weekday = _expiry_weekday(day)
    last = date(day.year, day.month, cal.monthrange(day.year, day.month)[1])
    while last.weekday() != weekday:
        last = date.fromordinal(last.toordinal() - 1)
    position = bisect_right(calendar, last) - 1
    return position == i


UNION_BUDGETS = (
    date(2016, 2, 29),
    date(2017, 2, 1),
    date(2018, 2, 1),
    date(2019, 2, 1),
    date(2019, 7, 5),
    date(2020, 2, 1),
    date(2021, 2, 1),
    date(2022, 2, 1),
    date(2023, 2, 1),
    date(2024, 2, 1),
    date(2024, 7, 23),
    date(2025, 2, 1),
    date(2026, 2, 1),
)
"""Union Budget presentation days, interim budgets included. # ASSUMPTION: A-042."""


def around_budget(calendar: Sequence[date], i: int) -> bool:
    """Days -1, 0 and +1 around each Union Budget. A budget on a day the market
    did not trade counts from the next trading day."""
    for budget in UNION_BUDGETS:
        event = bisect_right(calendar, budget - timedelta(days=1))
        if event < len(calendar) and event - 1 <= i <= event + 1:
            return True
    return False


def december(calendar: Sequence[date], i: int) -> bool:
    """Sah (2009): the December effect."""
    return calendar[i].month == 12


def post_holiday(calendar: Sequence[date], i: int) -> bool:
    """Lu & Patel (2016): the first trading day after an exchange holiday —
    a weekday the market was shut, between the previous trading day and this."""
    if i == 0:
        return False
    previous, day = calendar[i - 1], calendar[i]
    gap = (day - previous).days
    weekdays_skipped = sum(
        1 for k in range(1, gap) if date.fromordinal(previous.toordinal() + k).weekday() < 5
    )
    return weekdays_skipped > 0


# --- the calendar ------------------------------------------------------------


@cache
def trading_calendar() -> tuple[date, ...]:
    """NIFTYBEES's trading days from the price panel, read once per process.

    # ASSUMPTION: the exchange calendar is known ahead of each date. NSE
    # publishes its holiday list for the year in advance, so knowing that the
    # day after tomorrow is a holiday is not lookahead; the panel's calendar
    # also contains the rare unscheduled closure, which is. See A-041.
    """
    import json

    from eulerlab.features.panel import PANEL_PATH

    days: set[date] = set()
    marker = f'"s": "{INDEX_ETF}"'
    if not PANEL_PATH.exists():
        return ()
    with PANEL_PATH.open(encoding="utf-8") as handle:
        for line in handle:
            if marker in line:
                days.add(date.fromisoformat(json.loads(line)["d"]))
    return tuple(sorted(days))


# --- the registry ------------------------------------------------------------


@dataclass(frozen=True)
class PaperStrategy:
    """One paper's strategy as this platform runs it."""

    id: str
    title: str
    paper: str
    """The research library id, `research/papers/<paper>.yaml`."""
    citation: str
    summary: str
    logic: tuple[str, ...]
    lookback: int
    build: Callable[[], Strategy]
    universe: str = "all"
    """The batch universe. Cross-sectional strategies take the whole panel and
    choose their own point-in-time top 250; see the module docstring."""
    instruments: tuple[str, ...] = ()


def _macd_buy() -> Strategy:
    from eulerlab.builder.compile import BuiltStrategy
    from eulerlab.builder.spec import BuilderSpec

    def i(name: str, **params: float) -> dict[str, object]:
        return {"kind": "indicator", "name": name, "params": params}

    spec = BuilderSpec.model_validate(
        {
            "id": "b_india_macd_buy",
            "name": "MACD buy signal on the Nifty",
            "universe": {"asset_class": "equity", "universe": "all", "instruments": [INDEX_ETF]},
            "entry": {
                "match": "all",
                "rules": [
                    {"left": i("macd_line"), "op": "below", "right": {"kind": "value", "value": 0}},
                    {
                        "left": i("macd_signal"),
                        "op": "below",
                        "right": {"kind": "value", "value": 0},
                    },
                    {"left": i("macd_signal"), "op": "above", "right": i("macd_line")},
                ],
            },
            "sizing": {"max_positions": 1},
            "risk": {"max_hold_days": 1},
        }
    )
    strategy = BuiltStrategy(spec)
    strategy.name = "india_macd_buy"
    return strategy


def _nifty_sma60() -> Strategy:
    from eulerlab.builder.compile import BuiltStrategy
    from eulerlab.builder.spec import BuilderSpec

    close = {"kind": "indicator", "name": "close", "params": {}}
    sma = {"kind": "indicator", "name": "sma", "params": {"period": 60}}
    spec = BuilderSpec.model_validate(
        {
            "id": "b_india_nifty_sma60",
            "name": "Nifty above its 60-day average",
            "universe": {"asset_class": "equity", "universe": "all", "instruments": [INDEX_ETF]},
            "entry": {"rules": [{"left": close, "op": "above", "right": sma}]},
            "exit": {"rules": [{"left": close, "op": "below", "right": sma}]},
            "sizing": {"max_positions": 1},
        }
    )
    strategy = BuiltStrategy(spec)
    strategy.name = "india_nifty_sma60"
    return strategy


def _bb_rsi() -> Strategy:
    from eulerlab.builder.compile import BuiltStrategy
    from eulerlab.builder.spec import BuilderSpec

    def i(name: str, **params: float) -> dict[str, object]:
        return {"kind": "indicator", "name": name, "params": params}

    def v(value: float) -> dict[str, object]:
        return {"kind": "value", "value": value}

    spec = BuilderSpec.model_validate(
        {
            "id": "b_india_bb_rsi",
            "name": "Bollinger and RSI reversion",
            "universe": {"asset_class": "equity", "universe": "all"},
            "entry": {
                "match": "all",
                "rules": [
                    {"left": i("close"), "op": "below", "right": i("bb_lower", period=20, width=2)},
                    {"left": i("rsi", period=14), "op": "below", "right": v(30)},
                ],
            },
            "exit": {
                "match": "all",
                "rules": [
                    {"left": i("close"), "op": "above", "right": i("bb_upper", period=20, width=2)},
                    {"left": i("rsi", period=14), "op": "above", "right": v(70)},
                ],
            },
            "sizing": {"max_positions": 10},
        }
    )
    built = BuiltStrategy(spec)
    built.name = "india_bb_rsi"
    return LiquidBuilt(built)


def _calendar(name: str, rule: Callable[[Sequence[date], int], bool]) -> Callable[[], Strategy]:
    return lambda: IndexCalendar(name, trading_calendar, rule)


INDEX_ONLY = (INDEX_ETF,)

STRATEGIES: tuple[PaperStrategy, ...] = (
    PaperStrategy(
        "india_bab_low_beta",
        "Betting against beta, long leg (India)",
        "agarwalla-2014-betting-against-beta-india",
        "Agarwalla, Jacob, Varma & Vasudevan (2014), IIMA WP 2014-07-01",
        "Hold the below-median-beta half of the point-in-time top 250, rank-weighted toward the lowest beta.",
        (
            "Beta: correlation of 3-day returns with NIFTYBEES over 5 years (750+ days) "
            "times the ratio of 1-year daily volatilities, shrunk 0.6 toward 1.",
            "Each month, hold stocks below the median beta, weighted by distance below "
            "the mean rank. Unlevered and long only: the paper's short leg is dropped.",
        ),
        5 * YEAR + 5,
        LowBeta,
    ),
    PaperStrategy(
        "india_high_vol60",
        "High 60-month volatility quintile (India)",
        "pandey-2016-low-volatility-india",
        "Pandey & Samanta (2016), IRA-IJMSS 4(1)",
        "Hold the most volatile fifth of the point-in-time top 250 by 60-month volatility, the quintile the paper found best.",
        (
            "Volatility: standard deviation of monthly log returns over the past 60 months.",
            "Each month, hold the highest-volatility quintile, equal-weighted. The paper "
            "set out to find a low-volatility anomaly and reported the opposite; this "
            "tests what it reported.",
        ),
        61 * MONTH,
        lambda: RankTop(
            "india_high_vol60",
            monthly_volatility(60, 60),
            fraction=0.2,
            highest=True,
            rebalance_every=MONTH,
            lookback=61 * MONTH,
        ),
    ),
    PaperStrategy(
        "india_low_max_l5",
        "Low lottery score, MAX(L5) (India)",
        "sehgal-2024-lottery-factor-india",
        "Sehgal, Vasishth & Deisting (2024), Borsa Istanbul Review 24(3)",
        "Hold the decile of the point-in-time top 250 with the smallest best day in the last 5 sessions of last month.",
        (
            "MAX(L5): the largest daily return in the last 5 trading days of the previous month.",
            "Each month, hold the lowest decile, equal-weighted (the paper value-weights). "
            "Long only, as the authors themselves suggest for India.",
        ),
        2 * MONTH,
        lambda: RankTop(
            "india_low_max_l5",
            max_last5,
            fraction=0.1,
            highest=False,
            rebalance_every=MONTH,
            lookback=2 * MONTH,
        ),
    ),
    PaperStrategy(
        "india_illiquid_decile",
        "Most illiquid decile, Amihud (India)",
        "kundlia-2021-illiquidity-premium-india",
        "Kundlia & Verma (2021), Asian Economic and Financial Review 11(6)",
        "Hold the most illiquid tenth of the point-in-time top 250 by Amihud's measure, rebalanced yearly.",
        (
            "Illiquidity: mean |daily return| per rupee traded over the past year, 50+ days.",
            "Once a year, hold the most illiquid decile, equal-weighted. The top 250 is the "
            "liquid end of the market, so this tests the premium where it is tradable.",
        ),
        YEAR + 2,
        lambda: RankTop(
            "india_illiquid_decile",
            amihud_illiquidity,
            fraction=0.1,
            highest=True,
            rebalance_every=YEAR,
            lookback=YEAR + 2,
        ),
    ),
    PaperStrategy(
        "india_wml_12_1",
        "Momentum winners, 12-1, top 30% (India)",
        "agarwalla-2013-four-factor-india",
        "Agarwalla, Jacob & Varma (2013), IIMA WP 2013-09-05",
        "Hold the top 30% of the point-in-time top 250 by return from month t-12 to t-1, rebalanced monthly.",
        (
            "Formation: return from 12 months ago to 1 month ago, skipping the last month.",
            "Each month, hold the top 30%, equal-weighted. The factor's loser short leg "
            "and size split are dropped.",
        ),
        13 * MONTH,
        lambda: RankTop(
            "india_wml_12_1",
            momentum(11 * MONTH, MONTH),
            fraction=0.3,
            highest=True,
            rebalance_every=MONTH,
            lookback=13 * MONTH,
        ),
    ),
    PaperStrategy(
        "india_low_tvol36",
        "Lowest 36-month volatility quintile (India)",
        "joshipura-2017-low-risk-india",
        "Joshipura & Peswani (2017), Applied Finance Letters 6(1)",
        "Hold the least volatile fifth of the point-in-time top 250 by 36-month volatility, rebalanced monthly.",
        (
            "Volatility: standard deviation of monthly excess log returns over 36 months, "
            "12 at least.",
            "Each month, hold the lowest quintile, equal-weighted, as the paper does.",
        ),
        37 * MONTH,
        lambda: RankTop(
            "india_low_tvol36",
            monthly_volatility(36, 12),
            fraction=0.2,
            highest=False,
            rebalance_every=MONTH,
            lookback=37 * MONTH,
        ),
    ),
    PaperStrategy(
        "india_turn_of_month",
        "Turn of the month, Nifty (India)",
        "maher-2013-turn-of-month-india",
        "Maher & Parikh (2013), International Review of Financial Analysis 28",
        "Hold NIFTYBEES over the last trading day of each month and the first two of the next.",
        (
            "Long NIFTYBEES over trading days -1, +1 and +2 around the month end.",
            "The window is unverified: only the abstract could be read.",
        ),
        5,
        _calendar("india_turn_of_month", turn_of_month),
        "all",
        INDEX_ONLY,
    ),
    PaperStrategy(
        "india_monday_wednesday",
        "Monday and Wednesday, Nifty (India)",
        "srinivasan-2013-day-of-week-india",
        "Srinivasan & Kalaivani (2013), MPRA 46805",
        "Hold NIFTYBEES over Mondays and Wednesdays only.",
        ("Long NIFTYBEES from the previous close to the Monday close and to the Wednesday close.",),
        5,
        _calendar("india_monday_wednesday", monday_or_wednesday),
        "all",
        INDEX_ONLY,
    ),
    PaperStrategy(
        "india_expiry_day",
        "Monthly expiry day, Nifty (India)",
        "singh-2020-expiry-effects-india",
        "Singh & Shaik (2020), International Journal of Economics and Financial Issues 10(3)",
        "Hold NIFTYBEES over the monthly F&O expiry day only.",
        (
            "Expiry: the last Thursday of the month (last Tuesday from September 2025), "
            "or the trading day before when that is a holiday.",
            "Long NIFTYBEES from the previous close to the expiry close. The paper found "
            "no significant return effect; this measures whether one exists here.",
        ),
        5,
        _calendar("india_expiry_day", is_monthly_expiry),
        "all",
        INDEX_ONLY,
    ),
    PaperStrategy(
        "india_pair_bharatforg_ashokley",
        "Pair: Bharat Forge / Ashok Leyland (India)",
        "sen-2022-pair-trading-india",
        "Sen (2022), arXiv:2211.07080",
        "Hold whichever of Bharat Forge and Ashok Leyland the price ratio says is cheap.",
        (
            "Ratio BHARATFORG/ASHOKLEY, z-scored over the past year.",
            "z above +1: hold ASHOKLEY. z below -1: hold BHARATFORG. Otherwise keep the "
            "last side. The paper's short leg is dropped.",
        ),
        YEAR + 5,
        lambda: PairRatio("india_pair_bharatforg_ashokley", "BHARATFORG", "ASHOKLEY"),
        "all",
        ("BHARATFORG", "ASHOKLEY"),
    ),
    PaperStrategy(
        "india_macd_buy",
        "MACD buy signal, Nifty (India)",
        "muruganandan-2020-technical-rules-india",
        "Muruganandan (2020), Colombo Business Journal 11(1)",
        "Hold NIFTYBEES for one day after a MACD buy signal.",
        (
            "Buy when MACD(12,26) is below 0, its signal line is below 0, and the signal "
            "is above MACD. Sell the next day.",
            "The paper's signal line is a 9-day SMA; the builder's is an EMA. The paper "
            "trades open to close; the daily engine trades close to close. The paper's "
            "profitable side was the short (sell) signal, which cannot be run long only.",
        ),
        40,
        _macd_buy,
        "all",
        INDEX_ONLY,
    ),
    PaperStrategy(
        "india_post_holiday",
        "Day after a holiday, Nifty (India)",
        "lu-2016-festivity-anomaly-india",
        "Lu & Patel (2016), Economics Bulletin 36(2)",
        "Hold NIFTYBEES over the first trading day after an exchange holiday.",
        ("Long NIFTYBEES from the close before a holiday to the close of the first day after it.",),
        5,
        _calendar("india_post_holiday", post_holiday),
        "all",
        INDEX_ONLY,
    ),
    PaperStrategy(
        "india_momentum_3x6",
        "Momentum 3-month formation, 6-month hold (India)",
        "maheshwari-2015-momentum-seasonality-india",
        "Maheshwari & Dhankar (2015), Journal of Commerce and Accounting Research 4(3-4)",
        "Hold the top decile of the point-in-time top 250 by 3-month return, re-formed every 6 months.",
        (
            "Formation: return over the past 3 months. Hold the top decile for 6 months.",
            "3x6 is the paper's best-reported combination (0.87%/month); only the abstract "
            "could be read, so the decile and weighting are assumed.",
        ),
        4 * MONTH,
        lambda: RankTop(
            "india_momentum_3x6",
            momentum(3 * MONTH, 0),
            fraction=0.1,
            highest=True,
            rebalance_every=6 * MONTH,
            lookback=4 * MONTH,
        ),
    ),
    PaperStrategy(
        "india_sharpe_momentum",
        "Volatility-adjusted momentum, top 30 (India)",
        "vijaykumar-2020-momentum-india",
        "Vijaykumar (2020), SSRN 3614509",
        "Hold the 30 stocks of the point-in-time top 250 with the best 12-month return per unit of volatility.",
        (
            "Score: 12-month return divided by annualised 12-month daily volatility.",
            "Hold the top 30, equal-weighted, rebalanced monthly. The paper's exact rules "
            "were not readable; this is the volatility-adjusted ranking its summary credits.",
        ),
        YEAR + 5,
        lambda: RankTop(
            "india_sharpe_momentum",
            sharpe_momentum,
            fraction=30 / LIQUID_TOP,
            highest=True,
            rebalance_every=MONTH,
            lookback=YEAR + 5,
        ),
    ),
    PaperStrategy(
        "india_momentum_12_noskip",
        "12-month momentum, no skip, top 30 (India)",
        "vijaykumar-2026-which-momentum-india",
        "Vijaykumar (2026), SSRN 7394980",
        "Hold the 30 stocks of the point-in-time top 250 with the best 12-month return, rebalanced monthly.",
        (
            "Score: 12-month return including the last month, one of the two best of the "
            "ten definitions the paper compares.",
            "Top 30, equal-weighted, monthly. The paper's top-50 holding buffer is not "
            "applied: a strategy here cannot see what it already holds.",
        ),
        YEAR + 5,
        lambda: RankTop(
            "india_momentum_12_noskip",
            momentum(YEAR, 0),
            fraction=30 / LIQUID_TOP,
            highest=True,
            rebalance_every=MONTH,
            lookback=YEAR + 5,
        ),
    ),
    PaperStrategy(
        "india_52w_high",
        "Nearest the 52-week high, top decile (India)",
        "raju-2023-52-week-high-india",
        "Raju (2023), SSRN 4587697",
        "Hold the decile of the point-in-time top 250 closest to its 52-week high, rebalanced monthly.",
        (
            "Score: today's close over the highest close of the past 52 weeks (George & Hwang).",
            "Top decile, equal-weighted, monthly. Assumed: only the abstract was readable.",
        ),
        YEAR + 5,
        lambda: RankTop(
            "india_52w_high",
            nearness_to_52w_high,
            fraction=0.1,
            highest=True,
            rebalance_every=MONTH,
            lookback=YEAR + 5,
        ),
    ),
    PaperStrategy(
        "india_weekly_momentum",
        "Weekly momentum, top decile (India)",
        "sapate-2017-weekly-momentum-india",
        "Sapate (2017), SSRN 3065621",
        "Hold last week's top decile of the point-in-time top 250 for one week.",
        (
            "Score: return over the past 5 trading days. Hold the top decile for 5 days.",
            "Assumed: the paper's abstract states no formation or holding length.",
        ),
        2 * MONTH,
        lambda: RankTop(
            "india_weekly_momentum",
            momentum(5, 0),
            fraction=0.1,
            highest=True,
            rebalance_every=5,
            lookback=2 * MONTH,
        ),
    ),
    PaperStrategy(
        "india_illiquid_winners",
        "Illiquid winners (India)",
        "aziz-2014-momentum-illiquidity-india",
        "Aziz & Ansari (2014), SSRN 2416637",
        "Among the top 30% by 6-month return, hold the more illiquid half by Amihud's measure.",
        (
            "Winners: top 30% of the point-in-time top 250 by 6-month return.",
            "Of those, hold the half with the highest Amihud illiquidity, equal-weighted, "
            "monthly. Formation and split are assumed: only the abstract was readable.",
        ),
        YEAR + 5,
        lambda: DoubleSort(
            "india_illiquid_winners",
            momentum(6 * MONTH, 0),
            amihud_illiquidity,
            first_fraction=0.3,
            second_fraction=0.5,
            second_low=False,
            rebalance_every=MONTH,
            lookback=YEAR + 5,
        ),
    ),
    PaperStrategy(
        "india_liquid_winners",
        "Liquid winners (India)",
        "chui-2023-momentum-reversals-liquidity-india",
        "Chui, Ranganathan, Rohit & Veeraraghavan (2023), Pacific-Basin Finance Journal 82",
        "Among the top 30% by 6-month return, hold the more liquid half by turnover.",
        (
            "Winners: top 30% of the point-in-time top 250 by 6-month return.",
            "Of those, hold the half with the highest median rupee turnover (the paper uses "
            "share turnover ratio; shares outstanding are not in the panel). Monthly.",
        ),
        YEAR + 5,
        lambda: DoubleSort(
            "india_liquid_winners",
            momentum(6 * MONTH, 0),
            median_turnover,
            first_fraction=0.3,
            second_fraction=0.5,
            second_low=False,
            rebalance_every=MONTH,
            lookback=YEAR + 5,
        ),
    ),
    PaperStrategy(
        "india_tsmom",
        "Time-series momentum, long leg (India)",
        "singh-2020-time-series-momentum-india",
        "Singh & Walia (2020), Copernican Journal of Finance & Accounting 9(3)",
        "Hold every stock in the point-in-time top 250 whose own return from month t-12 to t-2 is positive.",
        (
            "Signal: return over months t-12 to t-2 (one-month gap). Positive means long.",
            "Hold all positive stocks, equal-weighted, rebalanced monthly. The short leg "
            "(negative stocks) is dropped.",
        ),
        13 * MONTH,
        lambda: AbsoluteMomentum(
            "india_tsmom", momentum(11 * MONTH, MONTH), market_filter=False, lookback=13 * MONTH
        ),
    ),
    PaperStrategy(
        "india_tsmom_risk_managed",
        "Risk-managed time-series momentum (India)",
        "singh-2022-risk-managed-momentum-india",
        "Singh, Walia, Bekiros, Gupta, Kumar & Mishra (2022), JEFAS 27(54)",
        "Time-series momentum's long leg, in cash after a month when the index fell more than over two years.",
        (
            "Signal: 12-month return with a one-month gap; hold positive stocks, equal-weighted.",
            "Market state: if NIFTYBEES's 1-month move is larger than its 24-month move and "
            "down, hold cash that month (the paper goes short-only; long only here).",
        ),
        25 * MONTH,
        lambda: AbsoluteMomentum(
            "india_tsmom_risk_managed",
            momentum(12 * MONTH, MONTH),
            market_filter=True,
            lookback=25 * MONTH,
        ),
    ),
    PaperStrategy(
        "india_budget_days",
        "Union Budget days, Nifty (India)",
        "srinivasu-2025-union-budget-india",
        "Srinivasu & Prathyusha (2025), International Journal of Economics and Business Administration 23(1)",
        "Hold NIFTYBEES over the day before, the day of, and the day after each Union Budget.",
        (
            "Long NIFTYBEES over trading days -1, 0 and +1 around each Union Budget, interim included.",
        ),
        5,
        _calendar("india_budget_days", around_budget),
        "all",
        INDEX_ONLY,
    ),
    PaperStrategy(
        "india_nifty_sma60",
        "Nifty above its 60-day average (India)",
        "mitra-2011-moving-average-rules-india",
        "Mitra (2011), International Journal of Business and Management 6(7)",
        "Hold NIFTYBEES while it closes above its 60-day simple moving average.",
        (
            "Long NIFTYBEES while the close is above SMA(60); in cash when it closes below.",
            "The paper is always in the market, short below the average; long only here. "
            "SMA(60) is the rule the paper finds survives costs best.",
        ),
        70,
        _nifty_sma60,
        "all",
        INDEX_ONLY,
    ),
    PaperStrategy(
        "india_physical_momentum",
        "Physical momentum, return over volatility (India)",
        "tripurana-2023-physical-momentum-india",
        "Tripurana & Devulapally (2023), arXiv:2302.13245",
        "Hold the 10 stocks of the point-in-time top 250 with the best 6-month mean-over-volatility of daily returns, for 2 months.",
        (
            "Score: mean daily log return over 6 months divided by its standard deviation "
            "(the paper's inverse-volatility p3).",
            "Hold the top 10, equal-weighted, re-formed every 2 months (the paper's best "
            "monthly cell is 6-2). The turnover-weighted variants need shares outstanding.",
        ),
        7 * MONTH,
        lambda: RankTop(
            "india_physical_momentum",
            mean_over_sd(6 * MONTH),
            fraction=10 / LIQUID_TOP,
            highest=True,
            rebalance_every=2 * MONTH,
            lookback=7 * MONTH,
        ),
    ),
    PaperStrategy(
        "india_big_fall_reversal",
        "Buy after a 20% monthly fall (India)",
        "parthasarathy-2022-large-price-moves-india",
        "Parthasarathy & Sendilvelu (2022), Economic Thought Journal 67(3)",
        "Hold large stocks for six months after a calendar month in which they fell 20% or more.",
        (
            "Universe: the 50 most-traded stocks at each date (the paper uses Nifty 50 members).",
            "Event: a calendar month return of -20% or worse, with no event in the 6 months "
            "before. Hold for 6 months, equal-weighted, at least 5 slots.",
        ),
        14 * MONTH,
        BigFallReversal,
    ),
    PaperStrategy(
        "india_contrarian_36m",
        "Three-year losers (India)",
        "joshipura-2009-overreaction-india",
        "Joshipura (2009), NSE research paper",
        "Hold the decile of the point-in-time top 250 with the worst 3-year return, re-formed yearly.",
        (
            "Score: return over the past 36 months. Hold the bottom decile, equal-weighted.",
            "Re-formed every year (the paper's cohorts start 12 months apart and run 36 "
            "months; overlapping cohorts are not modelled). The winner short is dropped.",
        ),
        37 * MONTH,
        lambda: RankTop(
            "india_contrarian_36m",
            momentum(36 * MONTH, 0),
            fraction=0.1,
            highest=False,
            rebalance_every=YEAR,
            lookback=37 * MONTH,
        ),
    ),
    PaperStrategy(
        "india_december",
        "December only, Nifty (India)",
        "sah-2009-seasonality-india",
        "Sah (2009), NSE research paper",
        "Hold NIFTYBEES in December only.",
        ("Long NIFTYBEES over every trading day in December; in cash otherwise.",),
        5,
        _calendar("india_december", december),
        "all",
        INDEX_ONLY,
    ),
    PaperStrategy(
        "india_bb_rsi",
        "Bollinger and RSI reversion (India)",
        "shalinigayathri-2024-bollinger-rsi-india",
        "Shalinigayathri & Shunmuga Kumari (2024), IJCRT 12(4)",
        "Buy a stock that closes below its lower Bollinger band with RSI under 30; sell above the upper band with RSI over 70.",
        (
            "Bollinger(20, 2) and RSI(14) on the point-in-time top 250; at most 10 positions.",
            "Entry: close below the lower band and RSI below 30. Exit: close above the upper "
            "band and RSI above 70. The paper tested ITC and Tata Coffee, 2019-2023.",
        ),
        40,
        _bb_rsi,
    ),
    PaperStrategy(
        "india_midcap_follows_largecap",
        "Mid caps follow large caps, weekly (India)",
        "sahoo-2022-lead-lag-india",
        "Sahoo & Kumar (2022), Southeast Asian Journal of Economics 10(2)",
        "Hold the Midcap 150 ETF for a week after the Nifty 100 ETF rose over the week before.",
        (
            "Leader NIF100BEES, follower MID150BEES; both ETFs list from 2022.",
            "Weekly, because the engine fills a decision on the next close: a one-day lead "
            "would be lost to that lag.",
        ),
        10,
        lambda: LeadLag("india_midcap_follows_largecap", "NIF100BEES", "MID150BEES"),
        "all",
        ("NIF100BEES", "MID150BEES"),
    ),
)

BUILDERS: dict[str, Callable[[], Strategy]] = {s.id: s.build for s in STRATEGIES}
BY_ID: dict[str, PaperStrategy] = {s.id: s for s in STRATEGIES}
