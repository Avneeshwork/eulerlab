"""Intraday signals from published papers, coded against this platform.

Every signal here traces to a paper in `docs/RESEARCH/019`, and every one of
them arrives with a **published expectation of failure**. That is not a
disclaimer, it is the point.

### Why a library of failures is worth building

A strategy library normally arrives with a positive prior — someone published a
result, and the noise bar's job is to argue it down. Mesfin (2026) tested
fourteen intraday signal families on 947 days of MNQ futures against five
criteria and **none passed**: maximum gross return across every family was
1.05-1.50 points against a 2.0-point friction cost. So the prior here is already
negative and measured, and a positive result on our data has to argue against
evidence rather than against nothing.

That is the correct posture, and it is one we normally have to manufacture.

### What is faithful here and what is not

**Faithful:** the entry conditions. Each `detect` implements the paper's stated
trigger, on the paper's stated bar geometry, with the thresholds it published.

**Not faithful:** the exits. Mesfin measures a fixed-horizon return (enter at
bar+1, exit at bar+N). This platform's intraday engine is a bracket — stop,
targets, forced close at the session end — because that is what `bracket.run`
simulates and what a real order would be. A bracket exit and a horizon exit are
different strategies over the same signal, and the difference is not small: a
signal with positive drift and fat left tails looks very different under a stop
than under a horizon. Results here therefore **cannot be compared to the
paper's tables directly**, and the note in `docs/RESEARCH/019` says so.

**Also not faithful:** everything is long-only, because `bracket.run` opens with
`Side.BUY` and closes with `Side.SELL`. Short variants are mirrored to the long
side where the mirror is meaningful and omitted where it is not.

**Also different:** the friction. Mesfin's ceiling is 2.0 points round-trip on a
Nasdaq future. Indian equity costs are a percentage, not a point spread, and
include STT and stamp duty. Whether the ceiling transfers is the first thing
running these measures — it is an open question in the note, not an assumption.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from eulerlab.features.indicators import atr, sma
from eulerlab.intraday.tweezer import Candle, Plan, Rejected


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


# --- shared plumbing ---------------------------------------------------------


def _sma_tail(window: Sequence[Candle], period: int, *, back: int = 1) -> list[float | None]:
    """The last `back` simple moving averages, from exactly enough history.

    Unlike ATR, a simple moving average has a finite window: the value at bar
    `i` depends on exactly `period` closes and nothing before them. So in exact
    arithmetic this returns precisely what the whole-window call returned, and
    the bound costs no accuracy at all.

    In float64 the two differ in the last bits, and it is worth knowing which
    way. `sma` keeps a running sum and subtracts the departing value, so its
    rounding error grows with the number of bars it has walked: at 120,960 bars
    the whole-window value has drifted about 5e-14 relative, at 1,000 bars
    about 1e-16. The **bounded** value is therefore the more accurate of the
    two, not the approximation — it has walked 74 bars instead of 120,960.

    It exists because computing them from the whole window was quadratic.
    `detect` runs once per bar with every bar so far, so `sma(_closes(window),
    n)` built a list of every close and a full moving-average series on each of
    120,960 crypto bars — about 1.5e10 operations for two numbers at the end of
    it. `trend_pullback` did not finish a single parameter set. It was not the last:
    `ou_mean_reversion` was still doing it in its own way until 2026-08-27,
    which is why a 1,244-session NSE request timed out and showed nothing.
    """
    tail = window[-(period + back) :]
    return sma(_closes(tail), period)


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
    **five-minute** range and report the breakout alone is weak. What
    transfers to NSE, which opens at 09:15 IST, is "the first N minutes of
    the session", not the clock time.
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


# --- Mesfin (2026) §4.2 — range expansion continuation ------------------------


def range_expansion(window: Sequence[Candle], rules: PaperRules, equity: float) -> Plan | Rejected:
    """A bar whose range far exceeds the rolling mean, taken as continuation.

    Mesfin §4.2 is the most interesting failure in the paper: t = -10.96 at
    bar+1. The signal is not merely unprofitable, it is **significantly
    backwards**, and the explanation generalises — the directional burst is
    real but is fully consumed *inside* the expansion bar, so a bar-close
    system entering on the next bar systematically captures the post-exhaustion
    reversal instead. Momentum that lives inside a bar cannot be reached by
    bar-close execution.
    """
    if len(window) < rules.expansion_lookback + 2:
        return Rejected("warmup")
    ranges = [c.high - c.low for c in window[-(rules.expansion_lookback + 1) : -1]]
    mean_range = statistics.fmean(ranges) if ranges else 0.0
    if mean_range <= 0:
        return Rejected("no range history")

    signal = window[-1]
    span = signal.high - signal.low
    if span < rules.expansion_mult * mean_range:
        return Rejected("not an expansion", f"{span / mean_range:.2f}x mean")
    if signal.close <= signal.open:
        return Rejected("expansion is downward", "continuation long needs an up bar")

    return _plan(signal=signal, entry=signal.close, stop=signal.low, rules=rules, equity=equity)


# --- Mesfin (2026) §4.3 — liquidity grab reversal ----------------------------


def liquidity_grab_reversal(
    window: Sequence[Candle], rules: PaperRules, equity: float
) -> Plan | Rejected:
    """Price pierces the session low, then closes back inside. Long the reversal.

    Mesfin §4.3 found 6,442 such events and both directions significantly
    negative — fading at t = -14.12, following at t = -13.24. The gross
    directional content is 0.20-0.80 points either way, which cannot clear a
    2-point friction in either direction. He calls it a pure friction-ceiling
    result: the pattern is real and too small to trade.
    """
    session = _session_bars(window)
    if len(session) < rules.grab_lookback + 1:
        return Rejected("warmup", f"{len(session)} session bars")

    prior = session[-(rules.grab_lookback + 1) : -1]
    floor = min(c.low for c in prior)
    signal = session[-1]

    if signal.low >= floor:
        return Rejected("no pierce", "did not take out the session low")
    if signal.close <= floor:
        return Rejected("closed outside", "a grab must close back inside the range")

    return _plan(signal=signal, entry=signal.close, stop=signal.low, rules=rules, equity=equity)


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


def gap_fill_fade(window: Sequence[Candle], rules: PaperRules, equity: float) -> Plan | Rejected:
    """A down gap, faded on the expectation that it closes during the session.

    Mesfin §4.4 tested three entry times and all failed, t between -0.32 and
    -0.59 — indistinguishable from noise rather than wrong. MNQ gaps simply do
    not reliably fill within the session.
    """
    gap = _gap_pct(window)
    if gap is None:
        return Rejected("no previous session")
    if gap > -rules.gap_min_pct:
        return Rejected("no down gap", f"{gap:.2f}%")

    signal = _session_bars(window)[-1]
    band = _atr_now(window, rules.atr_period)
    if band is None or band <= 0:
        return Rejected("no ATR")
    return _plan(
        signal=signal,
        entry=signal.close,
        stop=signal.close - rules.stop_atr_mult * band,
        rules=rules,
        equity=equity,
    )


def gap_continuation(window: Sequence[Candle], rules: PaperRules, equity: float) -> Plan | Rejected:
    """An up gap, taken as continuation rather than something to be filled.

    Mesfin §4.4's most interesting result and the one he refused to claim: with
    a Kalman velocity filter the short side reached t = 3.23 at a 68% win rate
    — on **22 trades over three years**, declining from 12 to 6 to 4. He kept
    it as a candidate rather than validating it, which is the right call and
    the reason this is coded without the Kalman filter: that filter is what
    reduced it to 22 observations.
    """
    gap = _gap_pct(window)
    if gap is None:
        return Rejected("no previous session")
    if gap < rules.gap_min_pct:
        return Rejected("no up gap", f"{gap:.2f}%")

    session = _session_bars(window)
    signal = session[-1]
    if signal.close <= session[0].open:
        return Rejected("gap already fading", "continuation needs price above the open")

    band = _atr_now(window, rules.atr_period)
    if band is None or band <= 0:
        return Rejected("no ATR")
    return _plan(
        signal=signal,
        entry=signal.close,
        stop=session[0].open - rules.stop_atr_mult * band,
        rules=rules,
        equity=equity,
    )


# --- Mesfin (2026) §4.5 — volume signatures ----------------------------------


def volume_spike_momentum(
    window: Sequence[Candle], rules: PaperRules, equity: float
) -> Plan | Rejected:
    """An unusually heavy up bar, taken as informed flow continuing.

    Mesfin §4.5: t = +0.07 on 2,119 up-spikes. He is careful about what that
    means — the sample is large enough that a near-zero t is a **precise null**,
    not an underpowered test. Volume magnitude at five-minute resolution does
    not predict the next bar's direction.
    """
    if len(window) < rules.volume_lookback + 1:
        return Rejected("warmup")
    z = _volume_z(window, rules.volume_lookback)
    if z is None:
        return Rejected("no volume history")
    if z < rules.volume_spike_z:
        return Rejected("no spike", f"z={z:.2f}")

    signal = window[-1]
    if signal.close <= signal.open:
        return Rejected("spike is downward")
    return _plan(signal=signal, entry=signal.close, stop=signal.low, rules=rules, equity=equity)


def volume_dryup_reversal(
    window: Sequence[Candle], rules: PaperRules, equity: float
) -> Plan | Rejected:
    """Volume drying up after a decline, taken as exhaustion before a turn.

    Mesfin §4.5: t = -0.92 on 1,060 events. Another precise null.
    """
    if len(window) < rules.volume_lookback + 2:
        return Rejected("warmup")
    z = _volume_z(window, rules.volume_lookback)
    if z is None:
        return Rejected("no volume history")
    if z > rules.volume_dryup_z:
        return Rejected("no dry-up", f"z={z:.2f}")

    signal = window[-1]
    trend = _sma_tail(window, rules.volume_lookback)
    level = trend[-1] if trend and trend[-1] is not None else None
    if level is None or signal.close >= level:
        return Rejected("not after a decline", "exhaustion needs price below its mean")

    return _plan(signal=signal, entry=signal.close, stop=signal.low, rules=rules, equity=equity)


# --- Mesfin (2026) §4.6 — volatility regime ----------------------------------


def volatility_regime_reversal(
    window: Sequence[Candle], rules: PaperRules, equity: float
) -> Plan | Rejected:
    """On an unusually volatile session, fade the move.

    Mesfin §4.6's VVG classifier needs three simultaneous pre-market terciles
    (first-30-minute return, overnight gap, first-bar volume deviation) and
    fires on 4.4% of days. The descriptive findings are real — a 25.6bp
    next-day spread and a 77.6% peak-reversal rate — and **every directional
    strategy built on them failed**, reversal at t = +0.86.

    Coded with a single volatility condition rather than three terciles: the
    tercile construction needs a cross-day distribution the intraday scanner
    does not carry. That is a simplification, and it is stated rather than
    hidden.
    """
    session = _session_bars(window)
    if len(session) < 2 or len(window) < rules.vvg_lookback + 2:
        return Rejected("warmup")

    ranges = [c.high - c.low for c in window[-(rules.vvg_lookback + 1) : -1]]
    mean_range = statistics.fmean(ranges) if ranges else 0.0
    if mean_range <= 0:
        return Rejected("no range history")

    span = max(c.high for c in session) - min(c.low for c in session)
    if span < rules.vvg_range_mult * mean_range * len(session) ** 0.5:
        return Rejected("session not volatile enough")

    signal = session[-1]
    opening = session[0].open
    if signal.close >= opening:
        return Rejected("not down on the session", "the long fade needs a decline to fade")

    return _plan(
        signal=signal,
        entry=signal.close,
        stop=min(c.low for c in session),
        rules=rules,
        equity=equity,
    )


# --- Mesfin (2026) §4.8 — Ornstein-Uhlenbeck mean reversion ------------------


def ou_mean_reversion(
    window: Sequence[Candle], rules: PaperRules, equity: float
) -> Plan | Rejected:
    """Buy when price is far below its rolling mean in standard deviations.

    Mesfin §4.8 tested this on Micro Gold at 1.5sd, 2.0sd and 2.5sd; all failed,
    most with strongly negative t. The 60-minute variant's half-life worked out
    to roughly eight hours — longer than a session, which makes it structurally
    incompatible with intraday execution regardless of its sign.
    """
    if len(window) < rules.ou_lookback + 1:
        return Rejected("warmup")
    # Bound the window *before* extracting, not after. This read
    # `_closes(window)[-(ou_lookback + 1):]`, which built a list of every close
    # since the start of the backtest and then kept the last 21 — once per bar,
    # so O(n) per call and O(n^2) per run. It is the exact hazard `_bounded_sma`
    # above documents, and that docstring named `trend_pullback` as the last
    # signal doing it while this one still was.
    #
    # The two forms are the same values: the last N closes of the whole window
    # are the closes of the last N candles.
    closes = _closes(window[-(rules.ou_lookback + 1) :])
    reference, signal = closes[:-1], window[-1]
    spread = statistics.pstdev(reference)
    if spread <= 0:
        return Rejected("no dispersion")
    z = (signal.close - statistics.fmean(reference)) / spread
    if z > rules.ou_entry_z:
        return Rejected("not stretched", f"z={z:.2f}")

    return _plan(
        signal=signal,
        entry=signal.close,
        stop=signal.close - spread * 1.5,
        rules=rules,
        equity=equity,
    )


# --- Zarattini, Barbon & Aziz (2024) — ORB on a stock in play ----------------


_RELATIVE_VOLUME_CACHE: dict[object, list[float]] = {}
"""Prior-session opening volumes, keyed by (window start, session, params).

