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

**It does not rebuild the panels.** Those are derived products, they take
minutes, and rebuilding them is a separate decision from fetching what they are
derived from.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field


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

    nse_eod.main(["--from", _days_ago(7)])
    return "last 7 days"


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


STEPS: tuple[tuple[str, Callable[..., str]], ...] = (
    ("NSE end-of-day", _nse_eod),
    ("mutual fund NAVs", _mutual_funds),
    ("economic calendar", _calendar),
    ("crypto gap", _crypto_gap),
    ("FX", _fx),
    ("news", _news),
    ("index levels", _indices),
    ("US bars and actions", _us),
)
"""The sources a daily refresh touches, in the order `make daily` runs them.

**Minute bars are absent, deliberately.** They need a Kite token minted the same
day, which a browser button cannot obtain — offering the step and failing every
afternoon would teach the operator to ignore a red row. `make daily-minute`
after a login is the honest route, and the runbook says so."""


def _wants_detail(work: Callable[..., str]) -> bool:
    """Whether a step accepts a progress callback."""
    import inspect

    return bool(inspect.signature(work).parameters)


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

                detail = work(note)
            else:
                detail = work()
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
