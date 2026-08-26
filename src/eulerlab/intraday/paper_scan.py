"""Run a coded paper signal over real minute bars.

Separate from `scan.py` for one structural reason: Tweezer is a pure
within-session pattern, so its scanner hands `detect` a window sliced from the
current session. Several paper signals are **not** within-session — a gap needs
the previous session's close, and Zarattini's relative-volume screen needs
fourteen prior sessions' opening volume.

So the window here is all history up to the signal bar, and `_session_bars`
inside `papers.py` narrows to today where a signal wants that. The *trade* is
still session-scoped: `forward` stops at the session end, so nothing is carried
overnight and `bracket.run` closes flat exactly as before.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

from eulerlab.intraday import bracket, store
from eulerlab.intraday.bracket import Trade
from eulerlab.intraday.crypto_signals import CRYPTO_SIGNALS
from eulerlab.intraday.crypto_signals import Detect as Detect
from eulerlab.intraday.india import INDIA_SIGNALS
from eulerlab.intraday.papers import SIGNALS, PaperRules
from eulerlab.intraday.tweezer import Candle, Plan, Rejected, Rules


class _Signal(Protocol):
    """What the scanner needs from a signal, whichever module defined it.

    A Protocol rather than a shared base class: the equity paper signals and
    the crypto ones were written independently and share a shape, not a
    lineage. Forcing an ancestor on them would be asserting a relationship that
    does not exist.

    Declared as properties because both concrete signal types are frozen
    dataclasses, and an attribute in a Protocol demands a read-write member
    that a frozen instance cannot satisfy.
    """

    @property
    def id(self) -> str: ...

    @property
    def detect(self) -> Detect: ...


ALL_SIGNALS: dict[str, _Signal] = {**SIGNALS, **CRYPTO_SIGNALS, **INDIA_SIGNALS}
"""Every scannable signal. The India entries are separate ids sharing the US
`detect` functions — a new hypothesis about a different market, not a second
measurement of an existing one, so it gets its own registry entry and its own
trial accounting."""
"""Every coded intraday signal, whichever module defined it.

Merged here rather than in either module so neither has to import the other:
the equity paper signals and the crypto ones share a shape and nothing else.
"""

_CANDLES: dict[tuple[str, date, date, str], list[Candle]] = {}
"""Fetched bars, shared across signals.

Ten signals over twelve symbols fetched the same bars ten times, which is what
put a batch of the whole set past the job timeout. The bars for one symbol and
window are the same object whichever signal is asking, so they are read once.

Keyed by the exact window rather than the symbol, because a wider request is
not satisfiable from a narrower cached one and quietly returning the narrow
range would shorten a backtest without saying so.
"""


def candles_for(
    symbol: str, start: date, end: date, *, asset_class: str = "equity"
) -> list[Candle]:
    """Minute bars for one symbol and window, read once per process.

    The source is chosen by asset class rather than guessed from the symbol:
    NSE minute bars come from the Kite archive, crypto from the Binance one, US
    bars from the Alpaca one, and a symbol like `ADANIENT` versus `ADAUSDT`
    versus `AAPL` is not a reliable tell.

    `us` is the third source, and it is the one a paper's `recommended_class`
    usually wants: most of the coded signals cite studies run on US markets, and
    before it existed they were swept on NSE names instead — a different
    question than the one those papers answer.
    """
    key = (symbol, start, end, asset_class)
    if key not in _CANDLES:
        if asset_class == "crypto":
            from eulerlab.intraday import crypto_store

            _CANDLES[key] = crypto_store.fetch(symbol, start=start, end=end)
        elif asset_class == "us":
            from eulerlab.intraday import us_store

            _CANDLES[key] = us_store.fetch(symbol, start=start, end=end)
        else:
            _CANDLES[key] = store.fetch(symbol, start=start, end=end)
    return _CANDLES[key]


WARMUP_BARS = 80
"""Bars of history before the first evaluation.

