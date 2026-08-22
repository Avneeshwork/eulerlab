"""Minute-level crypto intraday signals, priced against Delta Exchange India.

### Provenance is a field, not a footnote

Ten signals, and they do **not** all have the same standing. One is from a
peer-reviewed paper whose rules were read in full; several are families the
academic literature documents; the rest are practitioner constructions that are
widely used and, as far as this search found, never validated in a journal.

Conflating those would be the more comfortable presentation and the less useful
one, so `provenance` is a field on every signal and the interface shows it. A
practitioner rule is not worthless — it is untested, which is a different thing
and is exactly what this platform exists to measure.

### The cost is the point

Crypto has run gross of costs here since it landed (S-028). These are priced
against Delta Exchange India's published schedule: 0.05% taker, 0.02% maker,
plus 18% GST on the fee, so a taker round trip is **0.118% of notional**.

That number decides most of what follows. A minute-level signal has to clear
0.118% per round trip before it has earned anything, and Mesfin's MNQ study
found no intraday family whose gross edge cleared a comparable friction. The
prior for everything here is therefore negative, and a positive result is a
claim against evidence rather than in a vacuum.

### Sessions, for a market that has none

Crypto trades continuously, so "the session" is a convention rather than a
fact. Midnight UTC is used throughout because that is where the daily bar
already breaks in `alt_panel`, and two definitions of a day inside one
repository is how a backtest ends up disagreeing with itself.
"""

from __future__ import annotations

import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from eulerlab.features.indicators import atr, sma
from eulerlab.intraday.papers import PaperRules, _plan, _session_bars, _volume_z
from eulerlab.intraday.tweezer import Candle, Plan, Rejected

Detect = Callable[[Sequence[Candle], PaperRules, float], "Plan | Rejected"]


@dataclass(frozen=True)
class CryptoSignal:
    """One coded crypto signal, and how much to believe it before running it."""

    id: str
    title: str
    provenance: str
    """`paper`, `literature` or `practitioner`.

    - `paper` — rules read from a specific peer-reviewed publication.
    - `literature` — the effect is documented academically; the exact
      parameters here are ours.
    - `practitioner` — widely used, no academic validation found. Not a
      dismissal: untested is a measurable state, and measuring it is the job.
    """

    source: str
    published: str
    logic: tuple[str, ...]
    detect: Detect


# --- helpers ----------------------------------------------------------------


def _vwap(bars: Sequence[Candle]) -> float | None:
    """Volume-weighted average price over the given bars.

    Returns None rather than falling back to a simple mean when volume is
    absent. A "VWAP" computed without volume is just a moving average wearing
    its name, and every conclusion drawn from it would be about the wrong
    indicator.
    """
    volume = sum(bar.volume for bar in bars)
    if volume <= 0:
        return None
    return sum(((b.high + b.low + b.close) / 3.0) * b.volume for b in bars) / volume


def _poly_fit_next(values: Sequence[float], degree: int = 2) -> float | None:
    """Where a degree-2 least-squares fit says the next point should sit.

    Cohen (2023) fits a polynomial autoregression to recent minute closes and
    trades the gap between price and that line. Solved by normal equations on a
    tiny system rather than pulling in numpy: the window is dozens of points and
    a dependency for a 3x3 solve would cost more than it saves.
    """
    n = len(values)
    if n < degree + 2:
        return None
    xs = list(range(n))
    # Normal equations for a degree-2 fit: sums of x^k up to x^4.
    powers = [sum(x**k for x in xs) for k in range(2 * degree + 1)]
    targets = [sum((x**k) * y for x, y in zip(xs, values, strict=True)) for k in range(degree + 1)]
    size = degree + 1
    matrix = [
        [float(powers[row + col]) for col in range(size)] + [float(targets[row])]
        for row in range(size)
    ]

    for col in range(size):
        pivot = max(range(col, size), key=lambda r: abs(matrix[r][col]))
        if abs(matrix[pivot][col]) < 1e-12:
            return None
        matrix[col], matrix[pivot] = matrix[pivot], matrix[col]
        for row in range(size):
            if row == col:
                continue
            factor = matrix[row][col] / matrix[col][col]
            for k in range(col, size + 1):
                matrix[row][k] -= factor * matrix[col][k]
    coeffs = [matrix[i][size] / matrix[i][i] for i in range(size)]
    return float(sum(c * (n**i) for i, c in enumerate(coeffs)))


