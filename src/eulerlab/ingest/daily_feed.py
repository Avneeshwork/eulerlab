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
import re
import sys
import threading
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from dataclasses import dataclass, field
from typing import Any


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
    from eulerlab.ingest import alpaca

    symbols = alpaca.sp500_symbols()
    if on_detail:
        on_detail(f"{len(symbols)} symbols — bars")
    bars, _rows, err = alpaca.land_bars(symbols, start=_days_ago(7))
    if err:
        raise RuntimeError(err[:160])
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


def _market_history() -> str:
    from eulerlab import market_history

    text = _captured(lambda: market_history.main(["--skip-expiries"]))
    added = re.findall(r"^(.+?) days: ([\d,]+) added", text, flags=re.MULTILINE)
    return ", ".join(f"{name} +{n}" for name, n in added) or "index, delivery, futures"


def _price_panel() -> str:
    from eulerlab.features.panel import PANEL_PATH, build
    from eulerlab.ingest.coverage import last_day_jsonl

    written, note = build(start="2015-01-01", end=_days_ago(0))
    if note:
        raise RuntimeError(note)
    return f"{written} day(s) added, ends {last_day_jsonl(PANEL_PATH)}"


def _nifty_options() -> str:
    from eulerlab.options import nifty_history

    text = _captured(lambda: nifty_history.main(["--from", _days_ago(30)]))
    done = re.search(r"done: (\d+) days added", text)
    return f"{done.group(1)} day(s) added" if done else "nothing new"


def _paper_books() -> str:
    from eulerlab.deploy import runner

    text = _captured(lambda: runner.run_all())
    through = re.findall(r"through (\d{4}-\d{2}-\d{2})", text)
    if "no active paper deployments" in text:
        return "no active deployments"
    return f"{len(through)} deployment(s), through {max(through)}" if through else "ran"


def _us_panel() -> str:
    from eulerlab.features import us_panel

    rows, symbols = us_panel.build()
    return f"{rows:,} rows, {symbols} symbols (last two months re-read)"


STEPS: tuple[tuple[str, Callable[..., str]], ...] = (
    ("NSE end-of-day", _nse_eod),
    ("participant OI", _participant_oi),
    ("NSE index closes and delivery", _nse_daily_files),
    ("market history", _market_history),
    ("price panel", _price_panel),
    ("Nifty options", _nifty_options),
    ("paper books", _paper_books),
    ("mutual fund NAVs", _mutual_funds),
    ("economic calendar", _calendar),
    ("crypto gap", _crypto_gap),
    ("FX", _fx),
    ("news", _news),
    ("index levels", _indices),
    ("option chain", _option_chain),
    ("US bars and actions", _us),
    ("US panel", _us_panel),
)
"""The sources a daily refresh touches, in the order `make daily` runs them.

Fetch first, then everything derived from what was fetched, India before the
rest so the paper books are current within minutes of the click.

**Minute bars are absent, deliberately.** They need a Kite token minted the same
day, which a browser button cannot obtain — offering the step and failing every
afternoon would teach the operator to ignore a red row. `make daily-minute`
after a login is the honest route, and the runbook says so."""

STEP_MODULES: dict[str, str] = {
    "NSE end-of-day": "eulerlab.ingest.nse_eod",
    "participant OI": "eulerlab.ingest.backfill_oi",
    "NSE index closes and delivery": "eulerlab.ingest.nse_daily_files",
    "market history": "eulerlab.market_history",
    "price panel": "build-panel",
    "Nifty options": "nifty-options",
    "paper books": "paper-daily",
    "mutual fund NAVs": "eulerlab.ingest.mf_backfill",
    "economic calendar": "eulerlab.ingest.forexfactory",
    "crypto gap": "eulerlab.ingest.crypto_fill",
    "FX": "eulerlab.ingest.fx_bulk_backfill",
    "news": "eulerlab.ingest.news",
    "index levels": "eulerlab.indices",
    "option chain": "eulerlab.ingest.nse_chain",
    "US bars and actions": "eulerlab.ingest.alpaca",
    "US panel": "build-us-panel",
}
"""What each step runs, as `make daily` names it (a module or a make target).
`tests/test_feed_parity.py` fails when `make daily` runs something that is
neither here nor in `TERMINAL_ONLY` — the button and the overnight job drifted
apart once already, silently, for four sources."""

TERMINAL_ONLY: dict[str, str] = {
    "eulerlab.fundamentals.backfill": "walks every symbol for hours; overnight only",
    "daily-minute": "needs a Kite token minted today, which a button cannot obtain",
    "eulerlab.ingest.crypto_backfill": "a one-year backfill; the button fills the recent gap",
    "sync-cloud": "the button mirrors at the end of every run",
    "prune-local": "deleting files is not a side effect of a refresh button",
    "manifest": "the button recounts after its mirror",
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
    steps = [s for s in STEPS if not only or s[0] in only]

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
