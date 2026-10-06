"""Streaming indicators for the strategy builder.

Each indicator is fed one bar at a time and answers with its value on that bar,
or `None` while it is still warming up. Streaming rather than computed over a
whole series because a builder strategy is asked for weights once per trading
day over a history that grows by one bar each time: recomputing every series
from the start on every call is quadratic in the window, and measured on a
hundred names over 800 days that is minutes per backtest. Fed incrementally it
is linear (see `compile.py` for when the cache is thrown away).

The definitions are the textbook ones, chosen to match what a trader would get
from a charting package, and each is stated where it is implemented:

- RSI and ATR use Wilder's smoothing (alpha = 1/period), seeded with the simple
  mean of the first `period` values — Wilder (1978), and what TradingView's
  `ta.rsi` / `ta.atr` compute.
- EMA uses alpha = 2/(period+1), seeded with the SMA of the first `period`.
- Bollinger bands use the population standard deviation, as Bollinger does.
- Donchian high/low are over the **previous** `period` bars, excluding the
  current one, so "close crosses above Donchian high" is a breakout rather than
  a condition that can never be true.
- Volatility is the sample standard deviation of daily simple returns,
  annualised by sqrt(252).
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

TRADING_DAYS = 252


@dataclass(frozen=True)
class Bar:
    open: float
    high: float
    low: float
    close: float
    volume: float
    turnover: float


class Indicator:
    """One running series. `update` returns the value on the bar just fed."""

    def update(self, bar: Bar) -> float | None:  # pragma: no cover - interface
        raise NotImplementedError


class _Field(Indicator):
    def __init__(self, pick: Callable[[Bar], float]) -> None:
        self.pick = pick

    def update(self, bar: Bar) -> float | None:
        return self.pick(bar)


class _Window:
    """A fixed-length window with a running sum."""

    def __init__(self, period: int) -> None:
        self.period = period
        self.values: deque[float] = deque(maxlen=period)
        self.total = 0.0

    def push(self, value: float) -> None:
        if len(self.values) == self.period:
            self.total -= self.values[0]
        self.values.append(value)
        self.total += value

    @property
    def full(self) -> bool:
        return len(self.values) == self.period

    def mean(self) -> float:
        return self.total / len(self.values)


class SMA(Indicator):
    def __init__(self, period: int, pick: Callable[[Bar], float] = lambda b: b.close) -> None:
        self.window = _Window(period)
        self.pick = pick

    def update(self, bar: Bar) -> float | None:
        self.window.push(self.pick(bar))
        return self.window.mean() if self.window.full else None


class _EMA:
    """EMA over a stream of numbers, seeded with the SMA of the first `period`."""

    def __init__(self, period: int) -> None:
        self.period = period
        self.alpha = 2.0 / (period + 1)
        self.seed: list[float] = []
        self.value: float | None = None

    def push(self, x: float) -> float | None:
        if self.value is None:
            self.seed.append(x)
            if len(self.seed) == self.period:
                self.value = sum(self.seed) / self.period
            return self.value
        self.value += self.alpha * (x - self.value)
        return self.value


class EMA(Indicator):
    def __init__(self, period: int) -> None:
        self.ema = _EMA(period)

    def update(self, bar: Bar) -> float | None:
        return self.ema.push(bar.close)


class _Wilder:
    """Wilder smoothing, seeded with the mean of the first `period` values."""

    def __init__(self, period: int) -> None:
        self.period = period
        self.seed: list[float] = []
        self.value: float | None = None

    def push(self, x: float) -> float | None:
        if self.value is None:
            self.seed.append(x)
            if len(self.seed) == self.period:
                self.value = sum(self.seed) / self.period
            return self.value
        self.value = (self.value * (self.period - 1) + x) / self.period
        return self.value


class RSI(Indicator):
    def __init__(self, period: int) -> None:
        self.gain = _Wilder(period)
        self.loss = _Wilder(period)
        self.previous: float | None = None

    def update(self, bar: Bar) -> float | None:
        if self.previous is None:
            self.previous = bar.close
            return None
        change = bar.close - self.previous
        self.previous = bar.close
        gain = self.gain.push(max(change, 0.0))
        loss = self.loss.push(max(-change, 0.0))
        if gain is None or loss is None:
            return None
        if loss == 0.0:
            return 100.0 if gain > 0.0 else 50.0
        return 100.0 - 100.0 / (1.0 + gain / loss)


class MACD(Indicator):
    """`part` is "line", "signal" or "hist"."""

    def __init__(self, fast: int, slow: int, signal: int, part: str) -> None:
        self.fast = _EMA(fast)
        self.slow = _EMA(slow)
        self.signal = _EMA(signal)
        self.part = part

    def update(self, bar: Bar) -> float | None:
        fast = self.fast.push(bar.close)
        slow = self.slow.push(bar.close)
        if fast is None or slow is None:
            return None
        line = fast - slow
        signal = self.signal.push(line)
        if self.part == "line":
            return line
        if signal is None:
            return None
        return signal if self.part == "signal" else line - signal


class Bollinger(Indicator):
    """`part` is "upper", "middle" or "lower"."""

    def __init__(self, period: int, width: float, part: str) -> None:
        self.window: deque[float] = deque(maxlen=period)
        self.period = period
        self.width = width
        self.part = part

    def update(self, bar: Bar) -> float | None:
        self.window.append(bar.close)
        if len(self.window) < self.period:
            return None
        mean = sum(self.window) / self.period
        sd = math.sqrt(sum((x - mean) ** 2 for x in self.window) / self.period)
        if self.part == "middle":
            return mean
        return mean + self.width * sd if self.part == "upper" else mean - self.width * sd


class ATR(Indicator):
    def __init__(self, period: int, percent: bool = False) -> None:
        self.wilder = _Wilder(period)
        self.previous: float | None = None
        self.percent = percent

    def update(self, bar: Bar) -> float | None:
        if self.previous is None:
            true_range = bar.high - bar.low
        else:
            true_range = max(
                bar.high - bar.low, abs(bar.high - self.previous), abs(bar.low - self.previous)
            )
        self.previous = bar.close
        value = self.wilder.push(true_range)
        if value is None:
            return None
        if self.percent:
            return 100.0 * value / bar.close if bar.close > 0 else None
        return value


class Donchian(Indicator):
    """Highest high or lowest low of the previous `period` bars, today excluded."""

    def __init__(self, period: int, high: bool) -> None:
        self.window: deque[float] = deque(maxlen=period)
        self.period = period
        self.high = high

    def update(self, bar: Bar) -> float | None:
        value: float | None = None
        if len(self.window) == self.period:
            value = max(self.window) if self.high else min(self.window)
        self.window.append(bar.high if self.high else bar.low)
        return value


class ROC(Indicator):
    """Percent change over `period` bars."""

    def __init__(self, period: int) -> None:
        self.window: deque[float] = deque(maxlen=period + 1)

    def update(self, bar: Bar) -> float | None:
        self.window.append(bar.close)
        if len(self.window) < (self.window.maxlen or 0):
            return None
        base = self.window[0]
        return 100.0 * (bar.close / base - 1.0) if base > 0 else None


class Volatility(Indicator):
    """Annualised standard deviation of daily returns, in percent."""

    def __init__(self, period: int) -> None:
        self.returns: deque[float] = deque(maxlen=period)
        self.period = period
        self.previous: float | None = None

    def update(self, bar: Bar) -> float | None:
        if self.previous is not None and self.previous > 0:
            self.returns.append(bar.close / self.previous - 1.0)
        self.previous = bar.close
        if len(self.returns) < self.period:
            return None
        mean = sum(self.returns) / self.period
        variance = sum((r - mean) ** 2 for r in self.returns) / (self.period - 1)
        return 100.0 * math.sqrt(variance * TRADING_DAYS)


@dataclass(frozen=True)
class Param:
    name: str
    label: str
    default: float
    minimum: float
    maximum: float
    integer: bool = True


@dataclass(frozen=True)
class Definition:
    """What the interface shows and how to build the running series."""

    name: str
    label: str
    group: str
    description: str
    params: tuple[Param, ...]
    make: Callable[[dict[str, float]], Indicator]
    warmup: Callable[[dict[str, float]], int]
    unit: str = "price"
    """"price", "percent", "ratio" or "volume" — which operands it is
    meaningful to compare it with. The interface warns on a mismatch rather
    than refusing, because "RSI above SMA(close)" is legal arithmetic."""

    tags: tuple[str, ...] = field(default_factory=tuple)

    def to_row(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "group": self.group,
            "description": self.description,
            "unit": self.unit,
            "params": [
                {
                    "name": p.name,
                    "label": p.label,
                    "default": p.default,
                    "min": p.minimum,
                    "max": p.maximum,
                    "integer": p.integer,
                }
                for p in self.params
            ],
        }


def _p(name: str, label: str, default: float, lo: float, hi: float, integer: bool = True) -> Param:
    return Param(name, label, default, lo, hi, integer)


PERIOD = _p("period", "Period", 14, 1, 400)


def _i(params: dict[str, float], key: str) -> int:
    return int(params[key])


DEFINITIONS: tuple[Definition, ...] = (
    Definition(
        "close",
        "Close",
        "Price",
        "The day's closing price.",
        (),
        lambda p: _Field(lambda b: b.close),
        lambda p: 0,
    ),
    Definition(
        "open",
        "Open",
        "Price",
        "The day's opening price. Falls back to the close where the panel has no open.",
        (),
        lambda p: _Field(lambda b: b.open),
        lambda p: 0,
    ),
    Definition(
        "high",
        "High",
        "Price",
        "The day's high. Falls back to the close where not recorded.",
        (),
        lambda p: _Field(lambda b: b.high),
        lambda p: 0,
    ),
    Definition(
        "low",
        "Low",
        "Price",
        "The day's low. Falls back to the close where not recorded.",
        (),
        lambda p: _Field(lambda b: b.low),
        lambda p: 0,
    ),
    Definition(
        "sma",
        "SMA",
        "Trend",
        "Simple moving average of the close.",
        (_p("period", "Period", 50, 1, 400),),
        lambda p: SMA(_i(p, "period")),
        lambda p: _i(p, "period"),
    ),
    Definition(
        "ema",
        "EMA",
        "Trend",
        "Exponential moving average of the close, alpha 2/(period+1).",
        (_p("period", "Period", 20, 1, 400),),
        lambda p: EMA(_i(p, "period")),
        lambda p: _i(p, "period"),
    ),
    Definition(
        "macd_line",
        "MACD line",
        "Trend",
        "EMA(fast) minus EMA(slow) of the close.",
        (
            _p("fast", "Fast", 12, 1, 100),
            _p("slow", "Slow", 26, 2, 200),
            _p("signal", "Signal", 9, 1, 100),
        ),
        lambda p: MACD(_i(p, "fast"), _i(p, "slow"), _i(p, "signal"), "line"),
        lambda p: _i(p, "slow"),
        unit="ratio",
    ),
    Definition(
        "macd_signal",
        "MACD signal",
        "Trend",
        "EMA(signal) of the MACD line.",
        (
            _p("fast", "Fast", 12, 1, 100),
            _p("slow", "Slow", 26, 2, 200),
            _p("signal", "Signal", 9, 1, 100),
        ),
        lambda p: MACD(_i(p, "fast"), _i(p, "slow"), _i(p, "signal"), "signal"),
        lambda p: _i(p, "slow") + _i(p, "signal"),
        unit="ratio",
    ),
    Definition(
        "macd_hist",
        "MACD histogram",
        "Trend",
        "MACD line minus its signal line.",
        (
            _p("fast", "Fast", 12, 1, 100),
            _p("slow", "Slow", 26, 2, 200),
            _p("signal", "Signal", 9, 1, 100),
        ),
        lambda p: MACD(_i(p, "fast"), _i(p, "slow"), _i(p, "signal"), "hist"),
        lambda p: _i(p, "slow") + _i(p, "signal"),
        unit="ratio",
    ),
    Definition(
        "rsi",
        "RSI",
        "Momentum",
        "Wilder's relative strength index, 0 to 100.",
        (_p("period", "Period", 14, 2, 100),),
        lambda p: RSI(_i(p, "period")),
        lambda p: _i(p, "period") + 1,
        unit="percent",
    ),
    Definition(
        "roc",
        "ROC %",
        "Momentum",
        "Percent change in the close over the period.",
        (_p("period", "Period", 20, 1, 400),),
        lambda p: ROC(_i(p, "period")),
        lambda p: _i(p, "period") + 1,
        unit="percent",
    ),
    Definition(
        "bb_upper",
        "Bollinger upper",
        "Volatility",
        "SMA plus width standard deviations.",
        (
            _p("period", "Period", 20, 2, 400),
            _p("width", "Width (sd)", 2.0, 0.5, 5.0, integer=False),
        ),
        lambda p: Bollinger(_i(p, "period"), float(p["width"]), "upper"),
        lambda p: _i(p, "period"),
    ),
    Definition(
        "bb_middle",
        "Bollinger middle",
        "Volatility",
        "The SMA the bands are drawn around.",
        (
            _p("period", "Period", 20, 2, 400),
            _p("width", "Width (sd)", 2.0, 0.5, 5.0, integer=False),
        ),
        lambda p: Bollinger(_i(p, "period"), float(p["width"]), "middle"),
        lambda p: _i(p, "period"),
    ),
    Definition(
        "bb_lower",
        "Bollinger lower",
        "Volatility",
        "SMA minus width standard deviations.",
        (
            _p("period", "Period", 20, 2, 400),
            _p("width", "Width (sd)", 2.0, 0.5, 5.0, integer=False),
        ),
        lambda p: Bollinger(_i(p, "period"), float(p["width"]), "lower"),
        lambda p: _i(p, "period"),
    ),
    Definition(
        "atr",
        "ATR",
        "Volatility",
        "Wilder's average true range, in price.",
        (_p("period", "Period", 14, 1, 200),),
        lambda p: ATR(_i(p, "period")),
        lambda p: _i(p, "period"),
    ),
    Definition(
        "atr_pct",
        "ATR %",
        "Volatility",
        "ATR as a percent of the close.",
        (_p("period", "Period", 14, 1, 200),),
        lambda p: ATR(_i(p, "period"), percent=True),
        lambda p: _i(p, "period"),
        unit="percent",
    ),
    Definition(
        "volatility",
        "Volatility %",
        "Volatility",
        "Annualised standard deviation of daily returns.",
        (_p("period", "Period", 20, 2, 400),),
        lambda p: Volatility(_i(p, "period")),
        lambda p: _i(p, "period") + 1,
        unit="percent",
    ),
    Definition(
        "donchian_high",
        "Highest high",
        "Breakout",
        "Highest high of the previous N bars, today excluded. 252 is the 52-week high.",
        (_p("period", "Period", 20, 1, 400),),
        lambda p: Donchian(_i(p, "period"), high=True),
        lambda p: _i(p, "period") + 1,
    ),
    Definition(
        "donchian_low",
        "Lowest low",
        "Breakout",
        "Lowest low of the previous N bars, today excluded.",
        (_p("period", "Period", 20, 1, 400),),
        lambda p: Donchian(_i(p, "period"), high=False),
        lambda p: _i(p, "period") + 1,
    ),
    Definition(
        "volume",
        "Volume",
        "Volume",
        "Shares or units traded that day.",
        (),
        lambda p: _Field(lambda b: b.volume),
        lambda p: 0,
        unit="volume",
    ),
    Definition(
        "volume_sma",
        "Average volume",
        "Volume",
        "Simple average of volume.",
        (_p("period", "Period", 20, 1, 400),),
        lambda p: SMA(_i(p, "period"), pick=lambda b: b.volume),
        lambda p: _i(p, "period"),
        unit="volume",
    ),
    Definition(
        "turnover_sma",
        "Average turnover",
        "Volume",
        "Simple average of traded value, in currency.",
        (_p("period", "Period", 20, 1, 400),),
        lambda p: SMA(_i(p, "period"), pick=lambda b: b.turnover),
        lambda p: _i(p, "period"),
        unit="volume",
    ),
)

BY_NAME: dict[str, Definition] = {d.name: d for d in DEFINITIONS}