# --- 1. Cohen (2023): polynomial autoregression deviation --------------------


def par_deviation(window: Sequence[Candle], rules: PaperRules, equity: float) -> Plan | Rejected:
    """Price above a polynomial fit of recent closes, by more than a buffer.

    Cohen fits a polynomial autoregression to intraday closes and takes a long
    when `P_i > Pol_i + delta`, short when below. The buffer exists to suppress
    the false entries a bare crossing generates; his best Bitcoin result used
    67-minute bars, so this is a shorter-horizon variant of the same rule.
    """
    if len(window) < rules.ou_lookback + 2:
        return Rejected("warmup")
    closes = [c.close for c in window[-rules.ou_lookback :]]
    fit = _poly_fit_next(closes)
    if fit is None or fit <= 0:
        return Rejected("no fit")

    signal = window[-1]
    buffer = fit * (rules.min_risk_pct / 100.0)
    if signal.close <= fit + buffer:
        return Rejected("inside the buffer", f"{(signal.close / fit - 1) * 100:.3f}%")

    return _plan(signal=signal, entry=signal.close, stop=fit, rules=rules, equity=equity)


# --- 2. Session momentum -----------------------------------------------------


def session_momentum(window: Sequence[Candle], rules: PaperRules, equity: float) -> Plan | Rejected:
    """The day's move so far, continued.

    The intraday-momentum literature finds the first interval of a session
    predicts the last. Crypto has no session, so the UTC day stands in — and
    that substitution is the whole reason this is `literature` rather than
    `paper`: the effect is documented, the boundary is a convention.
    """
    session = _session_bars(window)
    if len(session) < 30 or len(window) < rules.atr_period * 2:
        return Rejected("warmup", f"{len(session)} session bars")

    opening = session[0].open
    if opening <= 0 or session[-1].close <= opening:
        return Rejected("not up on the session")

    band = atr(
        [c.high for c in window],
        [c.low for c in window],
        [c.close for c in window],
        period=rules.atr_period,
    )
    level = band[-1] if band and band[-1] is not None else None
    if level is None or level <= 0:
        return Rejected("no ATR")

    signal = session[-1]
    return _plan(
        signal=signal,
        entry=signal.close,
        stop=signal.close - rules.stop_atr_mult * level,
        rules=rules,
        equity=equity,
    )


# --- 3. Session reversal -----------------------------------------------------


def session_reversal(window: Sequence[Candle], rules: PaperRules, equity: float) -> Plan | Rejected:
    """The day's move so far, faded.

    The same literature reports reversal at some intraday horizons and momentum
    at others, which is why both are coded. Running only the one that agrees
    with a prior is how a library becomes an argument.
    """
    session = _session_bars(window)
    if len(session) < 30:
        return Rejected("warmup")

    opening = session[0].open
    signal = session[-1]
    if opening <= 0 or signal.close >= opening:
        return Rejected("not down on the session", "the long fade needs a decline")

    return _plan(
        signal=signal,
        entry=signal.close,
        stop=min(c.low for c in session),
        rules=rules,
        equity=equity,
    )


# --- 4 & 5. VWAP -------------------------------------------------------------


