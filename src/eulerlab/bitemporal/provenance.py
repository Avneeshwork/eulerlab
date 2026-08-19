"""When a fact became knowable, as distinct from when we happened to fetch it.

The landing-zone manifests record a field called `knowledge_time`. It is the
moment *we* downloaded the file. That is a real, measured, useful number — but
it is not what a backtest means by knowledge time, and using it as one is
catastrophic rather than merely imprecise.

Measured on this repository's own manifest: the median gap between a file's
trade date and our download of it is **1,820 days**, and the earliest download
timestamp across all 7,378 NSE files is 2026-08-18. Taken literally, nothing in
eleven years of history was knowable until yesterday, and every backtest
returns an empty frame.

So three separate times, never conflated:

- `event_time` — when it happened in the market.
- `knowledge_time` — when it first became knowable **to anyone**. This is what
  a backtest must filter on, because it answers the counterfactual the backtest
  is asking: what would a strategy running that day have seen?
- `receipt_time` — when **we** fetched it. Measured, immutable, and the right
  clock for auditing our own pipeline. Never the right clock for a backtest.

## The limitation this exposes, which cannot be engineered away

For backfilled data we hold whatever the exchange serves *today*. If NSE ever
corrected a bhavcopy after first publishing it, we have the correction and no
record that it was ever different. So our `knowledge_time` is honest about
*timing* and silent about *revision*: it says "this was knowable that evening",
which is true, but it cannot say "and this is the version that was published".

That distinction is invisible in the data and cannot be recovered from it, so
it is carried in the type instead. `Vintage.FINAL` means exactly "correct
timing, possibly-corrected content". Only same-day captures are `Vintage.LIVE`.
There are currently four of those.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from enum import StrEnum
from pathlib import Path
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

# When each feed becomes knowable. The error here is deliberately one-sided:
# assuming a *later* publication than the truth can only withhold data from a
# backtest, while assuming an earlier one manufactures a leak. So every value
# below is the latest time consistent with what we actually know.
#
# ASSUMPTION A-014: no primary NSE document has been read for these hours. See
# docs/ASSUMPTIONS.md and recheck before any intraday strategy depends on them.
DEFAULT_PUBLICATION_TIME_IST = time(20, 0)

PUBLICATION_TIME_IST: dict[str, time] = {
    # Unsourced, deliberately late.
    "cm": DEFAULT_PUBLICATION_TIME_IST,
    "fo": DEFAULT_PUBLICATION_TIME_IST,
    # Bounded by evidence rather than assumed: our one same-day capture of this
    # feed was fetched at 19:09 IST on 2026-08-18, so it was published no later
    # than that. The 20:00 default contradicted this measurement and the guard
    # below caught it. Using the observed bound keeps the value consistent with
    # the only evidence we have while staying on the safe side of it.
    "participant_oi": time(19, 9),
}


# A capture this soon after the trade date observed the data essentially as it
# was published, so no correction can have intervened unseen.
LIVE_CAPTURE_WINDOW = timedelta(days=2)

# The session close. Bhavcopy describes a whole session, so the event is the
# moment the session ended, not midnight.
SESSION_CLOSE_IST = time(15, 30)


class Vintage(StrEnum):
    """Whether we observed a fact as published, or only its surviving version."""

    LIVE = "live"
    """Captured within days of the event. A true point-in-time observation."""

    FINAL = "final"
    """Backfilled. The timing is right; the content is whatever the source
    serves now. If it was ever corrected, we hold the correction silently."""


@dataclass(frozen=True)
class Provenance:
    """The three times of one landed file, kept separate on purpose."""

    trade_date: str
    segment: str
    path: str
    event_time: datetime
    knowledge_time: datetime
    receipt_time: datetime
    vintage: Vintage

    @property
    def backfill_lag(self) -> timedelta:
        """How long after it was knowable we actually got it."""
        return self.receipt_time - self.knowledge_time


def knowable_at(trade_date: str, segment: str) -> datetime:
    """When `segment`'s file for `trade_date` first became knowable to anyone."""
    day = datetime.strptime(trade_date, "%Y-%m-%d").replace(tzinfo=IST).date()
    published = PUBLICATION_TIME_IST.get(segment, DEFAULT_PUBLICATION_TIME_IST)
    return datetime.combine(day, published, tzinfo=IST)


def session_close(trade_date: str) -> datetime:
    """The event time of a whole session: the moment it closed."""
    day = datetime.strptime(trade_date, "%Y-%m-%d").replace(tzinfo=IST).date()
    return datetime.combine(day, SESSION_CLOSE_IST, tzinfo=IST)


def from_manifest_row(row: dict[str, object]) -> Provenance:
    """Read one manifest line into three distinct times.

    The manifest's field named `knowledge_time` is read as `receipt_time`,
    which is what it has always actually held. The name in the file is left
    alone: the landing zone is immutable, and rewriting history to fix a
    label would be a worse sin than the label.
    """
    trade_date = str(row["trade_date"])
    receipt = datetime.fromisoformat(str(row["knowledge_time"]))
    if receipt.tzinfo is None:
        receipt = receipt.replace(tzinfo=UTC)
    segment = str(row["segment"])
    knowable = knowable_at(trade_date, segment)

    if receipt < knowable:
        # We hold a file before the exchange could have published it. Either the
        # publication assumption is wrong or a clock is. Both are bugs, and
        # guessing which would bake the error in.
        msg = (
            f"{trade_date}/{segment}: fetched at {receipt.isoformat()}, "
            f"before it was publishable at {knowable.isoformat()}. "
            f"Check PUBLICATION_TIME_IST (A-014) before trusting this file."
        )
        raise ValueError(msg)

    return Provenance(
        trade_date=trade_date,
        segment=segment,
        path=str(row["path"]),
        event_time=session_close(trade_date),
        knowledge_time=knowable,
        receipt_time=receipt,
        vintage=(Vintage.LIVE if receipt - knowable <= LIVE_CAPTURE_WINDOW else Vintage.FINAL),
    )


def read_manifest(path: Path) -> Iterator[Provenance]:
    """Stream a manifest file as provenance records."""
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield from_manifest_row(json.loads(line))


def main() -> int:
    """Print the vintage breakdown. This is the operator-checkable command."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default="data/landing/nse/manifest.jsonl")
    args = parser.parse_args()

    path = Path(args.manifest)
    if not path.exists():
        print(f"no manifest at {path} - nothing to audit")
        return 0

    records = list(read_manifest(path))
    counts = Counter(r.vintage for r in records)
    lags = sorted(r.backfill_lag.days for r in records)

    print(f"\nprovenance audit - {path}\n")
    print(f"{'VINTAGE':<10} {'FILES':>8}  MEANING")
    print(
        f"{'live':<10} {counts[Vintage.LIVE]:>8}  captured as published; content is point-in-time"
    )
    print(f"{'final':<10} {counts[Vintage.FINAL]:>8}  timing correct, content is today's version")
    if lags:
        print("\nbackfill lag (days between knowable and fetched):")
        print(f"  min {lags[0]}   median {lags[len(lags) // 2]}   max {lags[-1]}")
    print(
        "\nA backtest filters on knowledge_time, which is derived from the trade\n"
        "date (A-014), never on the manifest's download timestamp. Filtering on\n"
        f"the download timestamp would make every date before "
        f"{min(r.receipt_time for r in records).date() if records else 'n/a'} return nothing.\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
