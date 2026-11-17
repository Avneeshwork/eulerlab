"""Shared pieces of the papers strategies: helpers used by more than one, and the types they share."""

from __future__ import annotations

import math
import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import time

from eulerlab.features.indicators import atr
from eulerlab.intraday.tweezer import Candle, Plan, Rejected

IST_OPEN = time(9, 15)
"""NSE opens at 09:15 IST. The papers are written against 09:30 ET; what
transfers is "the first N minutes of the session", not the clock time."""


@dataclass(frozen=True)
class PaperRules:
    """Every threshold, named, and sourced.

    Separated from the logic for the same reason `tweezer.Rules` is: a
    threshold living inside a condition gets tuned as a side effect of reading
    the code, and nobody can see it happen.
    """

    # --- shared risk geometry ---
    atr_period: int = 14
    stop_atr_mult: float = 1.4
    """Zarattini, Barbon & Aziz (2024): stop at entry -/+ 1.4 x ATR(14)."""

    target_r: float = 2.0
    """Bracket target as a multiple of risk. **Ours, not the papers'** — Mesfin
    exits on a bar horizon and Zarattini exits at the close, neither of which
    is a target. Named so the substitution is visible."""

    risk_per_trade: float = 0.01
    max_risk_pct: float = 3.0
    min_risk_pct: float = 0.05

    # --- opening range (Mesfin §4.1, Zarattini et al. 2024) ---
    opening_range_minutes: int = 5
    orb_relative_volume_min: float = 1.0
    """Zarattini's selection step: first-5-minute volume over the mean of the
    prior 14 days. The paper's own summary reports the plain breakout is weak
    and this screen does almost all the work."""

    orb_baseline_sessions: int = 14
    """How many prior sessions the relative-volume baseline averages.

    The paper says 14 and this field is what enforces it. Until it existed the
    code averaged **every** prior session in the window, so a 58-session
    backtest silently compared today against a 58-day mean — a slower-moving,
    less selective baseline than the one published, which changes how often the
    screen fires and therefore what is being measured."""

    # --- range expansion (Mesfin §4.2) ---
    expansion_lookback: int = 20
    expansion_mult: float = 2.5

    # --- liquidity grab (Mesfin §4.3) ---
    grab_lookback: int = 20

    # --- gaps (Mesfin §4.4) ---
    gap_min_pct: float = 0.3

    # --- volume signatures (Mesfin §4.5) ---
    volume_lookback: int = 20
    volume_spike_z: float = 2.0
    volume_dryup_z: float = -1.0

    # --- volatility regime (Mesfin §4.6) ---
    vvg_lookback: int = 20
    vvg_range_mult: float = 1.5

    # --- mean reversion (Mesfin §4.8) ---
    ou_lookback: int = 60
    ou_entry_z: float = -2.0


Detect = Callable[[Sequence[Candle], PaperRules, float], "Plan | Rejected"]


@dataclass(frozen=True)
class PaperSignal:
    """One coded signal and the claim it is testing."""

    id: str
    title: str
    source: str
    """Citation, to the section. A signal whose provenance is a memory is not
    reproducible."""

    published: str
    """What the paper reported. Carried in the object so a result can never be
    read without the prior it is arguing against."""

    detect: Detect

    paper_url: str = ""
    paper_pdf: str = ""
    tested_on: str = ""
    """The instrument and market the **paper** tested, in its own words.

    Not what this platform runs it on. Mesfin tested MNQ futures and Zarattini
    US equities; everything here runs on NSE minute bars. Reading a result
    without knowing that gap is how a strategy gets credited with evidence
    gathered somewhere else entirely.
    """

    recommended_class: str = ""
    """The asset class the paper studied. Distinct from the asset class a run
    was pointed at, which the result already carries."""

    logic: tuple[str, ...] = ()
    """The implementation, step by step, as coded.

    Written beside the function rather than inside the UI so the two cannot
    drift: if the rule changes and this does not, the mismatch is in one file
    and visible in review.
    """


def _closes(window: Sequence[Candle]) -> list[float]:
    return [c.close for c in window]


ATR_TAIL_PERIODS = 20
"""How many ATR periods of history the current ATR is computed from.

At the default period of 14 this is 280 bars. Wilder smoothing weights the bar
`n` steps back by `(1 - 1/period)**n`, so the oldest bar retained carries about
1e-9 of the result.

This is a **speed** bound, and only that. `detect` is called once per bar with
every bar so far, so recomputing ATR over the whole window made every signal
using it quadratic in the length of the backtest: on 120,960 crypto minute bars
that is roughly 4e10 operations per parameter set, and `session_momentum` ran
32 minutes of CPU without finishing one. Bounded, it finishes in 51 seconds.

It buys nothing else, and the first version of this docstring claimed otherwise
— that it also made ATR independent of where the study starts. Measured, that
claim is wrong in both directions. Whole-history ATR has already converged to
the identical float64 by about 500 bars, so there was no long-window drift to
fix; and below the tail length the slice is a no-op, so a short window is
computed exactly as it was before. Where the study start genuinely does matter
is the first few hundred bars after it — 4% at 30 bars, 0.04% at 60 — and this
bound does not touch that, because there the tail *is* the whole window.

`tests/test_atr_tail_bound.py` measures the agreement rather than asserting it
from the algebra."""


