"""Comparing two independent vendors' account of the same instrument-day.

Every other check in this engine asks whether one source is *internally*
plausible. This one asks whether two sources that were never coordinated
agree — NSE's official end-of-day bhavcopy, and Zerodha's 1-minute bars
aggregated to a day. Neither was derived from the other, so a disagreement is
evidence rather than a threshold I picked.

That makes it the check most likely to find something genuinely unknown, and
also the one most likely to produce false alarms, because the two sources
legitimately differ in ways that are not defects:

* **The daily close is not the last traded price.** NSE computes the official
  close as a volume-weighted average of the last 30 minutes, so it routinely
  differs from the final minute bar by a few tenths of a percent. Anything
  comparing them exactly would report every single day.
* **Kite's bars cover the continuous session only.** The pre-open auction and
  any post-close activity are outside them.
* **Volume is reported on different bases** often enough that comparing it
  strictly is noise, so it is compared only for order-of-magnitude agreement.

The tolerances below exist because of those, not to make the numbers look
good. A disagreement beyond them means one of the two is wrong about a real
number, which is worth a person's attention.
"""

from __future__ import annotations

from collections.abc import Sequence

from eulerlab.quality.findings import Finding, Severity
from eulerlab.quality.row_checks import Bar

CLOSE_TOLERANCE = 0.01
"""1%. Wide enough for the VWAP-vs-last-trade difference described above,
narrow enough that a stale day, a wrong instrument or an unadjusted split
cannot hide inside it."""

RANGE_TOLERANCE = 0.02
"""2% on the day's high and low. Looser than the close because the extremes
are single prints and more exposed to a session-boundary difference."""

VOLUME_RATIO_LIMIT = 10.0
"""An order of magnitude. Volume conventions differ enough between vendors
that anything tighter is noise; a factor of ten is a units error."""


def _relative(a: float, b: float) -> float:
    return abs(a - b) / a if a else float("inf")


def reconcile_day(
    official: Sequence[Bar], other: Sequence[Bar], *, source_name: str = "kite_minute"
) -> list[Finding]:
    """Compare two vendors' bars for one trading day, matched by symbol.

    Symbols present in only one source are *not* reported here. That is a
    coverage question, not a correctness one — Kite's universe is 420 symbols
    against bhavcopy's ~2,000, so reporting the difference would bury every
    real finding under seventeen hundred irrelevant ones.
    """
    by_symbol = {bar.symbol: bar for bar in other}
    out: list[Finding] = []

    for bar in official:
        twin = by_symbol.get(bar.symbol)
        if twin is None or bar.day != twin.day:
            continue

        for field, tolerance, mine, theirs in (
            ("close", CLOSE_TOLERANCE, bar.close, twin.close),
            ("high", RANGE_TOLERANCE, bar.high, twin.high),
            ("low", RANGE_TOLERANCE, bar.low, twin.low),
        ):
            drift = _relative(mine, theirs)
            if drift > tolerance:
                out.append(
                    Finding(
                        check="cross-source",
                        severity=Severity.WARN,
                        dataset="nse",
                        symbol=bar.symbol,
                        day=bar.day,
                        detail=(
                            f"{field}: bhavcopy {mine} vs {source_name} {theirs} "
                            f"({drift:.1%} apart, tolerance {tolerance:.0%})"
                        ),
                    )
                )

        if bar.volume > 0 and twin.volume > 0:
            ratio = max(bar.volume, twin.volume) / min(bar.volume, twin.volume)
            if ratio > VOLUME_RATIO_LIMIT:
                out.append(
                    Finding(
                        check="cross-source-volume",
                        severity=Severity.WARN,
                        dataset="nse",
                        symbol=bar.symbol,
                        day=bar.day,
                        detail=(
                            f"volume differs {ratio:.0f}x: bhavcopy {bar.volume:,.0f} "
                            f"vs {source_name} {twin.volume:,.0f}"
                        ),
                    )
                )

    return out


def coverage_summary(official: Sequence[Bar], other: Sequence[Bar]) -> Finding:
    """How much of the official universe the second source covers.

    Reported once as INFO rather than per missing symbol. The number itself is
    the useful thing: if it drops sharply from one run to the next, the second
    source stopped delivering, and that is invisible in a per-symbol check
    that skips absent twins.
    """
    official_symbols = {b.symbol for b in official}
    other_symbols = {b.symbol for b in other}
    overlap = official_symbols & other_symbols
    pct = 100.0 * len(overlap) / len(official_symbols) if official_symbols else 0.0
    return Finding(
        check="cross-source-coverage",
        severity=Severity.INFO,
        dataset="nse",
        detail=(
            f"{len(overlap):,} of {len(official_symbols):,} bhavcopy symbols "
            f"({pct:.1f}%) have a comparable second source"
        ),
    )
