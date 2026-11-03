"""Ten seed features, each a pure function of one symbol's own history.

Pure on purpose. A feature that fetched its own data could reach for a date it
should not see, and no test would catch it — the lookahead firewall guards the
*read* path, so anything that bypasses reading bypasses the firewall too. Here
a feature receives a list of `PanelRow` ending at the evaluation date and can
physically see nothing else.

**Every feature returns None rather than a number when it lacks history.**
A 12-month momentum on nine months of data is not a smaller number, it is a
different quantity, and letting it through would silently fill the early part
of every backtest with a feature that means something else. Newly listed
stocks are exactly where that matters most, because they are also where the
most dramatic returns are.

The signs are chosen so that **higher is predicted to be better** for every
feature, which is what makes an IC comparable across them. Where the
literature's convention is the opposite — short-term reversal, volatility —
the value is negated here and the docstring says so.
"""

from __future__ import annotations

from collections.abc import Sequence
from itertools import pairwise

from eulerlab.features.base import TRADING_DAYS_PER_MONTH as TRADING_DAYS_PER_MONTH
from eulerlab.features.base import Feature as Feature
from eulerlab.features.base import FeatureFn as FeatureFn
from eulerlab.features.panel import PanelRow
from eulerlab.quality.robust import median


def _returns(history: Sequence[PanelRow]) -> list[float]:
    out: list[float] = []
    for previous, current in pairwise(history):
        if previous.close > 0:
            out.append(current.close / previous.close - 1.0)
    return out


def _total_return(history: Sequence[PanelRow], *, start: int, end: int) -> float | None:
    """Return between two points counted back from the end of `history`."""
    if len(history) < start + 1:
        return None
    first = history[-start - 1].close
    last = history[-end - 1].close if end else history[-1].close
    if first <= 0 or last <= 0:
        return None
    return last / first - 1.0


# --- momentum ---


def momentum_12_1(history: Sequence[PanelRow]) -> float | None:
    """Twelve-month return, skipping the most recent month.

    The skip is not a detail. Twelve-month momentum and one-month reversal
    point in opposite directions, so a naive 12-month return blends a
    predictive signal with its own opposite and reports the average, which is
    weaker than either. Skipping the last month is the standard construction
    for exactly that reason.
    """
    return _total_return(history, start=12 * TRADING_DAYS_PER_MONTH, end=1 * TRADING_DAYS_PER_MONTH)


def momentum_6_1(history: Sequence[PanelRow]) -> float | None:
    """Six-month return, skipping the most recent month."""
    return _total_return(history, start=6 * TRADING_DAYS_PER_MONTH, end=1 * TRADING_DAYS_PER_MONTH)


def reversal_1m(history: Sequence[PanelRow]) -> float | None:
    """*Negated* one-month return: recent losers are predicted to bounce.

    Negated so that, like every other feature here, higher means better
    expected return. Comparing a raw one-month return against the others would
    make a working signal look like a broken one purely from its sign.
    """
    raw = _total_return(history, start=1 * TRADING_DAYS_PER_MONTH, end=0)
    return None if raw is None else -raw


# --- risk ---


def low_volatility(history: Sequence[PanelRow]) -> float | None:
    """*Negated* dispersion of daily returns over three months.

    Uses median absolute deviation, not standard deviation, for the reason
    measured in `quality/robust.py`: a single spike dominates stdev, so a
    "high volatility" score would often be a statement about one day rather
    than about the stock.
    """
    rets = _returns(history[-3 * TRADING_DAYS_PER_MONTH :])
    if len(rets) < 20:
        return None
    centre = median(rets)
    return -median([abs(r - centre) for r in rets])


def max_drawdown(history: Sequence[PanelRow]) -> float | None:
    """*Negated* worst peak-to-trough fall over six months."""
    window = history[-6 * TRADING_DAYS_PER_MONTH :]
    if len(window) < 40:
        return None
    peak = window[0].close
    worst = 0.0
    for row in window:
        peak = max(peak, row.close)
        if peak > 0:
            worst = min(worst, row.close / peak - 1.0)
    return -abs(worst)


# --- liquidity and size ---


