"""Checks on the price rows themselves.

Two kinds, and the difference matters more than it looks.

**Invariants are absolute.** `high` cannot be below `low`. There is no market
condition, no illiquidity, no circuit filter under which that is true data. A
violation is corruption, so it is ERROR no matter how rare, and no threshold
can be tuned to make it acceptable.

**Spikes are statistical.** A 40% single-day move is unusual but entirely
possible — it happens on results day, on a block deal, on an open offer. So a
spike is WARN, and it is measured with MAD rather than standard deviation for
the reason set out in `robust.py`: stdev is inflated by the very outlier being
hunted, so a big enough error hides itself.

These need real price data, which lives in B2 and costs a transaction per
file. They are therefore driven by a caller that supplies rows, rather than
fetching anything themselves — so the same functions run against a cached
index, a restored local file, or a test fixture without knowing the difference.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from eulerlab.quality.findings import Finding, Severity
from eulerlab.quality.robust import DEFAULT_THRESHOLD, spikes

MAX_SANE_DAILY_MOVE = 0.30
"""Beyond this, a single-day return is more likely an unadjusted corporate
action than a real move.

The threshold is set from what it must catch, not from what feels large. The
common corporate actions produce these apparent one-day moves:

| Action      | Apparent move |
|-------------|---------------|
| 1:2 bonus   | -33%          |
| 1:1 bonus   | -50%          |
| 2:1 split   | -50%          |
| 5:1 split   | -80%          |

The first draft used 0.60, which could not catch a 1:1 bonus at -50% — the
exact case the docstring claimed it existed for. 0.30 sits just below the
smallest of them and above the 20% circuit limit that caps most Indian scrips
on an ordinary day.

It will occasionally fire on a genuine move in an F&O-eligible name, which has
no fixed circuit. That is the right trade for a WARN: a false positive costs
one look at a chart, a false negative silently leaves a 50% phantom crash in
the return series.
"""


@dataclass(frozen=True)
class Bar:
    """One instrument-day of prices, normalised across both bhavcopy eras."""

    symbol: str
    day: date
    open: float
    high: float
    low: float
    close: float
    prev_close: float | None = None
    volume: float = 0.0
    turnover: float | None = None


def check_ohlc_invariants(bars: Sequence[Bar], dataset: str = "nse") -> list[Finding]:
    """Structural facts that cannot be false in real data."""
    out: list[Finding] = []
    for bar in bars:
        problems: list[str] = []
        if bar.high < bar.low:
            problems.append(f"high {bar.high} below low {bar.low}")
        if not (bar.low <= bar.open <= bar.high):
            problems.append(f"open {bar.open} outside [{bar.low}, {bar.high}]")
        if not (bar.low <= bar.close <= bar.high):
            problems.append(f"close {bar.close} outside [{bar.low}, {bar.high}]")
        if bar.volume < 0:
            problems.append(f"negative volume {bar.volume}")
        if any(p <= 0 for p in (bar.open, bar.high, bar.low, bar.close)):
            problems.append("a non-positive price")

        out.extend(
            Finding(
                check="ohlc-bounds",
                severity=Severity.ERROR,
                dataset=dataset,
                symbol=bar.symbol,
                day=bar.day,
                detail=problem,
            )
            for problem in problems
        )
    return out


def check_turnover_consistency(
    bars: Sequence[Bar], dataset: str = "nse", *, tolerance: float = 0.25
) -> list[Finding]:
    """Turnover should be roughly volume times a price inside the day's range.

    Deliberately loose. The true figure is volume times the *average traded*
    price, which is not in the file, so the tightest honest bound is that the
    implied price falls between the low and the high. A 25% margin either side
    absorbs rounding in the older files without letting a genuine
    factor-of-ten error through — and a factor of ten is what a units mistake
    looks like.
    """
    out: list[Finding] = []
    for bar in bars:
        if bar.turnover is None or bar.volume <= 0 or bar.turnover <= 0:
            continue
        implied = bar.turnover / bar.volume
        floor, ceiling = bar.low * (1 - tolerance), bar.high * (1 + tolerance)
        if not (floor <= implied <= ceiling):
            out.append(
                Finding(
                    check="turnover-consistency",
                    severity=Severity.WARN,
                    dataset=dataset,
                    symbol=bar.symbol,
                    day=bar.day,
                    detail=(
                        f"turnover/volume implies {implied:.2f}, outside the day's "
                        f"range [{bar.low}, {bar.high}] even with {tolerance:.0%} slack"
                    ),
                )
            )
    return out


def daily_returns(bars: Sequence[Bar]) -> list[tuple[Bar, float]]:
    """Close-to-close returns, using each row's own recorded previous close.

    Uses `prev_close` from the file rather than the previous row's close, so a
    missing day in the middle does not manufacture a fake two-day return.
    """
    out: list[tuple[Bar, float]] = []
    for bar in bars:
        if bar.prev_close and bar.prev_close > 0:
            out.append((bar, (bar.close - bar.prev_close) / bar.prev_close))
    return out


_RIGHTS_ENTITLEMENT = re.compile(r"-(RE|E)\d*$", re.IGNORECASE)
"""Rights-entitlement lines: ACME-RE, ACME-RE1, ACME-E1.