def vwap_reversion(window: Sequence[Candle], rules: PaperRules, equity: float) -> Plan | Rejected:
    """Price stretched below session VWAP, faded back toward it."""
    session = _session_bars(window)
    if len(session) < 30:
        return Rejected("warmup")
    level = _vwap(session)
    if level is None:
        return Rejected("no volume", "VWAP without volume is a moving average")

    signal = session[-1]
    stretch = (level - signal.close) / level * 100.0
    if stretch < rules.min_risk_pct:
        return Rejected("not stretched", f"{stretch:.3f}% below VWAP")

    return _plan(
        signal=signal,
        entry=signal.close,
        stop=min(c.low for c in session[-30:]),
        rules=rules,
        equity=equity,
    )


def vwap_breakout(window: Sequence[Candle], rules: PaperRules, equity: float) -> Plan | Rejected:
    """A close back above session VWAP on rising volume."""
    session = _session_bars(window)
    if len(session) < 30 or len(window) < rules.volume_lookback + 2:
        return Rejected("warmup")
    level = _vwap(session)
    if level is None:
        return Rejected("no volume")

    signal, previous = session[-1], session[-2]
    if not (previous.close <= level < signal.close):
        return Rejected("no cross", "needs a close crossing up through VWAP")
    z = _volume_z(window, rules.volume_lookback)
    if z is None or z <= 0:
        return Rejected("volume not rising", f"z={z if z is not None else 'n/a'}")

    return _plan(signal=signal, entry=signal.close, stop=level, rules=rules, equity=equity)


# --- 6. UTC-day opening range ------------------------------------------------


def utc_open_range(window: Sequence[Candle], rules: PaperRules, equity: float) -> Plan | Rejected:
    """Break of the first minutes of the UTC day.

    An opening range needs an open, and crypto has none. Midnight UTC is a
    convention borrowed from where the daily bar already breaks — so a result
    here is partly a statement about that convention, which is worth knowing
    before reading it as one about crypto.
    """
    session = _session_bars(window)
    span = max(rules.opening_range_minutes, 15)
    if len(session) <= span:
        return Rejected("warmup")

    opening = session[:span]
    high = max(c.high for c in opening)
    signal = session[-1]
    if signal.close <= high:
        return Rejected("no breakout")

    return _plan(
        signal=signal,
        entry=signal.close,
        stop=min(c.low for c in opening),
        rules=rules,
        equity=equity,
    )


# --- 7. Volume climax --------------------------------------------------------


def volume_climax(window: Sequence[Candle], rules: PaperRules, equity: float) -> Plan | Rejected:
    """An extreme volume bar that closes strong, taken as continuation."""
    if len(window) < rules.volume_lookback + 2:
        return Rejected("warmup")
    z = _volume_z(window, rules.volume_lookback)
    if z is None or z < rules.volume_spike_z * 1.5:
        return Rejected("no climax", f"z={z if z is not None else 'n/a'}")

    signal = window[-1]
    span = signal.high - signal.low
    if span <= 0 or (signal.close - signal.low) / span < 0.7:
        return Rejected("weak close", "a climax bar must close in its upper third")

    return _plan(signal=signal, entry=signal.close, stop=signal.low, rules=rules, equity=equity)


# --- 8. Range compression ----------------------------------------------------


def range_compression(
    window: Sequence[Candle], rules: PaperRules, equity: float
) -> Plan | Rejected:
    """Break out of an unusually quiet stretch."""
    if len(window) < rules.expansion_lookback * 2:
        return Rejected("warmup")
    recent = window[-rules.expansion_lookback :]
    prior = window[-rules.expansion_lookback * 2 : -rules.expansion_lookback]
    quiet = statistics.fmean(c.high - c.low for c in recent)
    normal = statistics.fmean(c.high - c.low for c in prior)
    if normal <= 0 or quiet > normal * 0.6:
        return Rejected("not compressed", f"{quiet / normal:.2f}x prior range" if normal else "")

    ceiling = max(c.high for c in recent[:-1])
    signal = window[-1]
    if signal.close <= ceiling:
        return Rejected("no breakout")

    return _plan(
        signal=signal,
        entry=signal.close,
        stop=min(c.low for c in recent),
        rules=rules,
        equity=equity,
    )


