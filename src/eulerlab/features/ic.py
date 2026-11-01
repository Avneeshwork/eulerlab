"""Information Coefficient: does this feature predict forward returns at all?

IC is the rank correlation between a feature's cross-sectional ranking today
and the ranking of what happens *next*. It is the cheap first filter — an
order of magnitude less work than a backtest — and the point of running it
first is to kill most ideas before they cost anything.

**Rank correlation, not Pearson.** Feature values are fat-tailed, as Sprint 6
measured directly on this project's own data, and a Pearson correlation on
fat-tailed inputs is dominated by whichever handful of points are most
extreme. Spearman asks only about ordering, so one wild value moves it by one
rank. This is the same argument as MAD over standard deviation and Theil-Sen
over least squares, arriving a third time.

**The forward return must be strictly forward.** The feature is computed from
data up to and including day *t*; the return runs from *t* to *t+h* and no
part of it may touch the feature. Getting this off by a single day is the
classic way to manufacture an IC that does not exist — the feature would then
partly contain the answer. `evaluate` therefore takes the panel and derives
both sides itself rather than accepting a caller's aligned arrays, because an
aligned array is precisely where the off-by-one hides.

**A positive IC is not evidence of edge on its own.** Ten features chosen by
someone who already believes in them will produce several positive ICs by
construction. The tear sheet reports the t-statistic, the per-year breakdown
and the number of periods so that a signal which worked only in one year
cannot hide behind a flattering average.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from eulerlab.features.library import Feature
from eulerlab.features.panel import PanelRow, by_symbol, trading_days


def rank(values: Sequence[float]) -> list[float]:
    """Ranks, averaging ties.

    Ties matter here: many features are flat across illiquid names, and
    breaking ties by input order would inject the panel's alphabetical
    ordering into the correlation as if it were information.
    """
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        shared = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = shared
        i = j + 1
    return ranks


def spearman(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    """Rank correlation. None when it is not defined."""
    if len(xs) != len(ys) or len(xs) < 3:
        return None
    rx, ry = rank(xs), rank(ys)
    n = len(rx)
    mean_x = sum(rx) / n
    mean_y = sum(ry) / n
    cov = sum((a - mean_x) * (b - mean_y) for a, b in zip(rx, ry, strict=True))
    var_x = sum((a - mean_x) ** 2 for a in rx)
    var_y = sum((b - mean_y) ** 2 for b in ry)
    if var_x <= 0 or var_y <= 0:
        # One side is entirely tied, so there is no ordering to correlate.
        return None
    return float(cov / (var_x * var_y) ** 0.5)


@dataclass(frozen=True)
class PeriodIC:
    day: date
    ic: float
    n: int


@dataclass
class ICResult:
    feature: str
    periods: list[PeriodIC]
    horizon_days: int
    skipped_thin: int
    """Cross-sections dropped for having too few symbols with both a feature
    and a forward return. Reported rather than hidden: a feature that only
    scores on 5 names is not comparable to one that scores on 500."""

    @property
    def n(self) -> int:
        return len(self.periods)

    @property
    def mean_ic(self) -> float:
        return sum(p.ic for p in self.periods) / self.n if self.n else 0.0

    @property
    def std_ic(self) -> float:
        if self.n < 2:
            return 0.0
        mean = self.mean_ic
        variance = sum((p.ic - mean) ** 2 for p in self.periods) / (self.n - 1)
        return float(variance**0.5)

    @property
    def t_stat(self) -> float:
        """Mean IC over its standard error.

        The number that matters. A mean IC of 0.03 across 500 periods is
        interesting; the same 0.03 across 8 periods is noise, and only the
        t-statistic distinguishes them.
        """
        if self.n < 2 or self.std_ic == 0:
            return 0.0
        return float(self.mean_ic / (self.std_ic / self.n**0.5))

    @property
    def hit_rate(self) -> float:
        """Share of periods with a positive IC. A signal that is right 52% of
        the time but hugely right when it is right looks identical to noise in
        the mean alone."""
        return sum(1 for p in self.periods if p.ic > 0) / self.n if self.n else 0.0

    def by_year(self) -> dict[int, tuple[float, int]]:
        buckets: dict[int, list[float]] = {}
        for period in self.periods:
            buckets.setdefault(period.day.year, []).append(period.ic)
        return {y: (sum(v) / len(v), len(v)) for y, v in sorted(buckets.items())}


def forward_returns(
    histories: dict[str, list[PanelRow]], start: date, horizon: int
) -> dict[str, float]:
    """Return from `start` to `horizon` trading days later, per symbol.

    Indexed by each symbol's own trading days, so a stock that was suspended
    for a week is measured over its own next `horizon` sessions rather than
    being silently compared across a gap.
    """
    out: dict[str, float] = {}
    for symbol, history in histories.items():
        index = next((i for i, r in enumerate(history) if r.day == start), None)
        if index is None or index + horizon >= len(history):
            continue
        begin, finish = history[index].close, history[index + horizon].close
        if begin > 0 and finish > 0:
            out[symbol] = finish / begin - 1.0
    return out


def evaluate(
    rows: Sequence[PanelRow],
    feature: Feature,
    *,
    horizon: int = 21,
    step: int = 5,
    min_names: int = 30,
    min_turnover: float = 0.0,
) -> ICResult:
    """Compute the IC of `feature` at `horizon` trading days.

    `step` samples every Nth trading day. Consecutive daily cross-sections
    overlap almost completely at a 21-day horizon, so treating them as
    independent would inflate the t-statistic by roughly the square root of
    the overlap. Sampling every 5th day reduces that; it does not eliminate
    it, and the tear sheet says so rather than pretending otherwise.

    `min_turnover` (rupees) leaves out a name whose turnover on `day` is below
    it, the same rule `RankAndHold` applies, so a screen and the backtest after
    it judge the same stocks (ADR-112). 0 keeps every name.
    """
    histories = by_symbol(rows)
    days = trading_days(rows)
    periods: list[PeriodIC] = []
    skipped = 0

    for day in days[::step]:
        forwards = forward_returns(histories, day, horizon)
        if len(forwards) < min_names:
            continue

        xs: list[float] = []
        ys: list[float] = []
        for symbol, forward in forwards.items():
            history = histories[symbol]
            # Strictly up to and including `day` - the feature can physically
            # not see the window its own forward return is measured over.
            # Histories are oldest first, so a binary search finds the cut.
            visible = history[: bisect_right(history, day, key=lambda r: r.day)]
            if min_turnover and (not visible or visible[-1].turnover < min_turnover):
                continue
            value = feature(visible)
            if value is None:
                continue
            xs.append(value)
            ys.append(forward)

        if len(xs) < min_names:
            skipped += 1
            continue
        ic = spearman(xs, ys)
        if ic is not None:
            periods.append(PeriodIC(day=day, ic=ic, n=len(xs)))

    return ICResult(
        feature=feature.name,
        periods=periods,
        horizon_days=horizon,
        skipped_thin=skipped,
    )