def turnover_liquidity(history: Sequence[PanelRow]) -> float | None:
    """Median daily turnover over three months, log-scaled.

    Log because turnover spans six orders of magnitude across the universe and
    a rank correlation would be unaffected, but any later linear use would be
    dominated by the largest names.
    """
    import math

    values = [r.turnover for r in history[-3 * TRADING_DAYS_PER_MONTH :] if r.turnover > 0]
    if len(values) < 20:
        return None
    return math.log(median(values))


def illiquidity_amihud(history: Sequence[PanelRow]) -> float | None:
    """*Negated* Amihud illiquidity: |return| per rupee of turnover.

    How far the price moves for a given amount of trading — a direct measure
    of impact, and the input Sprint 9's cost model will need. Negated so that
    more liquid scores higher.
    """
    window = history[-3 * TRADING_DAYS_PER_MONTH :]
    if len(window) < 21:
        return None
    ratios = [
        abs(current.close / previous.close - 1.0) / current.turnover
        for previous, current in pairwise(window)
        if previous.close > 0 and current.turnover > 0
    ]
    if len(ratios) < 20:
        return None
    return -median(ratios)


def small_size(history: Sequence[PanelRow]) -> float | None:
    """*Negated* log price as a crude size proxy.

    **This is a poor proxy and is included to be measured, not believed.**
    Real size is price times shares outstanding, and the share count is not in
    the bhavcopy. Price alone conflates a genuinely small company with one that
    merely has a low face value after a split. It is here because a feature
    library that only contains features I expect to work tells me nothing
    about the harness.
    """
    import math

    last = history[-1].close
    return None if last <= 0 else -math.log(last)


# --- shape ---


def price_to_52w_high(history: Sequence[PanelRow]) -> float | None:
    """Closeness to the 52-week high. Nearness has historically predicted
    continuation rather than exhaustion."""
    window = history[-12 * TRADING_DAYS_PER_MONTH :]
    if len(window) < 200:
        return None
    high = max(r.close for r in window)
    return None if high <= 0 else history[-1].close / high


def volume_trend(history: Sequence[PanelRow]) -> float | None:
    """Recent volume against its own three-month median.

    Attention: a stock trading well above its usual volume is being looked at
    for some reason the price may not have finished absorbing.
    """
    window = history[-3 * TRADING_DAYS_PER_MONTH :]
    if len(window) < 40:
        return None
    recent = [r.volume for r in window[-5:] if r.volume > 0]
    baseline = [r.volume for r in window if r.volume > 0]
    if len(recent) < 3 or len(baseline) < 20:
        return None
    base = median(baseline)
    return None if base <= 0 else median(recent) / base


LIBRARY: tuple[Feature, ...] = (
    Feature("momentum_12_1", momentum_12_1, "12-month return, skipping the last month", 253),
    Feature("momentum_6_1", momentum_6_1, "6-month return, skipping the last month", 148),
    Feature("reversal_1m", reversal_1m, "negated 1-month return", 22),
    Feature("low_volatility", low_volatility, "negated MAD of daily returns, 3m", 63),
    Feature("max_drawdown", max_drawdown, "negated worst 6-month drawdown", 126),
    Feature("turnover_liquidity", turnover_liquidity, "log median turnover, 3m", 63),
    Feature("illiquidity_amihud", illiquidity_amihud, "negated Amihud impact, 3m", 63),
    Feature("small_size", small_size, "negated log price (weak proxy)", 1),
    Feature("price_to_52w_high", price_to_52w_high, "close / 52-week high", 200),
    Feature("volume_trend", volume_trend, "5-day vs 3-month median volume", 63),
)

BY_NAME: dict[str, Feature] = {f.name: f for f in LIBRARY}
"""Every feature a card may name: the ten seeds, then the signals the engineering
agent coded for research cards and the operator merged (`features/coded`, ADR-127).
`LIBRARY` stays the seeds, which the tear sheets and reports iterate."""

# Imported last: each coded module imports `Feature` from this one.
from eulerlab.features import coded as _coded  # noqa: E402

BY_NAME.update(_coded.load(BY_NAME))
