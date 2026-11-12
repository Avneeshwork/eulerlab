"""`make scheduler` — run the job table (`eulerlab.jobs`) as one long-lived process.

launchd ran the fourteen jobs on the operator's Mac, and only there. A server
or a container has no launchd, and cron would not catch up after a restart.
This is the smallest thing that does both (ADR-164):

- every `TICK` seconds it works out, in IST, which job slots have come due
  since the last look and runs each in its own thread, so a long `make daily`
  never delays the 22:00 data agent;
- it remembers what it ran in `data/scheduler/state.json`, so a restart does
  not run a slot twice and a slot missed while it was down is run late
  (`catch_up`) or skipped and reported, within `GRACE`;
- a job that exits non-zero is reported to Telegram the way `daily_guard.sh`
  reports `make daily`, and every run is a line in `data/scheduler/runs.jsonl`;
- `data/scheduler/heartbeat.json` says when it last looked, so `make health`
  can tell "the scheduler is down" from "nothing was due".

It never runs two copies of one job at once, which launchd also refuses. It
knows nothing about NSE holidays on purpose: each job already decides what a
holiday means for it (a plan that does not exist, a feed that finds nothing),
and two places deciding would disagree.

Usage
  uv run python -m eulerlab.scheduler            run until stopped
  uv run python -m eulerlab.scheduler --tick     one look, then exit (cron, tests)
  uv run python -m eulerlab.scheduler --once daily   run one job now, wait, exit
  uv run python -m eulerlab.scheduler --list     the table, with each job's next slot
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from eulerlab import notify
from eulerlab.env import find_repo_root
from eulerlab.jobs import JOBS, Job
from eulerlab.paths import data_path

IST = ZoneInfo("Asia/Kolkata")
TICK = 30.0
"""Seconds between looks. A slot is a minute, so half a minute never skips one."""
GRACE = timedelta(hours=3)
"""How late a `catch_up` job may still run. A slot older than this is skipped."""
GRACE_CLOCK_TIED = timedelta(minutes=10)
"""How late a job that must not run late (`catch_up=False`) may still start."""


def state_dir() -> Path:
    return data_path("scheduler")


def log_dir() -> Path:
    return data_path("logs")


def now_ist() -> datetime:
    return datetime.now(IST)


# --- slots ------------------------------------------------------------------------------------


def slots(job: Job, day: datetime) -> list[datetime]:
    """Every minute the job is meant to start on `day`, in IST."""
    base = day.astimezone(IST).replace(hour=0, minute=0, second=0, microsecond=0)
    if job.hours:
        return [base.replace(hour=h, minute=job.minute) for h in job.hours]
    if job.weekdays and base.isoweekday() not in job.weekdays:
        return []
    return [base.replace(hour=job.hour, minute=job.minute)]


def next_slot(job: Job, after: datetime) -> datetime:
    for days in range(8):
        for slot in slots(job, after + timedelta(days=days)):
            if slot > after:
                return slot
    raise ValueError(f"{job.name}: no slot in the next week")  # pragma: no cover


def grace(job: Job) -> timedelta:
    return GRACE if job.catch_up else GRACE_CLOCK_TIED


@dataclass(frozen=True)
class Due:
    job: Job
    slot: datetime
    late: timedelta
    skipped: tuple[datetime, ...]
    """Older slots that were missed and will not be run: they are recorded, not run."""


def due(
    jobs: Iterable[Job], now: datetime, state: dict[str, Any], *, running: Iterable[str] = ()
) -> list[Due]:
    """The latest unrun slot per job at or before `now`, within its grace.

    One slot at most per job per look: when two slots of the data agent are
    both missed, the later one does the same work, so the earlier is skipped.
    """
    out: list[Due] = []
    running = set(running)
    for job in jobs:
        if job.name in running:
            continue
        last = state.get(job.name, {}).get("slot", "")
        last_dt = datetime.fromisoformat(last) if last else None
        candidates = [s for d in (now - timedelta(days=1), now) for s in slots(job, d) if s <= now]
        if last_dt is not None:
            candidates = [s for s in candidates if s > last_dt]
        else:
            # A first start knows nothing about yesterday: it does not report
            # as missed what nobody was meant to run.
            candidates = [s for s in candidates if now - s <= grace(job)]
        if not candidates:
            continue
        latest = max(candidates)
        older = tuple(sorted(s for s in candidates if s != latest))
        if now - latest > grace(job):
            # Too late to run even the latest: record the whole run of misses.
            out.append(Due(job, latest, now - latest, (*older, latest)))
            continue
        out.append(Due(job, latest, now - latest, older))
    return out


# --- running ----------------------------------------------------------------------------------


def _read_state() -> dict[str, Any]:
    path = state_dir() / "state.json"
    if not path.exists():
        return {}
    try:
        return dict(json.loads(path.read_text()))
    except (OSError, ValueError):
        return {}


def _write_state(state: dict[str, Any]) -> None:
    state_dir().mkdir(parents=True, exist_ok=True)
    tmp = state_dir() / "state.json.tmp"
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, state_dir() / "state.json")


def _record(line: dict[str, Any]) -> None:
    state_dir().mkdir(parents=True, exist_ok=True)
    with (state_dir() / "runs.jsonl").open("a") as handle:
        handle.write(json.dumps(line, sort_keys=True) + "\n")


def heartbeat(running: Iterable[str], at: datetime | None = None) -> None:
    state_dir().mkdir(parents=True, exist_ok=True)
    body = {
        "at": (at or now_ist()).isoformat(timespec="seconds"),
        "pid": os.getpid(),
        "running": sorted(running),
    }
    (state_dir() / "heartbeat.json").write_text(json.dumps(body) + "\n")


Runner = Callable[[Job, Path], int]


def run_command(job: Job, repo: Path) -> int:
    """Run the job's command as launchd did: a login shell in the repo, output to its log."""
    log_dir().mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    home = Path.home()
    env["PATH"] = ":".join(
        p
        for p in (
            str(home / ".local" / "bin"),
            "/opt/homebrew/bin",
            "/usr/local/bin",
            env.get("PATH", ""),
            "/usr/bin",
            "/bin",
        )
        if p
    )
    with (
        (log_dir() / f"{job.log}.log").open("a") as out,
        (log_dir() / f"{job.log}.err").open("a") as err,
    ):
        proc = subprocess.run(
            ["/bin/sh", "-lc", job.command.format(repo=repo)],
            cwd=repo,
            env=env,
            stdout=out,
            stderr=err,
            check=False,
        )
    return proc.returncode