A separate, temporary instrument representing the *right* to subscribe, not
the share. It is nearly worthless by construction, expires within weeks, and
routinely moves tens of percent on a fraction of a rupee - 0.05 to 0.03 is
-40% and entirely normal. Measured: 52 of 235 extreme-move findings were
these. They are excluded rather than suppressed by id, because there is
nothing anomalous to record - the check simply does not apply to them.
"""


def is_rights_entitlement(symbol: str) -> bool:
    return bool(_RIGHTS_ENTITLEMENT.search(symbol))


def check_extreme_moves(bars: Sequence[Bar], dataset: str = "nse") -> list[Finding]:
    """Single-day moves too large to be an ordinary market event.

    An absolute bound, not a statistical one, so it fires on the first bar of
    a series where a spike test has no history to compare against.
    """
    return [
        Finding(
            check="extreme-move",
            severity=Severity.WARN,
            dataset=dataset,
            symbol=bar.symbol,
            day=bar.day,
            detail=(
                f"{ret:+.1%} in one day ({bar.prev_close} -> {bar.close}); "
                f"check for an unadjusted corporate action"
            ),
        )
        for bar, ret in daily_returns(bars)
        if abs(ret) > MAX_SANE_DAILY_MOVE and not is_rights_entitlement(bar.symbol)
    ]


def check_return_spikes(
    bars: Sequence[Bar], dataset: str = "nse", *, threshold: float = DEFAULT_THRESHOLD
) -> list[Finding]:
    """Returns that are extreme *relative to this instrument's own history*.

    Catches what a fixed bound cannot: a 12% move is unremarkable in a small
    cap and very strange in a utility that has never moved more than 2%.
    """
    pairs = daily_returns(bars)
    if len(pairs) < 3:
        return []
    values = [ret for _, ret in pairs]
    return [
        Finding(
            check="return-spike",
            severity=Severity.WARN,
            dataset=dataset,
            symbol=pairs[index][0].symbol,
            day=pairs[index][0].day,
            detail=f"{value:+.1%} is {z:.1f} robust sigmas from this symbol's median move",
        )
        for index, value, z in spikes(values, threshold=threshold)
    ]


def check_staleness_runs(
    bars: Sequence[Bar], dataset: str = "nse", *, min_run: int = 10
) -> list[Finding]:
    """A price that has not changed for many consecutive sessions.

    Usually a genuinely untraded scrip, occasionally a feed repeating its last
    value — which is far more dangerous, because a flat series has zero
    volatility and will look like a risk-free asset to anything downstream.
    """
    out: list[Finding] = []
    run_start = 0
    for index in range(1, len(bars) + 1):
        ended = index == len(bars) or bars[index].close != bars[run_start].close
        if not ended:
            continue
        length = index - run_start
        if length >= min_run:
            out.append(
                Finding(
                    check="stale-price",
                    severity=Severity.WARN,
                    dataset=dataset,
                    symbol=bars[run_start].symbol,
                    day=bars[run_start].day,
                    detail=(
                        f"close stayed at {bars[run_start].close} for {length} consecutive sessions"
                    ),
                )
            )
        run_start = index
    return out


def run_row_checks(bars: Sequence[Bar], dataset: str = "nse") -> list[Finding]:
    """Every row-level check over one instrument's ordered history."""
    return [
        *check_ohlc_invariants(bars, dataset),
        *check_turnover_consistency(bars, dataset),
        *check_extreme_moves(bars, dataset),
        *check_return_spikes(bars, dataset),
        *check_staleness_runs(bars, dataset),
    ]