# --- 9. Trend pullback -------------------------------------------------------


def trend_pullback(window: Sequence[Candle], rules: PaperRules, equity: float) -> Plan | Rejected:
    """A dip to the moving average inside an uptrend."""
    if len(window) < rules.ou_lookback + 2:
        return Rejected("warmup")
    closes = [c.close for c in window]
    trend = sma(closes, rules.ou_lookback)
    level = trend[-1] if trend and trend[-1] is not None else None
    earlier = trend[-rules.expansion_lookback] if len(trend) > rules.expansion_lookback else None
    if level is None or earlier is None or level <= earlier:
        return Rejected("no uptrend")

    signal = window[-1]
    if signal.low > level or signal.close < level:
        return Rejected("no pullback", "needs a dip to the mean that closes back above it")

    return _plan(signal=signal, entry=signal.close, stop=signal.low, rules=rules, equity=equity)


# --- 10. Funding-window drift ------------------------------------------------


def funding_drift(window: Sequence[Candle], rules: PaperRules, equity: float) -> Plan | Rejected:
    """The hour before a perpetual funding stamp.

    Delta's perpetuals settle funding every eight hours at 00:00, 08:00 and
    16:00 UTC. Positioning ahead of the stamp is a documented practitioner
    behaviour, and it is the one signal here whose premise is a *venue
    mechanic* rather than a price pattern.

    **The honest caveat is large.** This platform does not have the funding
    rate — only price — so what is coded is the price drift in that hour, not
    the funding trade itself. A result here says something about the hour, not
    about the mechanic that makes the hour interesting.
    """
    signal = window[-1]
    if signal.ts.hour not in (7, 15, 23):
        return Rejected("not a funding hour", f"{signal.ts.hour:02d}:00 UTC")
    if len(window) < rules.atr_period * 2:
        return Rejected("warmup")
    if signal.close <= signal.open:
        return Rejected("hour not trending up")

    band = atr(
        [c.high for c in window],
        [c.low for c in window],
        [c.close for c in window],
        period=rules.atr_period,
    )
    level = band[-1] if band and band[-1] is not None else None
    if level is None or level <= 0:
        return Rejected("no ATR")

    return _plan(
        signal=signal,
        entry=signal.close,
        stop=signal.close - rules.stop_atr_mult * level,
        rules=rules,
        equity=equity,
    )


