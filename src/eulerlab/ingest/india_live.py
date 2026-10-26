"""`make india-live` — the Indian data, from one minute after the close until it is in.

The operator's rule (2026-10-26): the Indian update should not wait for 19:30.
It starts at 15:31 IST on weekdays (launchd, `make schedule ACTION=install
JOB=india-live`) and, every `INTERVAL` seconds until `DEADLINE`, runs the
Indian steps of the feed: bhavcopy, F&O, participant OI, index closes and
delivery, Kite minute bars, then whatever those feed (price panel, Nifty
options, paper books, provisional daily bars). ADR-079.

**When it stops.** Once today's cash bhavcopy is landed and today's minute
bars are landed, or the bhavcopy is landed and there is no Kite token minted
today (minute bars cannot come without one, so waiting is pointless). At
`DEADLINE` it stops regardless and says what is still missing; the 19:30
`make daily` is the next chance.

**While waiting, minute bars stand in.** `provisional_daily` builds daily bars
from the minute bars for the ~450 Kite symbols and retires them when the
bhavcopy lands. The paper books do not trade on them; they wait for the
bhavcopy.

Each pass takes the `feed` lock like every other run; a pass that finds it
held is skipped, not queued. Nothing is fetched twice: every step skips what
is already landed.
"""

from __future__ import annotations

import argparse
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

INTERVAL = 600.0
"""Ten minutes between passes. A pass with nothing new costs seconds."""

DEADLINE = (21, 0)
"""Stop by 21:00 IST. NSE's files are normally out well before; after that the
19:30 `make daily` has already had its go and tomorrow's run picks up the rest."""

INDIA_STEPS = (
    "NSE end-of-day",
    "participant OI",
    "NSE index closes and delivery",
    "India minute bars",
)
"""The fetches. `daily_feed.with_dependents` adds what they feed."""


@dataclass(frozen=True)
class Landed:
    bhavcopy: bool
    minute: bool
    token: bool

    @property
    def done(self) -> bool:
        return self.bhavcopy and (self.minute or not self.token)

    def missing(self) -> str:
        gone = [
            name
            for name, held in (
                ("bhavcopy", self.bhavcopy),
                ("minute bars" + ("" if self.token else " (no Kite token today)"), self.minute),
            )
            if not held
        ]
        return ", ".join(gone) or "nothing"


def landed(day: date) -> Landed:
    """What is held for `day`, from the manifests."""
    from eulerlab.broker import kite_session
    from eulerlab.ingest.coverage import LANDING, _max_by
    from eulerlab.ingest.provisional_daily import bhavcopy_days

    stamp = day.isoformat()
    kite = _max_by(LANDING / "kite_minute" / "manifest.jsonl", "", "end").get("", "")
    return Landed(
        bhavcopy=stamp in bhavcopy_days(),
        minute=kite >= stamp,
        token=kite_session.is_fresh(kite_session.load()),
    )


def trading_day(now: datetime) -> date | None:
    """Today, if NSE trades today and has closed; else None."""
    from eulerlab.ingest.coverage import expected_nse, nse_closures

    day = expected_nse(now, nse_closures())
    return day if day == now.astimezone(IST).date() else None


def one_pass() -> str:
    """Run the Indian steps once. Returns the feed's summary, or why it did not run."""
    from eulerlab.ingest import daily_feed
    from eulerlab.ingest.filelock import Busy

    try:
        run = daily_feed.refresh(only=INDIA_STEPS)
    except Busy as exc:
        return f"skipped: {exc}"
    lines = [run.summary]
    lines += [f"  {'ok  ' if s.ok else 'FAIL'} {s.name}: {s.detail}" for s in run.steps]
    return "\n".join(lines)


def run(
    *,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    sleep: Callable[[float], None] = time.sleep,
    work: Callable[[], str] = one_pass,
    check: Callable[[date], Landed] = landed,
    interval: float = INTERVAL,
) -> tuple[int, str]:
    """Pass until today's data is in or the deadline passes. Returns (exit code, last line)."""
    started = now()
    day = trading_day(started)
    if day is None:
        return 0, "no NSE session today, or it has not closed yet"
    passes = 0
    while True:
        passes += 1
        stamp = now().astimezone(IST).strftime("%H:%M")
        print(f"== pass {passes} at {stamp} IST ==", flush=True)
        print(work(), flush=True)
        state = check(day)
        if state.done:
            return 0, f"India data for {day} is in ({passes} pass(es), last at {stamp} IST)"
        ist = now().astimezone(IST)
        if (ist.hour, ist.minute) >= DEADLINE:
            return 1, f"India data for {day}: still missing at {stamp} IST — {state.missing()}"
        print(f"still missing: {state.missing()}; next pass in {interval / 60:.0f} min", flush=True)
        sleep(interval)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="india-live", description=__doc__.splitlines()[0])
    parser.add_argument("--once", action="store_true", help="one pass, no waiting")
    args = parser.parse_args(argv)
    if args.once:
        print(one_pass())
        return 0
    code, line = run()
    print(line)
    try:
        from eulerlab import notify

        if notify.configured():
            notify.send(line)
    except Exception as exc:  # a failed message must not fail the data run
        print(f"(telegram not sent: {type(exc).__name__}: {exc})")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
