"""`make health` — is the machinery alive? One page, one exit code.

A job that runs unattended and writes only to a log is logged, not monitored
(`tools/daily_guard.sh`). This reads what the scheduler, the live book's
clock and the kill switch each leave behind and says, per part, whether it is
where it should be:

- **scheduler**: its heartbeat is younger than three ticks;
- **each job**: its latest slot that has come due either ran (exit 0), is
  running, or is still within its grace; a non-zero exit or an overdue slot
  is red;
- **live book**: when armed for today in market hours, the clock ticked in
  the last two minutes (the dead-man switch's own rule, `oms/deadman.py`);
- **kill switch**: tripped is red, with the reason.

`summary()` is what `GET /api/health` returns under `ops`; `main()` prints it
and exits 1 when anything is red, so a cron line or a container health check
can use it as is.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from eulerlab import scheduler
from eulerlab.jobs import JOBS
from eulerlab.oms import deadman
from eulerlab.oms.killswitch import KillSwitch
from eulerlab.paths import data_path

SCHEDULER_STALE = timedelta(seconds=scheduler.TICK * 3)


def _read(path: Path) -> dict[str, Any]:
    try:
        return dict(json.loads(path.read_text()))
    except (OSError, ValueError):
        return {}


def _age(stamp: str, now: datetime) -> int | None:
    try:
        at = datetime.fromisoformat(stamp)
    except ValueError:
        return None
    if at.tzinfo is None:
        at = at.replace(tzinfo=scheduler.IST)
    return int((now - at).total_seconds())


def _jobs(now: datetime, state: dict[str, Any], running: set[str]) -> list[dict[str, Any]]:
    rows = []
    for name in sorted(JOBS):
        job = JOBS[name]
        mine = state.get(name, {})
        past = [
            s for d in (now - timedelta(days=1), now) for s in scheduler.slots(job, d) if s <= now
        ]
        latest = max(past) if past else None
        last_slot = mine.get("slot", "")
        code = mine.get("code")
        if name in running:
            status, why = "running", f"since {mine.get('started', '')[11:16]}"
        elif not mine:
            # The scheduler does not run slots from before its first start
            # (scheduler.due), so a job with no record is not late yet.
            status, why = "ok", "no run recorded yet"
        elif latest is None:
            status, why = "ok", "no slot yet today"
        elif last_slot >= latest.isoformat(timespec="minutes"):
            status = "ok" if code == 0 else ("bad" if code is not None else "ok")
            why = f"slot {latest:%H:%M} exit {code}" if code is not None else f"slot {latest:%H:%M}"
        elif now - latest <= scheduler.grace(job):
            status, why = "ok", f"slot {latest:%H:%M} within grace"
        else:
            status, why = "bad", f"slot {latest:%H:%M} never ran"
        rows.append({"job": name, "status": status, "why": why, "last": mine})
    return rows


def summary(now: datetime | None = None) -> dict[str, Any]:
    now = now or scheduler.now_ist()
    beat = _read(scheduler.state_dir() / "heartbeat.json")
    beat_age = _age(str(beat.get("at", "")), now) if beat.get("at") else None
    running = set(beat.get("running", []))
    sched_ok = beat_age is not None and beat_age <= SCHEDULER_STALE.total_seconds()
    state = _read(scheduler.state_dir() / "state.json")
    jobs = _jobs(now, state, running) if sched_ok else []
    trip_path = data_path("oms/KILL_SWITCH")
    log_path = data_path("oms/killswitch_log.jsonl")
    book = deadman.check(now, switch=_NoTrip(trip_path, log_path), send=lambda _text: None)
    switch = KillSwitch(trip_path, log_path)
    parts: dict[str, Any] = {
        "scheduler": {
            "status": "ok" if sched_ok else "bad",
            "why": f"heartbeat {beat_age}s ago" if beat_age is not None else "no heartbeat",
            "running": sorted(running),
        },
        "jobs": jobs,
        "live_book": {
            "status": "bad" if (book.armed and book.in_hours and book.stale) else "ok",
            "why": book.why,
            "armed": book.armed,
            "heartbeat_age_s": book.heartbeat_age_s,
        },
        "kill_switch": {
            "status": "bad" if switch.is_tripped() else "ok",
            "why": switch.reason() or "clear",
        },
    }
    red = [k for k in ("scheduler", "live_book", "kill_switch") if parts[k]["status"] == "bad"]
    red += [f"job {j['job']}" for j in jobs if j["status"] == "bad"]
    return {"ok": not red, "red": red, "at": now.isoformat(timespec="seconds"), **parts}


class _NoTrip(KillSwitch):
    """A read of the dead-man rule must not trip anything; the watcher does that."""

    def trip(self, reason: str, *, by: str = "system") -> None:
        del reason, by


def render(body: dict[str, Any]) -> str:
    lines = [f"health {'OK' if body['ok'] else 'RED'} at {body['at']}"]
    for key in ("scheduler", "live_book", "kill_switch"):
        part = body[key]
        lines.append(f"  {key:<12} {part['status']:<4} {part['why']}")
    for row in body["jobs"]:
        lines.append(f"  job {row['job']:<20} {row['status']:<8} {row['why']}")
    if body["red"]:
        lines.append("red: " + ", ".join(body["red"]))
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    body = summary()
    print(json.dumps(body, indent=2, default=str) if args.json else render(body))
    return 0 if body["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
