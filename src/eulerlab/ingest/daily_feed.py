"""The daily data feed, as steps something other than a Makefile can run.

`make daily` fetches from every source, mirrors to B2 and prunes. That is the
right sequence and it is only reachable from a terminal — so the interface had a
button that uploaded whatever happened to be on disk and no way to *fetch*
anything. An operator watching a stale dashboard could mirror the staleness to
the cloud and nothing more.

### Every step is allowed to fail

`make daily` prefixes each line with `-` so one dead source does not abandon the
rest, and that judgement is right: NSE being down should not cost the day's
crypto, and a Kite token that expired overnight should not stop US bars from
landing. The same rule here — each step is caught, recorded, and the run
continues.

What differs is the reporting. A Makefile swallows the failure silently; this
returns which steps failed and why, because "the feed updated" and "the feed
updated except for the two sources you care about" are different sentences and
only one of them is true.

### What this deliberately does not do

**It does not prune.** `make daily` deletes local files once their upload is
verified, which is correct for a disk-constrained machine running unattended
and surprising as the side effect of a button someone clicked to refresh data.
Pruning stays a deliberate command.

### It does rebuild what the data feeds (T-4032)

It used to stop at fetching, so data fetched from the button never reached the
price panel or the paper books — on 2026-10-08 the bhavcopy had landed and the
books still showed 7 Oct. Every derived table now updates in the same run, and
each one only appends the days it lacks: the panel reads today's file from
local landing in seconds, the US panel re-reads only the last two months.

### Nothing is fetched twice, and two runs never overlap

Every source skips what is already landed, and each step says how many files it
downloaded against how many it already held. The mirror uploads only what the
bucket lacks (one LIST, size compare). The whole run holds the `feed` lock that
`make daily` also takes, so the button and the overnight job cannot both
append the same day.
"""

from __future__ import annotations

import datetime as dt
import io
import json
import re
import sys
import threading
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from eulerlab import timings


@dataclass
class StepResult:
    """What one source did."""

    name: str
    ok: bool
    detail: str = ""
    seconds: float = 0.0


@dataclass
class FeedRun:
    """The whole refresh."""

    steps: list[StepResult] = field(default_factory=list)
    synced: int = 0
    sync_error: str = ""

    @property
    def failed(self) -> list[StepResult]:
        return [s for s in self.steps if not s.ok]

    @property
    def summary(self) -> str:
        """A sentence that does not overstate what happened."""
        done = len(self.steps) - len(self.failed)
        if not self.steps:
            return "nothing ran"
        if self.failed:
            names = ", ".join(s.name for s in self.failed)
            return f"{done} of {len(self.steps)} sources updated — {names} failed"
        return f"all {done} sources updated"


def _days_ago(days: int) -> str:
    """A date `days` back, in the market's day rather than the server's.

    `date.today()` means whatever timezone the machine happens to be in, and a
    feed window that silently shifts by one is the kind of bug that only shows
    up as a missing day months later.
    """
    from zoneinfo import ZoneInfo

    today = dt.datetime.now(ZoneInfo("Asia/Kolkata")).date()
    return (today - dt.timedelta(days=days)).isoformat()


def _nse_eod() -> str:
    from eulerlab.ingest import nse_eod

    text = _captured(lambda: nse_eod.main(["--from", _days_ago(7)]))
    return fetch_counts(text) or "last 7 days"


def _mutual_funds() -> str:
    from eulerlab.ingest import mf_backfill

    mf_backfill.main(["--snapshot-only"])
    return "today's NAV snapshot"


def _calendar() -> str:
    from eulerlab.ingest import forexfactory

    forexfactory.main()
    return "economic calendar"


def _holidays() -> str:
    from eulerlab.ingest import holidays

    holidays.main()
    return "NSE trading holidays"


def _board_meetings() -> str:
    from eulerlab.ingest import board_meetings

    return board_meetings.capture()


def _crypto_gap() -> str:
    from eulerlab.ingest import crypto_fill

    # `_main`, not `main`. These entry points are private by convention and the
    # names differ per module — mypy named every one I assumed wrong.
    crypto_fill._main([])
    return "month-end gap filled from the daily archive"