class Scheduler:
    def __init__(
        self,
        jobs: dict[str, Job] | None = None,
        *,
        repo: Path | None = None,
        runner: Runner = run_command,
        clock: Callable[[], datetime] = now_ist,
        notifier: Callable[..., Any] = notify.job_failed,
    ) -> None:
        self.jobs = dict(JOBS if jobs is None else jobs)
        self.repo = repo or find_repo_root() or Path.cwd()
        self.runner = runner
        self.clock = clock
        self.notifier = notifier
        self._threads: dict[str, threading.Thread] = {}
        self._lock = threading.Lock()
        self.state = _read_state()

    @property
    def running(self) -> list[str]:
        with self._lock:
            return [n for n, t in self._threads.items() if t.is_alive()]

    def look(self, now: datetime | None = None) -> list[Due]:
        """One look at the clock: start what is due, record what was missed."""
        now = now or self.clock()
        found = due(self.jobs.values(), now, self.state, running=self.running)
        for item in found:
            for missed in item.skipped:
                _record(
                    {
                        "job": item.job.name,
                        "slot": missed.isoformat(timespec="minutes"),
                        "skipped": True,
                        "why": "missed; too late to run" if not item.job.catch_up else "superseded",
                        "at": now.isoformat(timespec="seconds"),
                    }
                )
            with self._lock:
                self.state[item.job.name] = {
                    **self.state.get(item.job.name, {}),
                    "slot": item.slot.isoformat(timespec="minutes"),
                }
                _write_state(self.state)
            if item.slot in item.skipped:
                continue  # too late for every slot: recorded above, nothing runs
            self._start(item, now)
        heartbeat(self.running, now)
        return found

    def _start(self, item: Due, now: datetime) -> None:
        thread = threading.Thread(
            target=self._run, args=(item, now), name=f"job-{item.job.name}", daemon=True
        )
        with self._lock:
            self._threads[item.job.name] = thread
        thread.start()

    def _run(self, item: Due, started: datetime) -> None:
        job = item.job
        code = -1
        try:
            code = self.runner(job, self.repo)
        finally:
            ended = self.clock()
            with self._lock:
                self.state[job.name] = {
                    **self.state.get(job.name, {}),
                    "started": started.isoformat(timespec="seconds"),
                    "ended": ended.isoformat(timespec="seconds"),
                    "code": code,
                }
                _write_state(self.state)
            _record(
                {
                    "job": job.name,
                    "slot": item.slot.isoformat(timespec="minutes"),
                    "late_s": int(item.late.total_seconds()),
                    "started": started.isoformat(timespec="seconds"),
                    "ended": ended.isoformat(timespec="seconds"),
                    "code": code,
                }
            )
            if code != 0:
                err = log_dir() / f"{job.log}.err"
                self.notifier(job.what, code=code, log=err if err.exists() else None)

    def wait(self, timeout: float | None = None) -> None:
        for thread in list(self._threads.values()):
            thread.join(timeout)

    def run_forever(self, tick: float = TICK) -> None:
        while True:
            try:
                self.look()
            except Exception as exc:  # the loop must outlive one bad look
                _record({"scheduler": "error", "error": f"{type(exc).__name__}: {exc}"})
            time.sleep(tick)

    def run_once(self, name: str) -> int:
        job = self.jobs[name]
        now = self.clock()
        item = Due(job, now.replace(second=0, microsecond=0), timedelta(0), ())
        self._start(item, now)
        self.wait()
        return int(self.state.get(name, {}).get("code", -1))


def listing(jobs: dict[str, Job], now: datetime) -> str:
    rows = ["job                   next slot (IST)      catch up  what"]
    for name in sorted(jobs):
        job = jobs[name]
        nxt = next_slot(job, now)
        rows.append(
            f"{name:<21} {nxt.strftime('%a %Y-%m-%d %H:%M')}  {'yes' if job.catch_up else 'no ':<8}  {job.what}"
        )
    return "\n".join(rows)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tick", action="store_true", help="one look, then exit")
    parser.add_argument("--once", metavar="JOB", choices=sorted(JOBS), help="run one job now")
    parser.add_argument("--list", action="store_true", help="the table and each next slot")
    parser.add_argument("--every", type=float, default=TICK, help="seconds between looks")
    args = parser.parse_args(argv)
    if args.list:
        print(listing(JOBS, now_ist()))
        return 0
    sched = Scheduler()
    if args.once:
        code = sched.run_once(args.once)
        print(f"{args.once}: exit {code}")
        return code
    if args.tick:
        found = sched.look()
        for item in found:
            print(
                f"{item.job.name}: slot {item.slot:%H:%M}, {int(item.late.total_seconds())}s late"
            )
        sched.wait()
        return 0
    print(f"scheduler: {len(JOBS)} jobs, looking every {args.every:g}s, repo {sched.repo}")
    sched.run_forever(args.every)
    return 0


if __name__ == "__main__":
    sys.exit(main())