One entry per session per sweep, so a 58-session backtest across a nine-point
grid holds a few hundred short lists. Cleared wholesale rather than evicted by
age: the contents are derived, so losing them costs recomputation and nothing
else, and an LRU here would be more machinery than the problem deserves."""

_RELATIVE_VOLUME_CACHE_MAX = 20_000


def orb_stock_in_play(
    window: Sequence[Candle], rules: PaperRules, equity: float
) -> Plan | Rejected:
    """The opening-range breakout, but only on an unusually active day.

    Zarattini, Barbon & Aziz (2024) report Sharpe 2.81 over 2016-2023 on the
    top-20 basket, and their own summary says the plain breakout is weak — the
    **relative-volume selection does almost all the work**.

    That directly contradicts Mesfin on ORB, and the contradiction is
    informative rather than awkward: Mesfin tests one index future with no
    selection step, while this is a cross-sectional result over 7,000 names. The
    two are consistent if the edge lives in choosing *which* instrument to apply
    the breakout to.

    The honest gap: the paper compares today's first-five-minute volume to the
    mean of the **prior 14 days**, which needs cross-session history the scanner
    holds only when the window spans them. Where it does not, this returns a
    rejection naming the reason rather than silently degrading to a plain ORB.
    """
    session = _session_bars(window)
    span = rules.opening_range_minutes
    if len(session) <= span:
        return Rejected("warmup", f"{len(session)} session bars")

    opening_volume = sum(c.volume for c in session[:span])

    # Walked backwards and stopped at `orb_baseline_sessions`, for two reasons.
    #
    # The paper averages the prior 14 days; the first version of this averaged
    # every prior session in the window, which on a 58-session backtest is a
    # 58-day baseline and a different screen than the published one.
    #
    # It was also quadratic. `detect` is called once per bar and the window is
    # every bar so far, and the old body ran a full `[c for c in window if ...]`
    # scan per distinct day inside a loop over the whole window — so the cost
    # grew as the cube of the range. On 22,000 US minute bars it did not finish;
    # it had run seventeen minutes at 99% CPU when it was killed, against about
    # thirty seconds for every other signal in the library.
    today = session[0].ts.date()

    # Memoised per (series, session). The baseline averages *prior* sessions,
    # so within one session it is the same number on every bar — recomputing it
    # per bar repeated identical work about 390 times a day.
    #
    # The key fingerprints the first bar's OHLCV, not just its timestamp. Every
    # US series in this platform starts at the same instant — QQQ and SPY both
    # open 13:30 on the first session — so a timestamp-only key would serve
    # SPY's volume baseline to a QQQ scan and silently change which days pass
    # the screen. A full opening bar is what distinguishes them.
    first = window[0]
    cache_key = (
        first.ts,
        first.open,
        first.high,
        first.low,
        first.close,
        first.volume,
        today,
        span,
        rules.orb_baseline_sessions,
    )
    history = _RELATIVE_VOLUME_CACHE.get(cache_key)
    if history is None:
        per_day: dict[object, list[float]] = {}
        for candle in reversed(window):
            day = candle.ts.date()
            if day == today:
                continue
            if day not in per_day and len(per_day) >= rules.orb_baseline_sessions:
                break
            per_day.setdefault(day, []).append(candle.volume)

        # Reversed once more: the walk collected each day's bars back to front,
        # and the paper measures the session's *first* `span` minutes.
        history = [
            sum(list(reversed(volumes))[:span])
            for volumes in per_day.values()
            if len(volumes) >= span
        ]
        if len(_RELATIVE_VOLUME_CACHE) > _RELATIVE_VOLUME_CACHE_MAX:
            _RELATIVE_VOLUME_CACHE.clear()
        _RELATIVE_VOLUME_CACHE[cache_key] = history

    if len(history) < 2:
        return Rejected(
            "no relative volume",
            "needs prior sessions' opening volume; the selection step is the strategy",
        )
    baseline = statistics.fmean(history)
    if baseline <= 0:
        return Rejected("no baseline volume")
    relative = opening_volume / baseline
    if relative < rules.orb_relative_volume_min:
        return Rejected("not in play", f"relative volume {relative:.2f}")

    return opening_range_breakout(window, rules, equity)


SIGNALS: dict[str, PaperSignal] = {
    signal.id: signal
    for signal in (
        PaperSignal(
            "orb_breakout",
            "Opening range breakout",
            "Mesfin (2026) arXiv:2605.04004 §4.1",
            "FAIL — best long t=1.50; -1.42 in 2022 against +7.04 in 2024",
            opening_range_breakout,
            tested_on="MNQ (Micro E-Mini Nasdaq 100) futures, 5-minute bars, 947 days 2021-2025",
            recommended_class="futures",
            logic=(
                "Take the first 5 minutes of the session as the opening range.",
                "Require it to close above its own open — the paper's long side only.",
                "Fire when a later bar closes above the range high.",
                "Stop at the range high minus 1.4 x ATR(14).",
                "Target 2R and 3R; forced flat at the session close.",
            ),
        ),
        PaperSignal(
            "range_expansion",
            "Range expansion continuation",
            "Mesfin (2026) arXiv:2605.04004 §4.2",
            "FAIL — t=-10.96, significantly backwards; the move is consumed inside the bar",
            range_expansion,
            tested_on="MNQ (Micro E-Mini Nasdaq 100) futures, 5-minute bars, 947 days 2021-2025",
            recommended_class="futures",
            logic=(
                "Take the mean bar range over the previous 20 bars.",
                "Fire when the signal bar's range exceeds 2.5x that mean and closes up.",
                "Stop at the expansion bar's low.",
                "The paper's finding is that entry lands after the move is already over.",
            ),
        ),
        PaperSignal(
            "liquidity_grab",
            "Liquidity grab reversal",
            "Mesfin (2026) arXiv:2605.04004 §4.3",
            "FAIL — t=-14.12 fading, -13.24 following; real but below the friction ceiling",
            liquidity_grab_reversal,
            tested_on="MNQ (Micro E-Mini Nasdaq 100) futures, 5-minute bars, 947 days 2021-2025",
            recommended_class="futures",
            logic=(
                "Track the lowest low of the previous 20 bars in this session.",
                "Fire when a bar pierces that low but closes back above it.",
                "Stop at the piercing bar's low — the level that was just swept.",
            ),
        ),
        PaperSignal(
            "gap_fill_fade",
            "Gap fill fade",
            "Mesfin (2026) arXiv:2605.04004 §4.4",
            "FAIL — t between -0.32 and -0.59 across three entry times; noise",
            gap_fill_fade,
            tested_on="MNQ (Micro E-Mini Nasdaq 100) futures, 5-minute bars, 947 days 2021-2025",
            recommended_class="futures",
            logic=(
                "Compare today's session open to the previous session's close.",
                "Fire when the gap is down by more than 0.3%, betting it closes.",
                "Stop 1.4 x ATR(14) below entry.",
            ),
        ),
        PaperSignal(
            "gap_continuation",
            "Gap continuation",
            "Mesfin (2026) arXiv:2605.04004 §4.4",
            "FAIL on sample size — t=3.23 but only 22 trades in three years, and declining",
            gap_continuation,
            tested_on="MNQ (Micro E-Mini Nasdaq 100) futures, 5-minute bars, 947 days 2021-2025",
            recommended_class="futures",
            logic=(
                "Same gap measure, opposite direction: up by more than 0.3%.",
                "Require price still above the session open — the gap has not faded.",
                "Stop 1.4 x ATR(14) below the session open.",
                "Coded without the paper's Kalman filter, which is what cut it to 22 trades.",
            ),
        ),
        PaperSignal(
            "volume_spike",
            "Volume spike momentum",
            "Mesfin (2026) arXiv:2605.04004 §4.5",
            "FAIL — t=+0.07 on 2,119 events; a precise null, not an underpowered test",
            volume_spike_momentum,
            tested_on="MNQ (Micro E-Mini Nasdaq 100) futures, 5-minute bars, 947 days 2021-2025",
            recommended_class="futures",
            logic=(
                "Take the volume z-score against the previous 20 bars.",
                "Fire when z exceeds 2.0 and the bar closes up.",
                "Stop at the spike bar's low.",
            ),
        ),
        PaperSignal(
            "volume_dryup",
            "Volume dry-up exhaustion",
            "Mesfin (2026) arXiv:2605.04004 §4.5",
            "FAIL — t=-0.92 on 1,060 events",
            volume_dryup_reversal,
            tested_on="MNQ (Micro E-Mini Nasdaq 100) futures, 5-minute bars, 947 days 2021-2025",
            recommended_class="futures",
            logic=(
                "Same z-score, inverted: fire when z falls below -1.0.",
                "Require price below its own 20-bar mean, so it is exhaustion after a fall.",
                "Stop at the signal bar's low.",
            ),
        ),
        PaperSignal(
            "volatility_regime",
            "Volatility regime reversal",
            "Mesfin (2026) arXiv:2605.04004 §4.6",
            "FAIL — t=+0.86; the classifier's descriptive findings are real, the trades are not",
            volatility_regime_reversal,
            tested_on="MNQ (Micro E-Mini Nasdaq 100) futures, 5-minute bars, 947 days 2021-2025",
            recommended_class="futures",
            logic=(
                "Measure the session's high-to-low range against the 20-bar mean range.",
                "Fire when the session is unusually wide and price is below its open.",
                "Stop at the session low.",
                "Simplified: the paper's classifier needs three pre-market terciles the scanner does not carry.",
            ),
        ),
        PaperSignal(
            "ou_reversion",
            "Ornstein-Uhlenbeck mean reversion",
            "Mesfin (2026) arXiv:2605.04004 §4.8",
            "FAIL — t=-2.19 at 2.0sd; half-life longer than a session at 60-minute resolution",
            ou_mean_reversion,
            tested_on="MNQ (Micro E-Mini Nasdaq 100) futures, 5-minute bars, 947 days 2021-2025",
            recommended_class="futures",
            logic=(
                "Take the z-score of the close against the previous 60 closes.",
                "Fire when it falls below -2.0 standard deviations.",
                "Stop 1.5 standard deviations below entry.",
            ),
        ),
        PaperSignal(
            "orb_in_play",
            "Opening range breakout on a stock in play",
            "Zarattini, Barbon & Aziz (2024) SSRN 4729284",
            "Sharpe 2.81, 2016-2023, top-20 basket — the only positive prior here, and it is "
            "a selection result that contradicts Mesfin's single-instrument ORB",
            orb_stock_in_play,
            tested_on="~7,000 US equities, 5-minute opening range, 2016-2023",
            recommended_class="equity",
            logic=(
                "Sum the first 5 minutes' volume for today.",
                "Compare it to the mean first-5-minute volume of the prior sessions.",
                "Refuse unless that ratio clears 1.0 — the selection step IS the strategy.",
                "Then apply the plain opening range breakout above.",
            ),
        ),
    )
}