def _fx() -> str:
    from eulerlab.ingest import fx_bulk_backfill

    year = dt.datetime.now(dt.UTC).year
    fx_bulk_backfill.main(["--from-year", str(year)])
    return f"FXCM weekly candles, {year} to date"


def _news() -> str:
    from eulerlab.ingest import news

    news._main()
    return "per-instrument headlines"


def _market_news() -> str:
    """Market-wide and geopolitical news with its tone, for the brief (ADR-134)."""
    from eulerlab.ingest import market_news

    market_news.main()
    return "market-wide headlines and tone"


class PartialSource(RuntimeError):
    """Some sub-sources of a step landed and some did not."""


def _option_chain() -> str:
    """Snapshot the live NSE option chain.

    The only source here that cannot be caught up later. The bhavcopy is
    published after the close and can be fetched for any past day; a chain
    snapshot carries a bid and an ask, which exist only while the market is
    open and are gone the moment it shuts. Every session this does not run is
    a session of spreads nobody can recover.
    """
    from eulerlab.ingest import nse_chain

    written, problems = nse_chain.snapshot_all()
    if not written:
        joined = "; ".join(problems[:3]) or "no snapshots"
        msg = f"no chain landed — {joined}"
        raise RuntimeError(msg)
    detail = f"{len(written)} chain snapshots"
    return f"{detail} ({len(problems)} expiries unavailable)" if problems else detail


def _indices() -> str:
    """Index levels, and a failure when any sub-source did not land.

    This called `indices._main()`, which prints its errors and returns None,
    so the feed recorded the step as OK no matter what happened inside it. On
    2026-09-09 that reported "index levels 30.4s OK" for a run whose own
    output said `! india: TokenException` and `! world: HTTP 402`. India index
    levels were stale and the summary said everything was fine.

    `land()` returns those errors; only `_main` was throwing them away. A step
    that cannot fail cannot be trusted when it passes.
    """
    from eulerlab import indices

    payload = indices.land()
    counts = {k: len(v) for k, v in payload.items() if isinstance(v, list)}
    landed = ", ".join(f"{name} {count}" for name, count in sorted(counts.items()) if count)

    errors = payload.get("errors")
    if isinstance(errors, dict) and errors:
        named = "; ".join(f"{name}: {str(why)[:60]}" for name, why in sorted(errors.items()))
        # Raised rather than returned, because the feed marks a step OK on any
        # return value. Partial is not OK — it is the state most worth seeing.
        msg = f"{len(errors)} of {len(counts) + len(errors)} sources failed — {named}"
        raise PartialSource(msg)
    return f"index levels, movers, sectors ({landed})" if landed else "index levels"


def _us(on_detail: Callable[[str], None] | None = None) -> str:
    """Recent US bars, actions and news for the S&P 500.

    **Seven days, not thirty.** A daily refresh needs the days since the last
    one; thirty was a number I picked without measuring and it made this step
    take over fourteen minutes for five hundred symbols — most of it re-fetching
    bars already landed. `make daily` reaches back to 2016 because it is a
    backfill; this is not.

    Sub-progress is reported because a step that runs for minutes with no
    output is indistinguishable from one that has hung, and the operator's only
    recourse is to reload and start again.
    """
    from eulerlab.ingest import alpaca, landing_reader

    # Include SPY as the actual tradable S&P 500 proxy used by backtest
    # comparisons. Seed its two-year panel window once; daily refreshes then
    # fetch only the recent bars. Keep it out of constituent-only actions/news.
    symbols = alpaca.sp500_symbols()
    if on_detail:
        on_detail(f"{len(symbols)} symbols — bars")
    bars, _rows, err = alpaca.land_bars(symbols, start=_days_ago(7))
    if err:
        raise RuntimeError(err[:160])
    has_spy = bool(landing_reader.available("us", "bars/SPY/*.jsonl.gz"))
    spy_start = _days_ago(7) if has_spy else _days_ago(730)
    spy_bars, _spy_rows, spy_err = alpaca.land_bars(["SPY"], start=spy_start)
    if spy_err:
        raise RuntimeError(spy_err[:160])
    bars += spy_bars
    if on_detail:
        on_detail(f"{len(symbols)} symbols — corporate actions")
    alpaca.land_actions(symbols, start=_days_ago(7))
    if on_detail:
        on_detail(f"{len(symbols)} symbols — news")
    alpaca.land_news(symbols, start=_days_ago(3))
    return f"{bars} symbols of bars, plus actions and news"


