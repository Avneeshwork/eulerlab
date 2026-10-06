"""What the instrument did while the strategy was trading it.

A backtest that reports `+2.6%` and nothing else is not a result, it is a
number. `orb_breakout` returns +2.6% over 58 sessions on QQQ; whether that is
worth anything depends entirely on what QQQ did over the same 58 sessions, and
until now nothing in this platform answered that.

The comparison is deliberately the **hardest one to beat that is still fair**:
buy the same instrument on the first traded day, hold it to the last, and pay
the same venue's costs on both legs. Not cash, not a risk-free rate, not a
broad index the strategy never traded — the thing the strategy actually chose
to trade, held passively.

### Why this specific benchmark and not an index

An index benchmark flatters an intraday signal on a single name: it measures
stock selection the strategy never claimed to do. Buy-and-hold of the same
instrument isolates the only claim being made — that *timing* the instrument
beats *holding* it. A strategy that cannot beat holding what it trades has not
demonstrated timing, whatever its Sharpe.

### What it deliberately does not adjust for

**Exposure.** A signal in the market 4% of the time and a buy-and-hold at 100%
are not risk-equivalent, and the naive comparison flatters the strategy on
risk-adjusted terms and the benchmark on absolute ones. Both figures are
reported — `exposure` is already on the report — rather than folded into one
"risk-adjusted excess" that hides which of the two is doing the work.

**Leverage.** Position sizes here come from a risk fraction, not from the
account being fully invested, so a strategy may hold notional well above or
below the benchmark's. Comparing return-on-account is the honest common
denominator and it is the one used.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from itertools import pairwise
from typing import Any

TRADING_DAYS = 252.0


@dataclass(frozen=True)
class Benchmark:
    """Buy-and-hold of the same instrument, over the same days."""

    symbol: str
    first_day: date | None
    last_day: date | None
    entry: float
    exit: float
    shares: int
    costs: float
    starting_cash: float
    equity: tuple[float, ...] = ()

    @property
    def net_pnl(self) -> float:
        return (self.exit - self.entry) * self.shares - self.costs

    @property
    def total_return(self) -> float:
        return self.net_pnl / self.starting_cash if self.starting_cash else 0.0

    @property
    def sharpe(self) -> float | None:
        """Annualised Sharpe of the held position, or None if undefined.

        Computed from the same per-session series the strategy's is, so the two
        numbers are produced the same way and can be subtracted.
        """
        if len(self.equity) < 2 or self.starting_cash <= 0:
            return None
        # `pairwise`, not `zip(x, x[1:], strict=True)` — the two slices differ in
        # length by one by construction, so strict zip raises every time. The
        # rest of this codebase already uses `pairwise` for exactly this.
        returns = [(b - a) / self.starting_cash for a, b in pairwise(self.equity)]
        spread = statistics.pstdev(returns)
        if spread <= 0:
            return None
        return (statistics.fmean(returns) / spread) * math.sqrt(TRADING_DAYS)

    @property
    def max_drawdown(self) -> float:
        peak = worst = 0.0
        for value in self.equity:
            peak = max(peak, value)
            if peak > 0:
                worst = min(worst, value / peak - 1.0)
        return worst


def hold(
    candles: Sequence[Any],
    *,
    symbol: str,
    asset_class: str,
    starting_cash: float,
    traded_days: set[date] | None = None,
) -> Benchmark | None:
    """Buy at the first traded session's open, sell at the last one's close.

    `traded_days` restricts the comparison to the sessions the strategy was
    actually measured over. Without it a benchmark computed on every fetched
    bar would include the warmup the strategy never traded — which is not a
    like-for-like comparison, and would flatter or punish the benchmark by
    whatever those extra days happened to do.
    """
    from eulerlab.costs.router import fill_cost
    from eulerlab.costs.schedule import Segment, Side

    usable = [
        candle for candle in candles if traded_days is None or candle.ts.date() in traded_days
    ]
    if len(usable) < 2:
        return None

    entry = usable[0].open
    exit_price = usable[-1].close
    if entry <= 0:
        return None

    # Fully invested, which is what "buy and hold" means. The strategy's own
    # sizing is risk-based and usually smaller; comparing return-on-account
    # rather than return-on-notional is what keeps that fair.
    shares = int(starting_cash // entry)
    if shares <= 0:
        return None

    first_day = usable[0].ts.date()
    last_day = usable[-1].ts.date()
    # Delivery, not intraday. This said neither and took the router's default,
    # which was intraday — for a position held for years. On NSE that is the
    # difference between Rs 412 and Rs 2,250 on a Rs 1M round trip, because
    # delivery STT is 0.1% on both sides against 0.025% on the sell alone. It
    # understated what holding costs, which flatters the benchmark and so
    # understates every strategy measured against it.
    costs = fill_cost(
        venue=asset_class,
        price=entry,
        quantity=shares,
        side=Side.BUY,
        day=first_day,
        segment=Segment.EQUITY_DELIVERY,
    ) + fill_cost(
        venue=asset_class,
        price=exit_price,
        quantity=shares,
        side=Side.SELL,
        day=last_day,
        segment=Segment.EQUITY_DELIVERY,
    )

    # Marked at each session's close, so the drawdown is the one a holder
    # actually lived through rather than the two endpoints.
    by_day: dict[date, float] = {}
    for candle in usable:
        by_day[candle.ts.date()] = candle.close
    equity = tuple(
        starting_cash + (close - entry) * shares for _day, close in sorted(by_day.items())
    )

    return Benchmark(
        symbol=symbol,
        first_day=first_day,
        last_day=last_day,
        entry=entry,
        exit=exit_price,
        shares=shares,
        costs=costs,
        starting_cash=starting_cash,
        equity=equity,
    )


# --- the market, for the Strategies table -------------------------------------


def _nifty_closes() -> list[tuple[date, float]]:
    """NIFTYBEES closes from the panel, chained across its 2019 1:10 split.

    Read once per process and per panel file version. The ETF is the investable
    Nifty 50, so "what the market did" on the Strategies page is what holding
    it did, before costs.
    """
    import json

    from eulerlab.features.panel import PANEL_PATH

    if not PANEL_PATH.exists():
        return []
    stamp = PANEL_PATH.stat().st_mtime_ns
    cached = _NIFTY_CACHE.get(stamp)
    if cached is not None:
        return cached
    raw: list[tuple[date, float]] = []
    with PANEL_PATH.open(encoding="utf-8") as handle:
        for line in handle:
            if '"s": "NIFTYBEES"' in line:
                row = json.loads(line)
                raw.append((date.fromisoformat(row["d"]), float(row["c"])))
    raw.sort()
    chained: list[tuple[date, float]] = []
    level = 1.0
    for index, (day, close) in enumerate(raw):
        if index:
            ratio = close / raw[index - 1][1]
            level *= 10 * ratio if ratio < 0.2 else ratio
        chained.append((day, level))
    _NIFTY_CACHE.clear()
    _NIFTY_CACHE[stamp] = chained
    return chained


_NIFTY_CACHE: dict[int, list[tuple[date, float]]] = {}


def nifty_return(start: date, end: date) -> float | None:
    """NIFTYBEES held from the first close on or after `start` to the last on
    or before `end`, before costs. None when the panel does not cover it."""
    series = [(d, v) for d, v in _nifty_closes() if start <= d <= end]
    if len(series) < 2:
        return None
    return series[-1][1] / series[0][1] - 1.0
