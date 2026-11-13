"""The decay monitor: has a strategy's edge gone, or is it only unlucky? (ADR-178)

Paper books stop at fixed loss limits (`deploy/loss_limits.py`). A strategy
whose edge has gone but which loses slowly keeps its capital, and one that is
fine but unlucky may be halted. This asks the other question, every session:
do the returns since the strategy started trading forward still look like
its backtest's?

A one-sided CUSUM (research 191). With the backtest's daily mean `m` and
standard deviation `s`:

    z_t = (r_t - m) / s                 today's return in backtest units
    k   = (m / s) / 2                   half the fall to "no edge at all"
    S_t = max(0, S_{t-1} - z_t - k)     grows while returns run below the backtest

    S < watch_at * h     healthy
    S >= watch_at * h    watch      no new capital
    S >= h               decayed    one step down the ladder (`deploy/ladder.py`)

`h` is not a universal number. `calibrate` finds, for each strategy, the
level that its own backtest returns (resampled in blocks, so runs of bad
days stay together) cross in no more than the constitution's `false_alarm`
share of `horizon_sessions`-long stretches. `delay` then says how many
sessions a strategy with no edge left would take to be caught, so the
operator can see what the monitor can and cannot do: a thin daily edge takes
many months to tell from noise, and no test changes that.

Measured slippage is taken off the backtest mean before anything else, so a
strategy is compared with what it could have earned at real fills.
"""

from __future__ import annotations

import random
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from eulerlab import constitution

BLOCK = 10
"""Sessions in a resampled block."""
RUNS = 400
MIN_BACKTEST = 120
State = Literal["healthy", "watch", "decayed", "too little history"]


@dataclass(frozen=True)
class Baseline:
    """What the backtest says a healthy day looks like."""

    mean: float
    std: float

    @property
    def k(self) -> float:
        return max(self.mean / self.std, 0.0) / 2.0


def baseline(backtest: Sequence[float], slippage_daily: float = 0.0) -> Baseline | None:
    """The backtest's daily mean (less measured slippage) and spread, or None if it is too short."""
    if len(backtest) < MIN_BACKTEST:
        return None
    std = statistics.stdev(backtest)
    if std <= 0:
        return None
    return Baseline(statistics.fmean(backtest) - slippage_daily, std)


def path(live: Sequence[float], base: Baseline) -> list[float]:
    """S after each live session."""
    out: list[float] = []
    s = 0.0
    for r in live:
        s = max(0.0, s - (r - base.mean) / base.std - base.k)
        out.append(s)
    return out


def _resample(values: Sequence[float], n: int, rng: random.Random) -> list[float]:
    out: list[float] = []
    while len(out) < n:
        start = rng.randrange(len(values))
        out.extend(values[(start + i) % len(values)] for i in range(BLOCK))
    return out[:n]


def _peaks(
    backtest: Sequence[float], base: Baseline, horizon: int, shift: float, seed: int
) -> list[float]:
    """The highest S reached in each of `RUNS` resampled stretches, with `shift` added to each day."""
    rng = random.Random(seed)
    return [
        max(path([r + shift for r in _resample(backtest, horizon, rng)], base)) for _ in range(RUNS)
    ]


def calibrate(
    backtest: Sequence[float], base: Baseline, *, false_alarm: float, horizon: int
) -> float:
    """The alarm level a healthy strategy crosses in at most `false_alarm` of stretches."""
    peaks = sorted(_peaks(backtest, base, horizon, 0.0, seed=17))
    return peaks[min(len(peaks) - 1, int((1.0 - false_alarm) * len(peaks)))] + 1e-9


def false_alarm_rate(backtest: Sequence[float], base: Baseline, h: float, horizon: int) -> float:
    """Share of healthy stretches that cross `h`, on resamples the calibration did not use."""
    peaks = _peaks(backtest, base, horizon, 0.0, seed=4099)
    return sum(p >= h for p in peaks) / len(peaks)


def delay(
    backtest: Sequence[float], base: Baseline, h: float, horizon: int
) -> dict[str, float | None]:
    """How a strategy whose mean has fallen to zero is caught: share caught, and the median session."""
    rng = random.Random(23)
    first: list[int] = []
    for _ in range(RUNS):
        dead = [r - base.mean for r in _resample(backtest, horizon, rng)]
        hit = next((i + 1 for i, s in enumerate(path(dead, base)) if s >= h), None)
        if hit is not None:
            first.append(hit)
    return {
        "caught": len(first) / RUNS,
        "median_sessions": statistics.median(first) if first else None,
    }


@dataclass(frozen=True)
class Reading:
    state: State
    s: float
    h: float | None
    sessions: int
    expected_mean: float | None
    live_mean: float | None
    why: str

    def as_dict(self) -> dict[str, object]:
        return {
            "state": self.state,
            "s": round(self.s, 3),
            "h": round(self.h, 3) if self.h is not None else None,
            "sessions": self.sessions,
            "expected_mean": self.expected_mean,
            "live_mean": self.live_mean,
            "why": self.why,
        }


def read(
    backtest: Sequence[float],
    live: Sequence[float],
    *,
    slippage_daily: float = 0.0,
    slippage_drift: bool = False,
) -> Reading:
    """The strategy's state today. `slippage_drift` alone puts a healthy strategy on watch."""
    rules = constitution.load().decay
    base = baseline(backtest, slippage_daily)
    if base is None:
        why = f"the backtest has fewer than {MIN_BACKTEST} sessions of returns"
        return Reading("too little history", 0.0, None, len(live), None, None, why)
    h = calibrate(backtest, base, false_alarm=rules.false_alarm, horizon=rules.horizon_sessions)
    s = path(live, base)[-1] if live else 0.0
    live_mean = statistics.fmean(live) if live else None
    state: State = "healthy"
    why = "returns since the start are in line with the backtest"
    if s >= h:
        state, why = "decayed", "returns have run below the backtest for longer than chance allows"
    elif s >= rules.watch_at * h:
        state, why = "watch", "returns are running below the backtest; not yet beyond chance"
    elif slippage_drift:
        state, why = "watch", "fills are costing more than the backtest assumed"
    return Reading(state, s, h, len(live), base.mean, live_mean, why)