class _ThreadStdout(io.TextIOBase):
    """`sys.stdout` that a thread can divert into its own buffer.

    `contextlib.redirect_stdout` swaps the global and restores whatever it saw
    on entry. A step abandoned at its deadline keeps running in its own thread,
    so the next step's redirect would save *that* step's buffer as "the
    original" and restore it on exit — leaving the process printing into a dead
    buffer. Diverting per thread has no such ordering to get wrong.
    """

    def __init__(self, base: Any) -> None:
        self.base = base
        self.local = threading.local()

    def write(self, text: str) -> int:
        buf = getattr(self.local, "buf", None)
        (buf if buf is not None else self.base).write(text)
        return len(text)

    def flush(self) -> None:
        self.base.flush()


def _captured(call: Callable[[], int | None]) -> str:
    """Run a CLI entry point in this thread, keeping what it prints.

    A non-zero exit becomes an exception carrying its last lines, so a source
    that reports failure through its exit code fails the step.
    """
    if not isinstance(sys.stdout, _ThreadStdout):
        sys.stdout = _ThreadStdout(sys.stdout)
    proxy = sys.stdout
    assert isinstance(proxy, _ThreadStdout)
    buf = io.StringIO()
    proxy.local.buf = buf
    try:
        code = call()
    finally:
        proxy.local.buf = None
    text = buf.getvalue()
    if code not in (None, 0):
        tail = " | ".join(line.strip() for line in text.splitlines()[-3:] if line.strip())
        msg = f"exit {code}: {tail}"[:200]
        raise RuntimeError(msg)
    return text


_COUNT = re.compile(r"\b(downloaded|skipped)\b[\s':=]{1,20}(\d+)")


def fetch_counts(text: str) -> str:
    """ "downloaded 2, already held 10" from a source's own report.

    Both report shapes the NSE sources print — `downloaded   1` and
    `{'downloaded': 5, ...}` — summed across the segments a step covers.
    """
    totals = {"downloaded": 0, "skipped": 0}
    seen = False
    for word, number in _COUNT.findall(text):
        totals[word] += int(number)
        seen = True
    if not seen:
        return ""
    return f"downloaded {totals['downloaded']}, already held {totals['skipped']}"


def _participant_oi() -> str:
    from eulerlab.ingest import backfill_oi

    text = _captured(lambda: backfill_oi.main(["--from", _days_ago(7)]))
    return fetch_counts(text) or "last 7 days"


def _nse_daily_files() -> str:
    from eulerlab.ingest import nse_daily_files

    text = _captured(lambda: nse_daily_files.main(["--from", _days_ago(7)]))
    return fetch_counts(text) or "last 7 days"


def _fii_dii() -> str:
    """NSE serves the latest day only, so this is one request a run (ADR-098)."""
    from eulerlab.ingest import fii_dii_cash

    text = _captured(lambda: fii_dii_cash.main([]))
    return fetch_counts(text) or "latest day"


def _nse_reports() -> str:
    """Deals, ban list, SLBM, MTF, insider and SAST filings, and snapshots (ADR-095)."""
    from eulerlab import market_reports
    from eulerlab.ingest import nse_reports

    text = _captured(lambda: nse_reports.main(["--from", _days_ago(7)]))
    _captured(lambda: market_reports.main([]))  # the Deals & filings tab (ADR-096)
    return fetch_counts(text) or "last 7 days"


def _index_minute() -> str:
    """NIFTY 50, NIFTY BANK and INDIA VIX minute bars (`make index-minute`)."""
    from eulerlab.broker import kite_session
    from eulerlab.ingest import kite_index_minute

    if not kite_session.is_fresh(kite_session.load()):
        return "skipped: no Kite token minted today. Log in to Kite on this page first"
    text = _captured(lambda: kite_index_minute.main(["--years", "1"]))
    last = next((ln.strip() for ln in reversed(text.splitlines()) if ln.strip()), "")
    return last[:160] or "index minute bars up to date"