Enough for the longest lookback any coded signal declares (the OU reference
window at 60, plus room for ATR). A signal that wants more says so itself by
returning a `warmup` rejection, which is counted rather than hidden.
"""


@dataclass
class SignalScan:
    """What one signal did on one symbol."""

    signal: str
    symbol: str
    candles: int = 0
    sessions: int = 0
    _session_dates: list[date] = field(default_factory=list)
    """Every session date the scan covered, recorded as the bounds are found.

    Kept because `sessions` is only a count, and a walk-forward split needs to
    know *which* days it is partitioning."""
    plans: int = 0
    trades: list[Trade] = field(default_factory=list)
    rejections: dict[str, int] = field(default_factory=dict)

    @property
    def filled(self) -> int:
        return sum(1 for t in self.trades if t.filled)

    @property
    def net_pnl(self) -> float:
        return sum(t.net_pnl() for t in self.trades)

    @property
    def wins(self) -> int:
        return sum(1 for t in self.trades if t.filled and t.net_pnl() > 0)

    def pnl_by_session(self) -> dict[date, float]:
        """Net P&L keyed by session date, zero for sessions that traded nothing.

        The dated form, which `session_pnl` flattens. Needed because a
        walk-forward split partitions *sessions*, and a bare list cannot say
        which session a number belongs to — the padding in `session_pnl` puts
        the zeros at the end rather than on the days that were actually flat,
        which is harmless for a Sharpe over the whole window and wrong for any
        subset of it.
        """
        by_day: dict[date, float] = dict.fromkeys(self.session_days(), 0.0)
        for trade in self.trades:
            if trade.entry_ts is None:
                continue
            day = trade.entry_ts.date()
            if day in by_day:
                by_day[day] += trade.net_pnl()
        return by_day

    def session_days(self) -> list[date]:
        """Every session date in the scan, trading or not."""
        return sorted({candle_day for candle_day in self._session_dates})

    def session_pnl(self) -> list[float]:
        """Net P&L per session, including sessions that traded nothing.

        The flat days matter. A signal that fires twice in 58 sessions and wins
        both has a very different return series from one that trades daily, and
        dropping the 56 zeros would report the second one's volatility for the
        first — inflating its Sharpe by roughly the square root of how rarely it
        trades.
        """
        by_day: dict[date, float] = {}
        for trade in self.trades:
            if trade.entry_ts is None:
                continue
            day = trade.entry_ts.date()
            by_day[day] = by_day.get(day, 0.0) + trade.net_pnl()

        if not self.sessions:
            return []
        # Sessions that traded, padded with zeros to the full session count.
        series = [by_day[day] for day in sorted(by_day)]
        return series + [0.0] * max(0, self.sessions - len(series))

    def sharpe(self, equity: float) -> float | None:
        """Annualised Sharpe of the per-session returns, or None if undefined.

        Returned as None rather than zero when there is nothing to measure —
        fewer than two sessions, or no variation at all. Zero is a finding
        ("no edge"); None is the absence of one, and the two must not be
        confused in a column that is read as evidence.

        Annualised at sqrt(252) on the session count, which assumes sessions are
        the independent unit. For an intraday strategy that closes flat every
        day that is closer to true than it is for most things annualised this
        way, but it is still an assumption and not a measurement.
        """
        series = self.session_pnl()
        if len(series) < 2 or equity <= 0:
            return None
        returns = [value / equity for value in series]
        spread = statistics.pstdev(returns)
        if spread <= 0:
            return None
        return (statistics.fmean(returns) / spread) * math.sqrt(252.0)


def scan_symbol(
    signal_id: str,
    symbol: str,
    *,
    start: date,
    end: date,
    rules: PaperRules | None = None,
    equity: float = 1_000_000.0,
    asset_class: str = "equity",
) -> SignalScan:
    """Evaluate one signal bar by bar across every session in the range.

    With no `rules` given, the signal runs on its **adopted** parameters — the
    ones a recorded sweep found beat the published defaults — falling back to
    the paper's own values where nothing was adopted. That is what makes an
    optimisation a change to the strategy rather than a report about it.

    A sweep passes `rules` explicitly for every candidate, so it is never
    reading its own previous winner as a starting point; each sweep measures the
    same grid against the same baseline.
    """
    signal = ALL_SIGNALS[signal_id]
    if rules is None:
        from eulerlab.intraday import tuned

        adopted = tuned.rules_for(signal_id)
        rules = adopted if isinstance(adopted, PaperRules) else PaperRules()
    candles = candles_for(symbol, start, end, asset_class=asset_class)
    out = SignalScan(signal=signal_id, symbol=symbol, candles=len(candles))
    if not candles:
        return out

    # Where each session starts and ends, so `forward` can be cut at the close
    # without scanning for it on every bar.
    bounds: list[tuple[int, int]] = []
    cursor = 0
    for index in range(1, len(candles) + 1):
        if index == len(candles) or candles[index].ts.date() != candles[cursor].ts.date():
            bounds.append((cursor, index))
            cursor = index
    out.sessions = len(bounds)
    out._session_dates = [candles[first].ts.date() for first, _ in bounds]

    bracket_rules = Rules()
    for first, last in bounds:
        index = max(first, WARMUP_BARS)
        while index < last - 1:
            outcome = signal.detect(candles[: index + 1], rules, equity)
            if isinstance(outcome, Rejected):
                out.rejections[outcome.reason] = out.rejections.get(outcome.reason, 0) + 1
                index += 1
                continue

            assert isinstance(outcome, Plan)
            out.plans += 1
            forward = candles[index + 1 : last]
            trade = bracket.run(outcome, forward, bracket_rules, asset_class=asset_class)
            out.trades.append(trade)
            # ONE trade per session, then move to the next one.
            #
            # Every signal coded here is a day-trade signal: the paper takes one
            # setup and is flat at the close. Stepping forward a couple of bars
            # instead let the same condition re-fire while it stayed true - an
            # opening-range breakout is "price is above the range high", which
            # remains true all afternoon. That produced 1,300 trades across 43
            # sessions on one symbol and a 150% two-month return, which is not a
            # result, it is the same move counted thirty times.
            break
    return out


def scan_many(
    signal_id: str,
    symbols: Sequence[str],
    *,
    start: date,
    end: date,
    rules: PaperRules | None = None,
    equity: float = 1_000_000.0,
    asset_class: str = "equity",
) -> list[SignalScan]:
    """Every symbol, one signal. Failures are skipped, never silently zeroed."""
    out: list[SignalScan] = []
    for symbol in symbols:
        try:
            out.append(
                scan_symbol(
                    signal_id,
                    symbol,
                    start=start,
                    end=end,
                    rules=rules,
                    equity=equity,
                    asset_class=asset_class,
                )
            )
        except (OSError, ValueError, KeyError):
            # A symbol whose bars cannot be read is absent from the result, not
            # a zero in it: a zero would read as "no setups found".
            continue
    return out
