"""Keep the price panel and the paper books level with the data, by themselves.

The operator's rule (2026-10-09): "price panel and paper trading should auto
update on data change". Before this, both moved only when something asked —
`make daily`, Update all data, or a row button that named them. Data landed any
other way (a terminal `make ingest-nse-daily`, a run that died after its
fetch, the Cash bhavcopy row on its own) left them a day behind until the next
full run, which is how 8 Oct sat on disk while the books showed 7 Oct (T-4030).

Two routes, both through `catch_up()`:

- **Inside a feed run.** `daily_feed.DEPENDENTS` pulls the price panel and the
  paper books into any run that fetches NSE files, and their steps call
  `catch_up` pieces that return at once when nothing changed.
- **Outside one.** The API server runs `watch()` in a background thread: every
  `INTERVAL` seconds it compares the NSE manifest's latest cash day with the
  panel's last day, and the panel's last day with each active paper book. Set
  `EULERLAB_AUTOUPDATE=0` to switch it off.

It never runs while the `feed` lock is held — that run will do the same work
and the two would only queue behind each other's locks.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from pathlib import Path

from eulerlab.paths import data_path

INTERVAL = 300.0
"""Seconds between checks. A check that finds nothing reads two small files."""

NSE_MANIFEST = data_path("landing/nse/manifest.jsonl")


@dataclass
class CatchUp:
    panel_days: int = 0
    panel_through: str = ""
    paper_ran: list[str] = field(default_factory=list)
    skipped: str = ""

    def render(self) -> str:
        if self.skipped:
            return self.skipped
        parts = [
            f"panel +{self.panel_days} day(s), through {self.panel_through}"
            if self.panel_days
            else f"panel already through {self.panel_through or '—'}"
        ]
        parts.append(
            f"{len(self.paper_ran)} paper book(s) brought forward"
            if self.paper_ran
            else "paper books already current"
        )
        return "; ".join(parts)


def landed_cash_day(manifest: Path = NSE_MANIFEST) -> str:
    """The latest cash bhavcopy day in the NSE manifest."""
    from eulerlab.ingest.coverage import _max_by

    return _max_by(manifest, "segment", "trade_date").get("cm", "")


def panel_day() -> str:
    from eulerlab.features.panel import PANEL_PATH
    from eulerlab.ingest.coverage import last_day_jsonl

    return last_day_jsonl(PANEL_PATH)


def update_panel() -> tuple[int, str]:
    """Build the panel only when the manifest holds a cash day it lacks.

    The fast path matters: a full `build` reads the 745 MB panel to learn which
    days it holds (about 12 s). The panel is appended in day order, so its last
    line answers "is anything newer landed?" in a millisecond.
    """
    from eulerlab.features.panel import build

    landed, have = landed_cash_day(), panel_day()
    if not landed or (have and have >= landed):
        return 0, have
    written, note = build(start="2015-01-01", end=landed)
    if note:
        raise RuntimeError(note)
    return written, panel_day()


def books_behind(through: str) -> list[str]:
    """Active paper deployments whose last traded day is before `through`.

    A deployment still waiting for its first two sessions has no traded day
    and is counted as behind only when the panel has moved since its last run,
    so a waiting book is not replayed every five minutes.
    """
    from eulerlab.deploy import deployments as store

    out: list[str] = []
    for deployment in store.all_deployments():
        if deployment.status != "active" or deployment.mode != "paper":
            continue
        state = store.read_state(deployment) or {}
        traded = str(state.get("traded_through") or "")
        if traded:
            if traded < through:
                out.append(deployment.id)
        elif str(state.get("as_of") or state.get("panel_through") or "") < through:
            out.append(deployment.id)
    return out


def update_paper(through: str) -> list[str]:
    """Run the paper books that are behind the panel; return their ids."""
    from eulerlab.deploy import runner

    behind = books_behind(through) if through else []
    if behind:
        runner.run_all(behind)
    return behind


def catch_up() -> CatchUp:
    """Panel, then paper books — each only if something is newer."""
    from eulerlab.ingest.filelock import holder

    if holder("feed"):
        return CatchUp(skipped="a data run holds the feed lock; it will do this")
    days, through = update_panel()
    return CatchUp(panel_days=days, panel_through=through, paper_ran=update_paper(through))


def enabled() -> bool:
    return os.environ.get("EULERLAB_AUTOUPDATE", "1") != "0"


def watch(stop: threading.Event, interval: float = INTERVAL) -> None:
    """Check, sleep, repeat until `stop` is set. Errors are printed, not fatal.

    A failed check must not end the thread: the next one may succeed (B2 back,
    the file unlocked), and a watcher that dies quietly is the failure this
    module exists to remove.
    """
    import traceback

    while not stop.is_set():
        try:
            result = catch_up()
            if result.panel_days or result.paper_ran:
                print(f"[autoupdate] {result.render()}", flush=True)
        except Exception:
            print(f"[autoupdate] check failed:\n{traceback.format_exc(limit=3)}", flush=True)
        stop.wait(interval)