def _market_history() -> str:
    from eulerlab import market_history

    text = _captured(lambda: market_history.main(["--skip-expiries"]))
    added = re.findall(r"^(.+?) days: ([\d,]+) added", text, flags=re.MULTILINE)
    return ", ".join(f"{name} +{n}" for name, n in added) or "index, delivery, futures"


def _price_panel() -> str:
    from eulerlab.deploy.autoupdate import update_panel

    # Returns at once when the panel already holds the latest landed cash day.
    written, through = update_panel()
    return f"{written} day(s) added, ends {through}" if written else f"already through {through}"


def _nifty_options() -> str:
    from eulerlab.options import nifty_history

    text = _captured(lambda: nifty_history.main(["--from", _days_ago(30)]))
    done = re.search(r"done: (\d+) days added", text)
    return f"{done.group(1)} day(s) added" if done else "nothing new"


def _paper_books() -> str:
    from eulerlab.deploy.autoupdate import panel_day, update_paper

    # Only the books behind the panel are replayed; none is a no-op.
    through = panel_day()
    ran = update_paper(through)
    return f"{len(ran)} book(s) brought to {through}" if ran else f"already through {through}"


def _us_panel() -> str:
    from eulerlab.features import us_panel

    rows, symbols = us_panel.build()
    return f"{rows:,} rows, {symbols} symbols (last two months re-read)"


def _india_minute() -> str:
    """Kite minute bars for the sessions not yet held (`make daily-minute`).

    Needs a Kite token minted today. Without one the step says so and passes:
    a red row every afternoon would teach the operator to ignore red rows.
    The Instruments page now has the login (`api/kite_routes.py`), which is
    what makes this a step at all.
    """
    from eulerlab.broker import kite_session
    from eulerlab.ingest import backfill_minute

    if not kite_session.is_fresh(kite_session.load()):
        return angel_minute_fill()
    text = _captured(lambda: backfill_minute.main(["--years", "1"]))
    last = next((ln.strip() for ln in reversed(text.splitlines()) if ln.strip()), "")
    return last[:160] or "minute bars up to date"


ANGEL_SESSIONS = 2
"""Sessions the Angel fallback fetches a run at most: about 450 symbols at one
request a second is eight minutes a session, inside `STEP_DEADLINE`."""


def angel_window(kite_end: str, angel_end: str, now: dt.datetime) -> tuple[str, str] | None:
    """(from, to) for the Angel fallback, or None when nothing is owed.

    From the day after the later of the two sources' last session, to the last
    *complete* session: today only from 15:45 IST, because a day landed while
    the market is open would be held as complete and never fetched again.
    """
    from zoneinfo import ZoneInfo

    ist = now.astimezone(ZoneInfo("Asia/Kolkata"))
    to = ist.date() if (ist.hour, ist.minute) >= (15, 45) else ist.date() - dt.timedelta(days=1)
    held = max(kite_end, angel_end)
    start = dt.date.fromisoformat(held) + dt.timedelta(days=1) if held else to
    start = max(start, to - dt.timedelta(days=14))
    return None if start > to else (start.isoformat(), to.isoformat())


