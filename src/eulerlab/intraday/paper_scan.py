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

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

from eulerlab.intraday import bracket, store
from eulerlab.intraday.bracket import Trade
from eulerlab.intraday.crypto_signals import CRYPTO_SIGNALS
from eulerlab.intraday.crypto_signals import Detect as Detect
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


ALL_SIGNALS: dict[str, _Signal] = {**SIGNALS, **CRYPTO_SIGNALS}
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
    NSE minute bars come from the Kite archive, crypto from the Binance one,
    and a symbol like `ADANIENT` versus `ADAUSDT` is not a reliable tell.
    """
    key = (symbol, start, end, asset_class)
    if key not in _CANDLES:
        if asset_class == "crypto":
            from eulerlab.intraday import crypto_store

            _CANDLES[key] = crypto_store.fetch(symbol, start=start, end=end)
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
    """Evaluate one signal bar by bar across every session in the range."""
    signal = ALL_SIGNALS[signal_id]
    rules = rules or PaperRules()
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
            trade = bracket.run(outcome, forward, bracket_rules)
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
