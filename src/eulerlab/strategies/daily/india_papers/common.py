"""Shared pieces of the india papers strategies: helpers used by more than one, and the types they share."""

from __future__ import annotations

import math
from bisect import bisect_right
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from functools import cache
from itertools import pairwise

from eulerlab.backtest.strategy import MarketView, Strategy
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


def sharpe_momentum_over(days: int) -> Score:
    """Return over `days` divided by daily volatility over the same `days`,
    annualised. The paper's window is a year; the sweep in research 067 varies it."""

    def score(rows: Sequence[PanelRow]) -> float | None:
        if len(rows) < days + 1:
            return None
        window = rows[-days - 1 :]
        first, last = window[0].close, window[-1].close
        sd = _sd(_returns(window))
        if first <= 0 or not sd:
            return None
        return (last / first - 1.0) / (sd * math.sqrt(days))

    return score


sharpe_momentum = sharpe_momentum_over(YEAR)
"""12-month return divided by 12-month daily volatility (annualised)."""


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


def _calendar(name: str, rule: Callable[[Sequence[date], int], bool]) -> Callable[[], Strategy]:
    return lambda: IndexCalendar(name, trading_calendar, rule)


INDEX_ONLY = (INDEX_ETF,)