def angel_minute_fill() -> str:
    """Minute bars from Angel One SmartAPI when there is no Kite token today.

    Kite needs a browser login each day; Angel logs in headless with TOTP
    (`ingest/angel_minute.py`, ADR-157), so the data agent and `make daily`
    can fill the sessions Kite missed without the operator. The bars land in
    `data/landing/angel_minute`, their own tree, so the source stays visible.
    """
    from eulerlab.ingest import angel_minute
    from eulerlab.ingest.nse_eod import session_days

    def last_end(manifest: Path) -> str:
        if not manifest.exists():
            return ""
        ends = (
            str(json.loads(line).get("end", ""))
            for line in manifest.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
        return max(ends, default="")

    window = angel_window(
        last_end(Path("data/landing/kite_minute/manifest.jsonl")),
        last_end(angel_minute.LANDING_ROOT / "manifest.jsonl"),
        dt.datetime.now(dt.UTC),
    )
    days = (
        session_days(dt.date.fromisoformat(window[0]), dt.date.fromisoformat(window[1]))
        if window
        else []
    )
    if not days:
        return "no Kite token today; Angel minute bars already up to date"
    days = days[-ANGEL_SESSIONS:]
    span = ["--from", days[0].isoformat(), "--to", days[-1].isoformat()]
    text = _captured(lambda: angel_minute.main(span))
    last = next((ln.strip() for ln in reversed(text.splitlines()) if "done:" in ln), "")
    return f"no Kite token today, so from Angel One: {days[0]}..{days[-1]} {last}"[:200]


def _mcx_index_minute(progress: Callable[[str], None] | None = None) -> str:
    """Five-year Kite history for MCX iCOMDEX indices with available candles."""
    from eulerlab.broker import kite_session
    from eulerlab.ingest import kite_mcx_indices

    if not kite_session.is_fresh(kite_session.load()):
        return "skipped: no Kite token minted today. Log in to Kite on this page first"
    text = _captured(lambda: kite_mcx_indices.main(["--years", "5"], on_progress=progress))
    last = next((ln.strip() for ln in reversed(text.splitlines()) if ln.strip()), "")
    return last[:160] or "MCX iCOMDEX minute history up to date"


def _provisional_daily() -> str:
    """Daily bars from minute bars while the bhavcopy is missing (ADR-079)."""
    from eulerlab.ingest import provisional_daily

    return provisional_daily.record(provisional_daily.latest_session()).render()


STEPS: tuple[tuple[str, Callable[..., str]], ...] = (
    ("NSE end-of-day", _nse_eod),
    ("participant OI", _participant_oi),
    ("NSE reports", _nse_reports),
    ("NSE index closes and delivery", _nse_daily_files),
    ("FII/DII cash flows", _fii_dii),
    ("market history", _market_history),
    ("price panel", _price_panel),
    ("Nifty options", _nifty_options),
    ("paper books", _paper_books),
    ("mutual fund NAVs", _mutual_funds),
    ("economic calendar", _calendar),
    ("NSE holidays", _holidays),
    ("board meetings", _board_meetings),
    ("crypto gap", _crypto_gap),
    ("FX", _fx),
    ("market news", _market_news),
    ("news", _news),
    ("index levels", _indices),
    ("option chain", _option_chain),
    ("US bars and actions", _us),
    ("US panel", _us_panel),
    ("India minute bars", _india_minute),
    ("provisional daily bars", _provisional_daily),
    ("index minute bars", _index_minute),
    ("MCX index minute bars", _mcx_index_minute),
)
"""The sources a daily refresh touches, in the order `make daily` runs them.

Fetch first, then everything derived from what was fetched, India before the
rest so the paper books are current within minutes of the click.

**Minute bars are last, and skip themselves without a token.** They need a Kite
token minted the same day. Until 2026-10-12 a browser could not obtain one, so
the step was left out. The Instruments page now logs in to Kite, so the step
is here; with no fresh token it reports "skipped" and passes."""

STEP_MODULES: dict[str, str] = {
    "NSE end-of-day": "eulerlab.ingest.nse_eod",
    "participant OI": "eulerlab.ingest.backfill_oi",
    "NSE reports": "nse-reports",
    "NSE index closes and delivery": "eulerlab.ingest.nse_daily_files",
    "FII/DII cash flows": "eulerlab.ingest.fii_dii_cash",
    "market history": "eulerlab.market_history",
    "price panel": "build-panel",
    "Nifty options": "nifty-options",
    "paper books": "paper-daily",
    "mutual fund NAVs": "eulerlab.ingest.mf_backfill",
    "economic calendar": "eulerlab.ingest.forexfactory",
    "NSE holidays": "eulerlab.ingest.holidays",
    "board meetings": "eulerlab.ingest.board_meetings",
    "crypto gap": "eulerlab.ingest.crypto_fill",
    "FX": "eulerlab.ingest.fx_bulk_backfill",
    "market news": "eulerlab.ingest.market_news",
    "news": "eulerlab.ingest.news",
    "index levels": "eulerlab.indices",
    "option chain": "eulerlab.ingest.nse_chain",
    "US bars and actions": "eulerlab.ingest.alpaca",
    "US panel": "build-us-panel",
    "India minute bars": "daily-minute",
    "provisional daily bars": "eulerlab.ingest.provisional_daily",
    "index minute bars": "index-minute",
    "MCX index minute bars": "mcx-index-minute",
}
"""What each step runs, as `make daily` names it (a module or a make target).
`tests/test_feed_parity.py` fails when `make daily` runs something that is
neither here nor in `TERMINAL_ONLY` — the button and the overnight job drifted
apart once already, silently, for four sources."""

DEPENDENTS: dict[str, tuple[str, ...]] = {
    "NSE end-of-day": ("price panel", "Nifty options", "provisional daily bars"),
    "India minute bars": ("provisional daily bars",),
    "price panel": ("paper books",),
    "NSE index closes and delivery": ("market history",),
    "US bars and actions": ("US panel",),
}
"""What must be rebuilt when a step may have landed new data.

The operator's rule: the price panel and paper trading update on data change,
whichever button changed it. So the Cash bhavcopy row's button (NSE end-of-day
alone) also runs the panel and the paper books. Each dependent returns at once
when there is nothing newer, so pulling it in costs a second, not a rebuild."""


def with_dependents(only: Sequence[str]) -> set[str]:
    """`only` plus everything downstream of it; empty means every step."""
    wanted = set(only)
    frontier = list(wanted)
    while frontier:
        for child in DEPENDENTS.get(frontier.pop(), ()):
            if child not in wanted:
                wanted.add(child)
                frontier.append(child)
    return wanted


TERMINAL_ONLY: dict[str, str] = {
    "eulerlab.fundamentals.backfill": "walks every symbol for hours; weekly and on demand, not in make daily",
    "eulerlab.ingest.crypto_backfill": "a one-year backfill; the button fills the recent gap",
    "sync-cloud": "the button mirrors at the end of every run",
    "upload-tree": "uploads and removes one folder after its download; the button mirrors once at the end",
    "prune-local": "deleting files is not a side effect of a refresh button",
    "manifest": "the button recounts after its mirror",
    "data-merge-back": "merging into the bucket and deleting local copies is the nightly job's and the data agent's, not a refresh button's (ADR-132)",
    "screener": "loads the whole price panel to build today's lists; nightly, after the panel (ADR-136)",
    "fundamentals-annual": "rebuilt after each weekly fundamentals fetch, not by a refresh button",
    "eulerlab.agents.runtime": "the after-close note is an agent's run, not a data refresh; the AI tab runs agents",
}
"""What `make daily` runs that the button deliberately does not, and why."""


def _wants_detail(work: Callable[..., str]) -> bool:
    """Whether a step accepts a progress callback."""
    import inspect

    return bool(inspect.signature(work).parameters)


STEP_DEADLINE = 1800.0
"""Seconds any one source may take before the feed gives up on it.

Every individual request in this pipeline is already bounded — `crypto._fetch`
allows 120s and three attempts, which is correct. What was unbounded is the
*sum*. The crypto step builds one job per symbol per day: twenty symbols
across a month is 560 jobs, each worth up to 363 seconds of perfectly
well-behaved timeouts, six at a time. On 2026-09-08, with the network path
failing, that arithmetic came to 9.4 hours and the run sat there for 9h11m.

So the fix is not a shorter socket timeout. A bounded request repeated enough
times is still unbounded work, and the thing that needed a limit was the step.
"""


def _run_step(work: Callable[..., str], arg: Callable[[str], None] | None) -> str:
    """Run one step, or raise `TimeoutError` when it overruns.

    The overrunning thread is **not** killed — Python cannot — so it keeps
    running until the process exits. That is worth stating plainly rather than
    implying a clean cancellation: what this buys is that the remaining
    sources still get their turn and the operator gets a report, instead of
    one stalled source holding the whole feed overnight. The threads are
    daemons, so they do not keep the process alive at the end.
    """
    # Deliberately not a `with` block. The context manager exits through
    # `shutdown(wait=True)`, which blocks until the worker finishes — so an
    # abandoned step was still held for its full runtime while reporting that
    # it had been abandoned. A test caught it: the step reported "exceeded" and
    # took thirty seconds anyway.
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="feed-step")
    future = pool.submit(work, arg) if arg is not None else pool.submit(work)
    try:
        detail = future.result(timeout=STEP_DEADLINE)
    except FuturesTimeout:
        pool.shutdown(wait=False, cancel_futures=True)
        msg = f"exceeded {STEP_DEADLINE:.0f}s and was abandoned"
        raise TimeoutError(msg) from None
    pool.shutdown(wait=False)
    return detail


