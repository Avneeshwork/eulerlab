"""Tweezer Bottom — an intraday bullish reversal setup, ported to this project.

The rules are the operator's, restated here exactly: two adjacent candles whose
lows match, the first bearish and the second bullish, in a short-term downtrend,
near a support level, with volatility, trend strength and RSI all inside stated
bands. Entry above the first candle's high, stop below the pattern, targets at
2R and 3R, position split in two.

**Why this is not a `Strategy` subclass.** Every other strategy in this project
implements `target_weights(view) -> dict[str, float]` and is executed by the
Tier B engine at the daily close. This one cannot be expressed that way, and
pretending otherwise would be the exact failure `CLAUDE.md` warns about — one
interface that quietly means different things in different places.

Four properties make it a different animal:

- **It is intraday.** The pattern is minute candles, and the strategy closes
  everything before the session ends. Daily bars cannot represent it.
- **Entry is conditional.** A buy-stop above C1's high that may never trigger.
  Target weights have no way to say "only if it trades through this price".
- **The exit is a bracket.** Stop loss, two take-profits, a stop moved to
  breakeven when the first fills, and a trailing stop after 1.5R. A weight is a
  single number and holds none of that.
- **Position size comes from risk, not from a weight.** Shares are
  `1% of equity / R`, which depends on where the stop is.

So the pattern detection and the trade plan live here as pure functions, and
`bracket.py` executes them. The daily cross-sectional engine is untouched.

**What this shares with the rest of the project**, deliberately: the same cost
model, the same instrument identity, and the same rule that a decision may only
use bars at or before the decision bar. `detect` takes a window ending at the
signal candle and physically cannot see past it — the same firewall property as
`MarketView`, enforced the same structural way.

**Not yet run on real data.** The minute store is mirrored to B2 and pruned
locally, so this has been validated against hand-built candles only. Recorded
as S-023.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from eulerlab.features.indicators import (
    adx,
    atr,
    body_ratio,
    is_bearish,
    is_bullish,
    range_pct,
    rsi,
    sma,
)

IST = ZoneInfo("Asia/Kolkata")
"""Market time. Candle timestamps are tz-aware for the reason Sprint 4 learned
the hard way: a naive timestamp silently means whatever the reading machine's
locale says, and an intraday strategy with a session cutoff cannot afford that."""


@dataclass(frozen=True)
class Candle:
    """One minute bar. Raw exchange prices, same convention as `PanelRow`."""

    ts: datetime
    """Tz-aware, in IST. A naive value is a bug, not a shortcut."""
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class Rules:
    """Every threshold, in one place and none of them buried in the logic.

    Separated for the same reason `mandate.yaml` is separate from `gates.py`: a
    threshold that lives inside a condition gets tuned as a side effect of
    reading the code, and nobody can see it happen.
    """

    c1_body_ratio_min: float = 0.30
    c2_body_ratio_min: float = 0.60
    min_candle_range_pct: float = 0.05
    low_diff_tolerance_pct: float = 0.15
    sma_trend_period: int = 20
    htf_sma_period: int = 80
    swing_lookback: int = 10
    support_zone_max_dist_pct: float = 0.5
    atr_period: int = 14
    atr_min_pct: float = 0.3
    adx_period: int = 14
    adx_min: float = 25.0
    adx_max: float = 50.0
    rsi_period: int = 14
    rsi_min: float = 25.0
    rsi_max: float = 40.0
    min_risk_pct: float = 1.0
    max_risk_pct: float = 1.5
    min_rr_ratio: float = 1.5
    risk_per_trade: float = 0.01
    trail_activate_r: float = 1.5
    trail_giveback: float = 0.005


@dataclass(frozen=True)
class Plan:
    """A fully specified trade, before anything has happened.

    Frozen and complete: entry, stop, both targets, both sizes. Nothing is
    decided later, so a plan can be inspected, logged and compared against what
    actually filled.
    """

    signal_ts: datetime
    entry: float
    stop: float
    target_1: float
    target_2: float
    r: float
    shares_1: int
    shares_2: int
    risk_pct: float

    @property
    def shares(self) -> int:
        return self.shares_1 + self.shares_2


@dataclass(frozen=True)
class Rejected:
    """Why a candidate was not taken. Named so a run can be audited.

    Returned rather than a bare `None`, because "no trade today" and "no trade
    because ADX was 51" are different facts, and only the second tells you
    whether the filter is doing anything.
    """

    reason: str
    detail: str = ""


def _series(window: Sequence[Candle]) -> tuple[list[float], list[float], list[float]]:
    return (
        [c.high for c in window],
        [c.low for c in window],
        [c.close for c in window],
    )


def detect(window: Sequence[Candle], rules: Rules, *, equity: float) -> Plan | Rejected:
    """Evaluate the last two candles of `window` as a Tweezer Bottom.

    `window` ends at the signal candle (C2). Nothing after it is present, so
    this cannot look ahead — the same structural firewall the daily engine gets
    from `MarketView`, for the same reason.
    """
    needed = max(rules.htf_sma_period, rules.swing_lookback + 2, rules.adx_period * 2)
    if len(window) < needed:
        return Rejected("warmup", f"{len(window)} candles, need {needed}")

    c1, c2 = window[-2], window[-1]

    # --- Step 2: the pattern ---
    c1_range = c1.high - c1.low
    c2_range = c2.high - c2.low
    if c1_range <= 0 or c2_range <= 0:
        return Rejected("no range", "a candle with no range has no shape")

    if not is_bearish(c1.open, c1.close):
        return Rejected("c1 not bearish")
    if body_ratio(c1.open, c1.high, c1.low, c1.close) < rules.c1_body_ratio_min:
        return Rejected("c1 body too small")
    if range_pct(c1.high, c1.low, c1.close) < rules.min_candle_range_pct:
        return Rejected("c1 range too small")

    if not is_bullish(c2.open, c2.close):
        return Rejected("c2 not bullish")
    if body_ratio(c2.open, c2.high, c2.low, c2.close) < rules.c2_body_ratio_min:
        return Rejected("c2 body too small")
    if range_pct(c2.high, c2.low, c2.close) < rules.min_candle_range_pct:
        return Rejected("c2 range too small")

    if c1.low <= 0:
        return Rejected("bad price")
    low_diff_pct = abs(c1.low - c2.low) / c1.low * 100.0
    if low_diff_pct > rules.low_diff_tolerance_pct:
        return Rejected("lows do not match", f"{low_diff_pct:.3f}% apart")

    pattern_low = min(c1.low, c2.low)

    # --- Step 3: context ---
    highs, lows, closes = _series(window)

    trend = sma(closes, rules.sma_trend_period)
    sma_now, sma_prev = trend[-1], trend[-2]
    if sma_now is None or sma_prev is None:
        return Rejected("warmup", "trend average not ready")
    if c2.close >= sma_now or sma_now >= sma_prev:
        return Rejected("not in a downtrend")

    # The swing low over the `swing_lookback` candles BEFORE C1. The slice ends
    # at -2 so neither pattern candle can define the level it is tested against.
    swing_window = lows[-(rules.swing_lookback + 2) : -2]
    if not swing_window:
        return Rejected("warmup", "no swing window")
    swing_low = min(swing_window)
    if swing_low <= 0:
        return Rejected("bad price")
    if abs(c2.low - swing_low) / swing_low * 100.0 > rules.support_zone_max_dist_pct:
        return Rejected("not at support")

    atr_now = atr(highs, lows, closes, rules.atr_period)[-1]
    if atr_now is None:
        return Rejected("warmup", "ATR not ready")
    if (atr_now / c2.close) * 100.0 < rules.atr_min_pct:
        return Rejected("too quiet", f"ATR {atr_now / c2.close * 100:.3f}%")

    adx_now = adx(highs, lows, closes, rules.adx_period)[-1]
    if adx_now is None:
        return Rejected("warmup", "ADX not ready")
    if not (rules.adx_min <= adx_now < rules.adx_max):
        return Rejected("trend strength outside band", f"ADX {adx_now:.1f}")

    rsi_now = rsi(closes, rules.rsi_period)[-1]
    if rsi_now is None:
        return Rejected("warmup", "RSI not ready")
    if not (rules.rsi_min <= rsi_now <= rules.rsi_max):
        return Rejected("RSI outside band", f"RSI {rsi_now:.1f}")

    # --- Steps 5-8: the trade ---
    entry = c1.high
    if entry <= 0:
        return Rejected("bad price")

    stop_buffer = max(0.001, atr_now / entry)
    stop = pattern_low * (1.0 - stop_buffer)
    r = entry - stop
    if r <= 0:
        return Rejected("stop above entry")

    risk_pct = r / entry * 100.0
    if not (rules.min_risk_pct <= risk_pct <= rules.max_risk_pct):
        return Rejected("risk outside band", f"{risk_pct:.2f}%")

    target_1 = entry + 2.0 * r
    target_2 = entry + 3.0 * r
    if (target_2 - entry) / r < rules.min_rr_ratio:
        return Rejected("reward too small")

    shares = math.floor((equity * rules.risk_per_trade) / r)
    shares = min(shares, math.floor(equity / entry))
    if shares < 1:
        return Rejected("size rounds to zero")

    first = shares // 2 if shares >= 2 else 0
    second = shares - first

    return Plan(
        signal_ts=c2.ts,
        entry=entry,
        stop=stop,
        target_1=target_1,
        target_2=target_2,
        r=r,
        shares_1=first,
        shares_2=second,
        risk_pct=risk_pct,
    )
