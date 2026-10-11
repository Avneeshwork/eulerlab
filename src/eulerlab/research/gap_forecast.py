"""Mukherjee & Mandal (2025), "Price Action Meets Volatility: A Dual-Factor
Strategy for Nifty Gap Forecasting" — the paper as written, then as a trade.

IJFMR 7(4), read in full on 2026-10-11 (research 072). The paper asks whether
two things known at a day's close predict the direction of the next morning's
opening gap in the Nifty 50:

- the **candle**: GREEN when the close is above the open, RED when below;
- the **change in India VIX**: its close minus its open *that day*.

and scores three models by how often the gap went the predicted way:

1. VIX only — VIX up predicts a gap down, VIX down a gap up;
2. candle only — GREEN predicts a gap up, RED a gap down;
3. both — GREEN with VIX down predicts a gap up, RED with VIX up a gap down;
   every other day is "inconclusive" and left out.

`tables()` reproduces its Tables 5, 6 and 7 from this project's index history.

### What the paper does not do, and this does

**It compares every rate with 50%.** The Nifty gaps up on about two days in
three whatever happened the day before, so "GREEN and VIX down is right 69.6%
of the time" says little until it is set against that. Every row here carries
the base rate of the direction it predicts, the lift over it, and a
two-proportion z-test of signal days against all other days.

**It measures accuracy on the index, which cannot be traded.** The index's open
is built from its constituents' first prints and its close from a 30-minute
average, which leans its gaps upward (research 064). `trade()` holds the
near-month Nifty future from the signal day's close to the next open — two
real trades in one contract — long when a gap up is predicted and short when a
gap down is, after the platform's futures costs.

**Its VIX change is close minus open.** `session_studies.calm_rise`, written
from a summary before the paper was read, used close against the previous
close. Both are here (`VixChange`); `agreement()` counts how often they differ.

These are calculations, not engine runs: the trade is from a close to the next
open, which the daily engines cannot express. No `Strategy`, no trial.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from itertools import pairwise
from typing import Any

from eulerlab.research.session_studies import Overnight, round_trip_cost, summarise


class Model(StrEnum):
    VIX = "vix"
    CANDLE = "candle"
    JOINT = "joint"


class VixChange(StrEnum):
    INTRADAY = "close_minus_open"
    """The paper's definition: VIX close minus VIX open, the same day."""
    CLOSE_TO_CLOSE = "close_minus_previous_close"
    """What `session_studies` used before the paper was read."""


UP, DOWN = "up", "down"


@dataclass(frozen=True)
class Day:
    """One session of the Nifty 50 with India VIX beside it."""

    day: date
    open: float
    close: float
    vix_open: float
    vix_close: float
    vix_previous_close: float | None = None

    @property
    def candle(self) -> str | None:
        """GREEN ("up") or RED ("down"); None for a day that closed where it opened."""
        if self.close > self.open:
            return UP
        if self.close < self.open:
            return DOWN
        return None

    def vix_move(self, definition: VixChange = VixChange.INTRADAY) -> str | None:
        """Whether VIX rose or fell, by the chosen definition; None when flat or unknown."""
        if definition is VixChange.INTRADAY:
            base = self.vix_open
        else:
            if self.vix_previous_close is None:
                return None
            base = self.vix_previous_close
        if self.vix_close > base:
            return UP
        if self.vix_close < base:
            return DOWN
        return None


def predict(model: Model, day: Day, definition: VixChange = VixChange.INTRADAY) -> str | None:
    """The gap direction the model expects after `day`, or None for no signal.

    # ASSUMPTION: the day's Nifty and VIX closes are known at the moment of
    # trading at the close. In practice the order goes in a minute or two
    # before, on values that are almost final. See A-046.
    """
    candle, vix = day.candle, day.vix_move(definition)
    if model is Model.CANDLE:
        return candle
    if model is Model.VIX:
        if vix is None:
            return None
        return DOWN if vix == UP else UP
    if candle == UP and vix == DOWN:
        return UP
    if candle == DOWN and vix == UP:
        return DOWN
    return None


def gap(today_close: float, next_open: float) -> str | None:
    if next_open > today_close:
        return UP
    if next_open < today_close:
        return DOWN
    return None


# --- the paper's tables ---------------------------------------------------------


@dataclass(frozen=True)
class Row:
    """One line of the paper's Tables 5-7, with the comparison it leaves out."""

    signal: str
    count: int
    success: int
    base_rate: float
    """How often the gap went this row's predicted way on *every* day."""
    z: float | None
    """Two-proportion z of signal days against all other days."""

    @property
    def rate(self) -> float | None:
        return self.success / self.count if self.count else None

    @property
    def lift(self) -> float | None:
        return self.rate - self.base_rate if self.rate is not None else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal": self.signal,
            "count": self.count,
            "success": self.success,
            "rate": round(self.rate, 4) if self.rate is not None else None,
            "base_rate": round(self.base_rate, 4),
            "lift": round(self.lift, 4) if self.lift is not None else None,
            "z": round(self.z, 2) if self.z is not None else None,
            "p_value": round(p_value(self.z), 4) if self.z is not None else None,
        }


def two_proportion_z(hits_a: int, n_a: int, hits_b: int, n_b: int) -> float | None:
    """z for the difference between two success rates, pooled variance."""
    if n_a == 0 or n_b == 0:
        return None
    pooled = (hits_a + hits_b) / (n_a + n_b)
    spread = math.sqrt(pooled * (1 - pooled) * (1 / n_a + 1 / n_b))
    return (hits_a / n_a - hits_b / n_b) / spread if spread > 0 else None