def refresh(
    *,
    only: Sequence[str] = (),
    on_step: Callable[[int, int, str], None] | None = None,
    sync: bool = True,
) -> FeedRun:
    """Fetch from each source, then mirror to B2.

    Failures are recorded and the run continues — one dead source should not
    cost the others. The sync happens last so it carries whatever did land.
    """
    from eulerlab.ingest.filelock import exclusive

    # The whole run under the `feed` lock that `make daily` also takes; the
    # second to start raises `filelock.Busy` instead of appending the same day.
    with exclusive("feed", wait=False, what="Instruments → Update all data"):
        return _refresh(only=only, on_step=on_step, sync=sync)


def _refresh(
    *,
    only: Sequence[str],
    on_step: Callable[[int, int, str], None] | None,
    sync: bool,
) -> FeedRun:
    import time

    run = FeedRun()
    wanted = with_dependents(only)
    steps = [s for s in STEPS if not wanted or s[0] in wanted]

    for index, (name, work) in enumerate(steps, start=1):
        if on_step:
            on_step(index, len(steps), name)
        started = time.monotonic()
        try:
            # Steps that take minutes accept a callback so the operator sees
            # movement inside them; the rest do not and are called plainly.
            if _wants_detail(work):
                # Bound as defaults rather than closed over: a lambda capturing
                # the loop variables would report whichever step the loop had
                # reached by the time it fired, not the one that called it.
                def note(
                    text: str, *, at: int = index, total: int = len(steps), step: str = name
                ) -> None:
                    if on_step:
                        on_step(at, total, f"{step} · {text}")

                detail = _run_step(work, note)
            else:
                detail = _run_step(work, None)
        except Exception as exc:
            run.steps.append(
                StepResult(
                    name=name,
                    ok=False,
                    detail=f"{type(exc).__name__}: {exc}"[:200],
                    seconds=time.monotonic() - started,
                )
            )
        else:
            run.steps.append(
                StepResult(name=name, ok=True, detail=detail, seconds=time.monotonic() - started)
            )
        # For the data and operations agents (ADR-085): which step failed, and
        # which is getting slower. Writing it cannot fail the step.
        last = run.steps[-1]
        timings.record(f"feed: {name}", last.seconds, ok=last.ok, detail=last.detail)

    if sync:
        total = len(steps)

        def phase(text: str) -> None:
            if on_step:
                on_step(total, total, text)

        phase("uploading to B2")
        run.synced, run.sync_error = _mirror(on_phase=phase)
    return run