def _atr_now(window: Sequence[Candle], period: int) -> float | None:
    """Current ATR, from a bounded tail of the window.

    See `ATR_TAIL_PERIODS` for why it is bounded rather than computed over
    everything available.
    """
    tail = window[-(period * ATR_TAIL_PERIODS) :]
    series = atr([c.high for c in tail], [c.low for c in tail], _closes(tail), period=period)
    return series[-1] if series and series[-1] is not None else None


def _session_bars(window: Sequence[Candle]) -> list[Candle]:
    """Bars belonging to the same session date as the last bar.

    Sessions are separated by date rather than by a clock window, so this works
    unchanged on crypto, which has no session at all and returns the whole day.

    Found by walking back from the end rather than filtering the whole window.
    Candles arrive sorted, so one session's bars are contiguous at the tail, and
    the two forms return the same list. The difference is cost: `detect` is
    called once per bar with every bar so far, so a full filter here made every
    signal in the library quadratic in the length of the backtest. On 22,000 US
    minute bars that is 484 million comparisons per parameter set, spent to
    re-find roughly 390 bars that were already at the end.
    """
    day = window[-1].ts.date()
    first = len(window)
    while first > 0 and window[first - 1].ts.date() == day:
        first -= 1
    return list(window[first:])


def _plan(
    *, signal: Candle, entry: float, stop: float, rules: PaperRules, equity: float
) -> Plan | Rejected:
    """Turn a trigger into a fully specified bracket, or say why not."""
    r = entry - stop
    if r <= 0:
        return Rejected("stop above entry")
    risk_pct = r / entry * 100.0
    if risk_pct > rules.max_risk_pct:
        return Rejected("risk too wide", f"{risk_pct:.2f}%")
    if risk_pct < rules.min_risk_pct:
        return Rejected("risk too tight", f"{risk_pct:.2f}%")

    shares = math.floor((equity * rules.risk_per_trade) / r)
    shares = min(shares, math.floor(equity / entry))
    if shares < 1:
        return Rejected("size rounds to zero")

    first = shares // 2 if shares >= 2 else 0
    return Plan(
        signal_ts=signal.ts,
        entry=entry,
        stop=stop,
        target_1=entry + rules.target_r * r,
        target_2=entry + (rules.target_r + 1.0) * r,
        r=r,
        shares_1=first,
        shares_2=shares - first,
        risk_pct=risk_pct,
    )


def _volume_z(window: Sequence[Candle], lookback: int) -> float | None:
    """How unusual the last bar's volume is, in standard deviations."""
    volumes = [c.volume for c in window[-(lookback + 1) : -1]]
    if len(volumes) < lookback or len(set(volumes)) < 2:
        return None
    spread = statistics.pstdev(volumes)
    if spread <= 0:
        return None
    return (window[-1].volume - statistics.fmean(volumes)) / spread


# --- Mesfin (2026) §4.1 — opening range breakout -----------------------------


def opening_range_breakout(
    window: Sequence[Candle], rules: PaperRules, equity: float
) -> Plan | Rejected:
    """Break of the first N minutes' high, long.

    Mesfin §4.1 tested 09:30-09:55 ET with immediate, pullback and delayed
    entries; the best long variant reached t = 1.50 and failed on year
    stability (-1.42 in 2022, +7.04 in 2024). Zarattini et al. use a
    **five-minute** range and report the breakout alone is weak.
    """
    session = _session_bars(window)
    span = rules.opening_range_minutes
    if len(session) <= span:
        return Rejected("warmup", f"{len(session)} session bars, need > {span}")
    if len(window) < rules.atr_period * 2:
        return Rejected("warmup", "not enough history for ATR")

    opening = session[:span]
    high = max(c.high for c in opening)
    if opening[-1].close <= opening[0].open:
        return Rejected("range closed down", "the paper takes the long only when it closes up")

    signal = window[-1]
    if signal.close <= high:
        return Rejected("no breakout", f"close {signal.close:.2f} <= range high {high:.2f}")
    if signal in opening:
        return Rejected("still inside the opening range")

    band = _atr_now(window, rules.atr_period)
    if band is None or band <= 0:
        return Rejected("no ATR")
    return _plan(
        signal=signal,
        entry=signal.close,
        stop=high - rules.stop_atr_mult * band,
        rules=rules,
        equity=equity,
    )


# --- Mesfin (2026) §4.4 — gaps -----------------------------------------------


def _gap_pct(window: Sequence[Candle]) -> float | None:
    """Today's open against the previous session's close."""
    session = _session_bars(window)
    if not session:
        return None
    before = [c for c in window if c.ts.date() < session[0].ts.date()]
    if not before:
        return None
    previous_close = before[-1].close
    if previous_close <= 0:
        return None
    return (session[0].open - previous_close) / previous_close * 100.0