def p_value(z: float) -> float:
    """Two-sided, normal."""
    return math.erfc(abs(z) / math.sqrt(2))


LABELS: dict[tuple[Model, str], str] = {
    (Model.VIX, DOWN): "VIX up -> gap down",
    (Model.VIX, UP): "VIX down -> gap up",
    (Model.CANDLE, UP): "GREEN -> gap up",
    (Model.CANDLE, DOWN): "RED -> gap down",
    (Model.JOINT, UP): "GREEN & VIX down -> gap up",
    (Model.JOINT, DOWN): "RED & VIX up -> gap down",
}


def observations(
    days: Sequence[Day], *, start: date | None = None, end: date | None = None
) -> list[tuple[Day, str]]:
    """(signal day, the next morning's gap direction) for each pair of
    consecutive sessions whose gap was not exactly zero, signal day in
    [start, end]."""
    out = []
    for today, after in pairwise(days):
        if (start and today.day < start) or (end and today.day > end):
            continue
        direction = gap(today.close, after.open)
        if direction is not None:
            out.append((today, direction))
    return out


def table(
    model: Model,
    seen: Sequence[tuple[Day, str]],
    definition: VixChange = VixChange.INTRADAY,
) -> dict[str, Any]:
    """The paper's success table for one model, on `seen`."""
    total = len(seen)
    ups = sum(1 for _, direction in seen if direction == UP)
    base = {UP: ups / total if total else 0.0, DOWN: (total - ups) / total if total else 0.0}
    rows: list[Row] = []
    for expected in (DOWN, UP) if model is Model.VIX else (UP, DOWN):
        fired = [
            direction for day, direction in seen if predict(model, day, definition) == expected
        ]
        hits = sum(1 for direction in fired if direction == expected)
        others = total - len(fired)
        other_hits = sum(1 for _, direction in seen if direction == expected) - hits
        rows.append(
            Row(
                LABELS[model, expected],
                len(fired),
                hits,
                base[expected],
                two_proportion_z(hits, len(fired), other_hits, others),
            )
        )
    signalled = sum(r.count for r in rows)
    success = sum(r.success for r in rows)
    return {
        "model": model.value,
        "rows": [r.to_dict() for r in rows],
        "signalling_days": signalled,
        "inconclusive_days": total - signalled,
        "success": success,
        "accuracy": round(success / signalled, 4) if signalled else None,
        "always_predict_up": round(base[UP], 4),
    }


def tables(
    days: Sequence[Day],
    *,
    start: date | None = None,
    end: date | None = None,
    definition: VixChange = VixChange.INTRADAY,
) -> dict[str, Any]:
    """Tables 5, 6 and 7 of the paper, with base rates and tests."""
    seen = observations(days, start=start, end=end)
    return {
        "days": len(seen),
        "gap_up_any_day": round(sum(1 for _, d in seen if d == UP) / len(seen), 4)
        if seen
        else None,
        **{model.value: table(model, seen, definition) for model in Model},
    }


def agreement(days: Sequence[Day]) -> dict[str, int]:
    """How often the two definitions of "VIX rose" give the same answer."""
    same = differ = undefined = 0
    for day in days:
        a, b = day.vix_move(VixChange.INTRADAY), day.vix_move(VixChange.CLOSE_TO_CLOSE)
        if a is None or b is None:
            undefined += 1
        elif a == b:
            same += 1
        else:
            differ += 1
    return {"same": same, "differ": differ, "flat_or_unknown": undefined}


# --- as a trade, on the future --------------------------------------------------


def trade(
    model: Model | None,
    days: Sequence[Day],
    legs: Sequence[Overnight],
    *,
    side: str = "both",
    start: date | None = None,
    end: date | None = None,
    definition: VixChange = VixChange.INTRADAY,
) -> dict[str, Any]:
    """Hold the near-month future from a signal day's close to the next open.

    Long when the model predicts a gap up, short when it predicts a gap down.
    `side` restricts it to "long" or "short". A leg's `day` is the morning the
    position is closed; the signal is read from the session before it. Costs
    are one futures round trip per night held (`session_studies.round_trip_cost`).
    Also returns how often the *future* gapped the predicted way, since that,
    not the index, is what was traded.

    `model=None` is the yardstick: long every night, no signal. A signal is
    worth something only if it beats that, because the future drifts up
    overnight on its own.
    """
    by_day = {d.day: d for d in days}
    order = [d.day for d in days]
    previous = dict(zip(order[1:], order[:-1], strict=True))
    out_days: list[date] = []
    gross: list[float] = []
    net: list[float] = []
    trips = right = longs = shorts = 0
    for leg in legs:
        signal_day = previous.get(leg.day)
        if signal_day is None or (start and signal_day < start) or (end and signal_day > end):
            continue
        out_days.append(leg.day)
        expected = UP if model is None else predict(model, by_day[signal_day], definition)
        direction = {UP: 1, DOWN: -1}.get(expected or "", 0)
        if (side == "long" and direction < 0) or (side == "short" and direction > 0):
            direction = 0
        if direction == 0:
            gross.append(0.0)
            net.append(0.0)
            continue
        move = direction * (leg.open / leg.previous_close - 1.0)
        trips += 1
        longs += direction > 0
        shorts += direction < 0
        right += move > 0
        gross.append(move)
        net.append((1 + move) * (1 - round_trip_cost(leg.day, leg.open)) - 1)
    return {
        "model": model.value if model else "every night",
        "side": side,
        "nights": trips,
        "long_nights": longs,
        "short_nights": shorts,
        "future_gapped_as_predicted": round(right / trips, 4) if trips else None,
        "gross": summarise(out_days, gross, 0),
        "net": summarise(out_days, net, trips),
    }