def _mirror(*, on_phase: Callable[[str], None] | None = None) -> tuple[int, str]:
    """Upload what landed, and recount. Returns (objects uploaded, error).

    Reported as two phases because the recount runs long enough that a single
    "mirroring" message looks hung — it relists the bucket, not just the diff.
    """
    import io
    from contextlib import redirect_stdout

    try:
        from eulerlab.ingest import manifest
        from eulerlab.ingest.sync_cloud import main as sync_main

        captured = io.StringIO()
        with redirect_stdout(captured):
            sync_main([])
        uploaded = sum(
            int(line.split(":")[1].strip())
            for line in captured.getvalue().splitlines()
            if line.strip().startswith("uploaded")
        )
        # Recounted after the upload, never before: the census describes what
        # the bucket holds, and counting first describes the state just left.
        if on_phase:
            on_phase("recounting the bucket")
        manifest.save(manifest.build())
    except Exception as exc:
        return 0, f"{type(exc).__name__}: {exc}"[:200]
    return uploaded, ""


def main() -> int:
    """`make feed`: the button's run, printed step by step."""
    from eulerlab.ingest.filelock import Busy

    def show(index: int, total: int, name: str) -> None:
        print(f"[{index}/{total}] {name}", flush=True)

    try:
        run = refresh(on_step=show)
    except Busy as exc:
        print(f"not started: {exc}")
        return 75
    print()
    for step in run.steps:
        mark = "ok  " if step.ok else "FAIL"
        print(f"  {mark} {step.name:32s} {step.seconds:6.1f}s  {step.detail}")
    print(f"\n{run.summary} · {run.synced} object(s) uploaded to B2")
    if run.sync_error:
        print(f"mirror failed: {run.sync_error}")
    return 1 if run.failed or run.sync_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
