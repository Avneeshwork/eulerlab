"""The only work an agent may start: re-running named, idempotent feed steps.

The data agent can bring a stale dataset back by re-running the feed steps its
Data coverage row lists (`ingest/coverage.STEPS_FOR`) — the same steps the
dataset's own Update button runs, under the same `feed` lock, so it cannot
overlap `make daily` or a click. Every one of those steps skips what is
already landed and only appends the days it lacks (CLAUDE.md: all ETL is
idempotent), which is what makes an unattended re-run safe.

Nothing else is reachable from here: no shell, no make target by name, no
upload-and-delete, no prune. A step not in `ALLOWED` is refused.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

ALLOWED = frozenset(
    {
        "NSE end-of-day",
        "NSE index closes and delivery",
        "participant OI",
        "market history",
        "price panel",
        "Nifty options",
        "mutual fund NAVs",
        "crypto gap",
        "FX",
        "US bars and actions",
        "US panel",
        "paper books",
        "India minute bars",
        "FII/DII cash flows",
    }
)
"""Steps an agent may re-run. "India minute bars" is here because without a Kite
token it fetches from Angel One, which logs in headless (2026-11-09). "FII/DII
cash flows" too: NSE serves only the latest day, so a day not taken that evening
is lost. The other
Kite steps are left out: they need a login made by the operator that day, and a
re-run without one only fails again."""


@dataclass(frozen=True)
class Rerun:
    steps: tuple[str, ...]
    ok: bool
    detail: str


def allowed_steps(names: Sequence[str]) -> tuple[str, ...]:
    from eulerlab.ingest import daily_feed

    known = {name for name, _ in daily_feed.STEPS}
    return tuple(n for n in names if n in ALLOWED and n in known)


def rerun(names: Sequence[str]) -> Rerun:
    """Run the allowed steps once, without the B2 sync (the nightly job does that)."""
    from eulerlab.ingest import daily_feed, filelock

    steps = allowed_steps(names)
    if not steps:
        return Rerun((), False, "no step here is one an agent may re-run")
    try:
        result = daily_feed.refresh(only=steps, sync=False)
    except filelock.Busy as exc:
        return Rerun(steps, False, f"the feed is already running: {exc}")
    failed = [s for s in result.steps if not s.ok]
    if failed:
        return Rerun(steps, False, "; ".join(f"{s.name}: {s.detail}" for s in failed)[:400])
    return Rerun(steps, True, "; ".join(f"{s.name}: {s.detail}" for s in result.steps)[:400])
