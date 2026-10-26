"""Is Binance a good source? Cross-check it against an independent exchange.

The Binance archive is convenient and free, which are exactly the properties
that should make one suspicious of trusting it alone. A single source cannot
be checked against itself: if its clock is wrong, or a month is silently
truncated, or a price is stale, nothing inside the file says so.

So the same minutes are fetched from a second exchange and the closes compared.
Two venues will never agree exactly — they are different order books with
different participants — so the question is not "are they identical" but "do
they agree to within the spread you would expect between two real markets".
`docs/RESEARCH/011` made the same argument for MAD over standard deviation:
the interesting statistic is the median, because a handful of bad prints must
not move it.

### The trap that makes this check worthless if unnoticed

**Kraken ignores `since`.** Asked for 2024-01-01 it returns *2026* bars, with no
error and no warning. A reconciliation that trusted it would compare Binance's
2024 against Kraken's 2026 and report a ~70% "disagreement" that is entirely a
timestamp bug — and the natural reading of that result is "Binance is wrong".

So every comparison here **verifies the timestamps line up before comparing any
price**, and a venue whose bars do not match the requested window is reported
as unusable rather than as disagreeing. Coinbase honours `since` correctly and
is the reference used.
"""

from __future__ import annotations

import gzip
import json
import statistics
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from eulerlab.ingest import crypto

REFERENCE_EXCHANGE = "coinbase"

# Binance quotes in USDT; Coinbase quotes in USD. They are different assets in
# principle and within a few basis points in practice, which is part of what
# this check measures rather than something it corrects for.
PAIR_MAP = {
    "BTCUSDT": "BTC/USD",
    "ETHUSDT": "ETH/USD",
    "XRPUSDT": "XRP/USD",
    "SOLUSDT": "SOL/USD",
    "DOGEUSDT": "DOGE/USD",
    "ADAUSDT": "ADA/USD",
    "LINKUSDT": "LINK/USD",
    "AVAXUSDT": "AVAX/USD",
    "XLMUSDT": "XLM/USD",
    "BCHUSDT": "BCH/USD",
    "UNIUSDT": "UNI/USD",
    "LTCUSDT": "LTC/USD",
    "AAVEUSDT": "AAVE/USD",
    "NEARUSDT": "NEAR/USD",
}


class Exchange(Protocol):
    def fetch_ohlcv(
        self, symbol: str, timeframe: str, since: int | None = None, limit: int | None = None
    ) -> list[list[Any]]: ...


@dataclass(frozen=True)
class Comparison:
    """One symbol's agreement between two venues over a sampled window."""

    symbol: str
    compared: int
    median_diff_pct: float
    p95_diff_pct: float
    max_diff_pct: float
    usable: bool
    note: str = ""

    @property
    def agrees(self) -> bool:
        """Under 0.5% median is two real books quoting the same asset.

        Not zero, and it should not be: Binance quotes against USDT and
        Coinbase against USD, the venues have different participants, and a
        minute bar is a sample of a continuous process. A median under half a
        percent means the disagreement is microstructure, not corruption.
        """
        return self.usable and self.median_diff_pct < 0.5


def _landed_closes(
    symbol: str, year_month: str, *, directory: Path | None = None
) -> dict[int, float]:
    """Landed closes keyed by epoch milliseconds."""
    path = crypto.month_path(symbol, year_month, directory=directory or crypto.LANDING)
    if not path.exists():
        return {}
    out: dict[int, float] = {}
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            when = datetime.fromisoformat(str(row["event_time"]))
            out[int(when.timestamp() * 1000)] = float(row["close"])
    return out