CRYPTO_SIGNALS: dict[str, CryptoSignal] = {
    signal.id: signal
    for signal in (
        CryptoSignal(
            "par_deviation",
            "Polynomial autoregression deviation",
            "paper",
            "Cohen, G. (2023). Intraday trading of cryptocurrencies using polynomial "
            "auto regression. AIMS Mathematics 8(4): 9782-9794. DOI 10.3934/math.2023493",
            "Net profit 15.58% on Bitcoin using 67-minute bars against -44.8% buy-and-hold, "
            "over six months of out-of-sample trading",
            (
                "Fit a degree-2 least-squares curve to the last 60 minute closes.",
                "Project it one bar forward to get the expected price.",
                "Go long when the close exceeds that projection by a buffer.",
                "Stop at the projection line itself.",
            ),
            par_deviation,
        ),
        CryptoSignal(
            "session_momentum",
            "UTC-session momentum",
            "literature",
            "Intraday time-series momentum: the first interval of a session predicts the "
            "last. Documented for equities (Gao et al.) and reported for crypto by Wen, "
            "Bouri, Xu & Zhao, Intraday return predictability in the cryptocurrency markets",
            "Momentum and reversal both reported at different intraday horizons; the "
            "boundary here is a convention, not the papers' own",
            (
                "Take the UTC day's open as the session start.",
                "Require price above it — the day is up so far.",
                "Enter long at the current close, continuing the move.",
                "Stop 1.4 x ATR(14) below entry.",
            ),
            session_momentum,
        ),
        CryptoSignal(
            "session_reversal",
            "UTC-session reversal",
            "literature",
            "The opposite leg of the same intraday predictability literature",
            "Coded because the literature reports both; running only the leg that agrees "
            "with a prior is how a library becomes an argument",
            (
                "Take the UTC day's open as the session start.",
                "Require price below it — the day is down so far.",
                "Enter long against the move, expecting reversion.",
                "Stop at the session low.",
            ),
            session_reversal,
        ),
        CryptoSignal(
            "vwap_reversion",
            "VWAP reversion",
            "practitioner",
            "Widely documented practitioner rule; no academic validation found",
            "Untested, which is a measurable state rather than a dismissal",
            (
                "Compute session VWAP from the UTC day's bars.",
                "Require price stretched below it by more than the risk floor.",
                "Enter long, expecting a return toward VWAP.",
                "Stop at the low of the last 30 minutes.",
            ),
            vwap_reversion,
        ),
        CryptoSignal(
            "vwap_breakout",
            "VWAP breakout on rising volume",
            "practitioner",
            "Widely documented practitioner rule; no academic validation found",
            "Untested",
            (
                "Compute session VWAP from the UTC day's bars.",
                "Require the previous close below it and this close above — a crossing.",
                "Require the volume z-score against the last 20 bars to be positive.",
                "Stop at VWAP itself.",
            ),
            vwap_breakout,
        ),
        CryptoSignal(
            "utc_open_range",
            "UTC-day opening range breakout",
            "practitioner",
            "The opening-range family applied to a market with no open",
            "A result here is partly a statement about the midnight-UTC convention",
            (
                "Take the first 15 minutes of the UTC day as the opening range.",
                "Fire when a later bar closes above the range high.",
                "Stop at the opening range low.",
            ),
            utc_open_range,
        ),
        CryptoSignal(
            "volume_climax",
            "Volume climax continuation",
            "practitioner",
            "Practitioner construction; Mesfin (2026) tested the weaker volume-spike "
            "version on MNQ futures and measured a precise null at t=+0.07",
            "The nearest tested relative failed on 2,119 events",
            (
                "Require a volume z-score above 3.0 against the last 20 bars.",
                "Require the bar to close in its upper third — a strong close, not a wick.",
                "Stop at the climax bar's low.",
            ),
            volume_climax,
        ),
        CryptoSignal(
            "range_compression",
            "Compression breakout",
            "practitioner",
            "The volatility-squeeze family; no crypto-specific validation found",
            "Untested",
            (
                "Compare the mean bar range of the last 20 bars to the 20 before them.",
                "Require the recent stretch under 60% of prior — genuinely quiet.",
                "Fire on a close above the quiet stretch's high.",
                "Stop at the quiet stretch's low.",
            ),
            range_compression,
        ),
        CryptoSignal(
            "trend_pullback",
            "Trend pullback to the mean",
            "practitioner",
            "The buy-the-dip family; no crypto-specific validation found",
            "Untested",
            (
                "Require the 60-bar mean to be rising over the last 20 bars.",
                "Require this bar to dip to that mean and close back above it.",
                "Stop at the pullback bar's low.",
            ),
            trend_pullback,
        ),
        CryptoSignal(
            "funding_drift",
            "Funding-window drift",
            "practitioner",
            "Delta perpetuals settle funding at 00:00, 08:00 and 16:00 UTC",
            "The one signal whose premise is a venue mechanic rather than a price pattern "
            "— and the platform has price only, so what is coded is the hour, not the "
            "mechanic that makes the hour interesting",
            (
                "Fire only in the hour before a funding stamp (07, 15, 23 UTC).",
                "Require the hour to be trending up.",
                "Stop 1.4 x ATR(14) below entry.",
            ),
            funding_drift,
        ),
    )
}