def compare(
    symbol: str,
    year_month: str,
    exchange: Exchange,
    *,
    samples: int = 6,
    per_sample: int = 60,
    directory: Path | None = None,
) -> Comparison:
    """Compare a sample of minutes against an independent venue.

    Sampled rather than exhaustive: the reference exchange serves 300 bars a
    call and rate-limits, so checking a whole month would take longer than
    downloading it. Six windows of an hour, spread across the month, is enough
    to catch a wrong clock, a stale feed, or a truncated file — which are the
    failures that matter and are never subtle.
    """
    ours = _landed_closes(symbol, year_month, directory=directory)
    if not ours:
        return Comparison(symbol, 0, 0.0, 0.0, 0.0, usable=False, note="nothing landed")

    pair = PAIR_MAP.get(symbol)
    if pair is None:
        return Comparison(symbol, 0, 0.0, 0.0, 0.0, usable=False, note="no reference pair mapped")

    stamps = sorted(ours)
    step = max(1, len(stamps) // samples)
    diffs: list[float] = []
    mismatched_windows = 0

    for index in range(0, len(stamps), step):
        since = stamps[index]
        try:
            rows = exchange.fetch_ohlcv(pair, "1m", since=since, limit=per_sample)
        except Exception as exc:
            return Comparison(
                symbol, len(diffs), 0.0, 0.0, 0.0, usable=False, note=f"reference failed: {exc}"
            )
        if not rows:
            continue

        # THE GUARD. A venue that ignores `since` returns a valid-looking series
        # from the wrong period, and comparing it would blame Binance for a
        # timestamp bug in the reference.
        if abs(int(rows[0][0]) - since) > 5 * 60 * 1000:
            mismatched_windows += 1
            continue

        for row in rows:
            stamp = int(row[0])
            theirs = float(row[4])
            mine = ours.get(stamp)
            if mine is None or mine <= 0 or theirs <= 0:
                continue
            diffs.append(abs(mine - theirs) / mine * 100.0)

        if len(diffs) >= samples * per_sample:
            break

    if mismatched_windows and not diffs:
        return Comparison(
            symbol,
            0,
            0.0,
            0.0,
            0.0,
            usable=False,
            note=(
                f"reference returned bars from the wrong period in "
                f"{mismatched_windows} window(s) — it is ignoring `since`, so it "
                f"cannot be used to check history"
            ),
        )
    if not diffs:
        return Comparison(symbol, 0, 0.0, 0.0, 0.0, usable=False, note="no overlapping minutes")

    ordered = sorted(diffs)
    return Comparison(
        symbol=symbol,
        compared=len(diffs),
        median_diff_pct=statistics.median(ordered),
        p95_diff_pct=ordered[int(len(ordered) * 0.95)],
        max_diff_pct=ordered[-1],
        usable=True,
    )


@dataclass(frozen=True)
class Finding:
    """One problem, named precisely enough to act on."""

    kind: str
    detail: str
    at: str = ""


def stale_runs(
    symbol: str, year_month: str, *, threshold: int = 30, directory: Path | None = None
) -> list[Finding]:
    """Runs of identical closes — what a frozen feed looks like.

    The check the archive most needed and did not have. OHLC bounds pass
    perfectly on a stale feed: every bar is internally consistent, the count is
    right, and the price simply stopped moving. Only the repetition gives it
    away.

    `threshold` is 30 minutes. Genuinely flat half-hours do happen in thin
    alt-coins at 3am, so this is a *finding* rather than a failure — but a
    liquid pair printing the same close for half an hour is a stopped clock,
    and a strategy reading it as calm will size into it.
    """
    path = crypto.month_path(symbol, year_month, directory=directory or crypto.LANDING)
    if not path.exists():
        return []

    findings: list[Finding] = []
    previous: float | None = None
    run = 0
    run_started = ""

    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            close = float(row["close"])
            when = str(row["event_time"])

            if previous is not None and close == previous:
                if run == 0:
                    run_started = when
                run += 1
            else:
                if run >= threshold:
                    findings.append(
                        Finding("stale", f"{run + 1} identical closes at {previous}", run_started)
                    )
                run = 0
            previous = close

    if run >= threshold:
        findings.append(Finding("stale", f"{run + 1} identical closes at {previous}", run_started))
    return findings


# Measured, not chosen. Across 2,437,704 minute returns sampled from 14 symbols
# and 56 symbol-months of the landed archive:
#
#     p50      0.0453%      p99.9    0.9322%
#     p90      0.1754%      p99.99   2.0515%
#     p99      0.4401%      p99.999  3.9683%
#     max      9.16%
#
# So an ordinary crypto minute moves ~0.05%, and the single largest move in the
# entire sample is 9.16% — a real market move, not a corrupt print.
EXTREME_MOVE_PCT = 12.0
"""One-minute return beyond which a print is not plausibly a market move.

Set above the 9.16% maximum actually observed, so it flags things the archive
has never yet contained rather than things it contains routinely.

The first version used 15x MAD and produced **37,140 findings**, flagging
1.2% minute moves as extreme. That is the identical mistake T-609 records on
the equity side, where a spike threshold of 5.0 turned out to be the *99th
percentile of ordinary trading*. Writing a comment citing that lesson did not
prevent repeating it; measuring the distribution did.
"""


def extreme_moves(
    symbol: str,
    year_month: str,
    *,
    threshold_pct: float = EXTREME_MOVE_PCT,
    directory: Path | None = None,
) -> list[Finding]:
    """Minute returns too large to be a market move.

    An absolute threshold rather than a dispersion multiple. Crypto volatility
    varies enormously between a quiet month in a large cap and a violent one in
    an alt, so a relative threshold flags the calm months and misses the wild
    ones — which is exactly backwards. What does not vary is that no honest
    minute bar moves 12%.
    """
    path = crypto.month_path(symbol, year_month, directory=directory or crypto.LANDING)
    if not path.exists():
        return []

    rows: list[dict[str, Any]] = []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))

    if len(rows) < 20:
        return []

    volumes = sorted(float(r["volume"]) for r in rows)
    # A thin month can have a median volume of exactly zero — most minutes
    # genuinely trade nothing — and dividing by it is how this check crashed
    # the first time it met a quiet alt-coin.
    typical_volume = volumes[len(volumes) // 2] or 1e-9

    findings: list[Finding] = []
    for index in range(1, len(rows)):
        previous, current = rows[index - 1], rows[index]
        before, after = float(previous["close"]), float(current["close"])
        if before <= 0:
            continue
        move = (after / before - 1.0) * 100.0
        if abs(move) <= threshold_pct:
            continue

        # Corroboration. A real move brings volume and trades with it; a
        # corrupt print does not. Verified against NEARUSDT 2021-12-15 04:00,
        # a +73% minute that looked like the worst outlier in the archive:
        # volume went from ~500 to 4,097,436 and trades from 22 to 40,691, and
        # the price held for the following ten minutes. That is a market, not
        # a bad tick.
        volume = float(current["volume"])
        trades = int(current["trades"] or 0)
        multiple = volume / typical_volume
        corroborated = multiple > 10 and trades > 100

        findings.append(
            Finding(
                "extreme-corroborated" if corroborated else "extreme-isolated",
                f"{move:+.2f}% in one minute, volume {volume:,.0f} "
                f"({multiple:,.0f}x typical), {trades:,} trades",
                str(current["event_time"]),
            )
        )
    return findings


def sanity_checks(symbol: str, year_month: str, *, directory: Path | None = None) -> list[str]:
    """Checks that need no second source at all.

    These catch the failures a cross-check would also catch but more cheaply,
    and they work for symbols no other venue lists.
    """
    path = crypto.month_path(symbol, year_month, directory=directory or crypto.LANDING)
    problems: list[str] = []
    if not path.exists():
        return [f"{symbol} {year_month}: not landed"]

    previous_stamp: int | None = None
    rows = 0
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            rows += 1
            high, low = float(row["high"]), float(row["low"])
            close, open_ = float(row["close"]), float(row["open"])

            if low > high:
                problems.append(f"low>high at {row['event_time']}")
            if not (low <= close <= high) or not (low <= open_ <= high):
                problems.append(f"open/close outside range at {row['event_time']}")
            if close <= 0:
                problems.append(f"non-positive close at {row['event_time']}")

            stamp = int(datetime.fromisoformat(str(row["event_time"])).timestamp() * 1000)
            if previous_stamp is not None and stamp <= previous_stamp:
                problems.append(f"time did not advance at {row['event_time']}")
            previous_stamp = stamp

            if len(problems) >= 20:
                problems.append("... further problems suppressed")
                break

    check = crypto.verify_month(symbol, year_month, directory=directory or crypto.LANDING)
    if not check.complete:
        problems.append(f"{check.missing:,} of {check.expected:,} minutes absent")
    return problems
