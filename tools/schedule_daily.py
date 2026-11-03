"""`make schedule` — install (or remove) the daily ingest, or the gap signal, as a launchd job.

`make daily` has existed for a while and nothing has ever run it. "Data updated
regularly and mirrored to cloud" was a command somebody had to remember to
type, which is not a property of a system — it is a property of a person's
memory, and it fails silently the first busy week.

**launchd, not cron.** On macOS cron is deprecated and, more importantly, a
cron job simply does not fire if the laptop was asleep at the appointed minute.
launchd's `StartCalendarInterval` catches up: if the machine was asleep at
19:30 it runs the job on wake. For a daily data pull that is the difference
between a gap and no gap, and gaps in market history cannot be bought back
later.

**It writes a plist and tells you the command.** Loading it is left to the
operator: installing a background job that runs on their machine daily and
makes network requests is their decision to take deliberately, not a side
effect of running a make target.

**It runs `tools/daily_guard.sh`, not `make daily` directly.** The job failed
at 19:30 every evening for six days and reported to nobody — it wrote stderr to
a log file and the first signal was a human noticing a stale date on screen. A
job that runs unattended and writes only to a file is logged, not monitored, so
the wrapper turns a non-zero exit into a message.

**PATH is set explicitly.** launchd starts with a minimal environment and
`zsh -lc` does not source `.zshrc`, so `uv` was not on PATH and every step died
with "uv: No such file or directory". Relying on shell init files means relying
on a thing that differs between an interactive terminal and an agent.

**Keep the repo out of ~/Documents, ~/Desktop and ~/Downloads.** macOS TCC
denies a launchd agent access to all three, and the failure is obscure: the
shell cannot even `getcwd`, so `make` runs somewhere else and reports "No rule
to make target". That was the original six-day outage.

**Four jobs.** `india-live` runs `make india-live` at 15:31 on weekdays: the
Indian data from one minute after the close, retried until it is in (ADR-079). `fundamentals` runs `make fundamentals-update` on Sunday at
10:00: it left the nightly job on 2026-10-13 because it takes hours. `daily`
runs `make daily` every evening. `gap-signal` runs
`make gap-signal SCHEDULED=1` at 15:20 on weekdays: the Nifty gap strategy's
decision, sent to Telegram ten minutes before the close (T-4047). The catch-up
that suits the daily pull does not suit a message tied to a clock, so that
command itself says nothing when it runs far from 15:20, on a weekend or on an
NSE holiday.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

LOG_DIR = Path("data/logs")
WEEKDAYS = (1, 2, 3, 4, 5)
"""launchd's numbering: 1 is Monday."""
SUNDAY = 7
"""launchd takes 0 or 7 for Sunday; 7 keeps `if weekday` true in `_when`."""


@dataclass(frozen=True)
class Job:
    name: str
    label: str
    command: str
    """Run by `zsh -lc` in the repo. `{repo}` is filled in."""
    hour: int
    minute: int
    weekdays: tuple[int, ...]
    """Empty means every day."""
    log: str
    what: str
    why_then: str
    hours: tuple[int, ...] = ()
    """When set, one run at `minute` past each of these hours, every day."""

    @property
    def plist_path(self) -> Path:
        return Path.home() / "Library" / "LaunchAgents" / f"{self.label}.plist"


JOBS = {
    "daily": Job(
        name="daily",
        label="com.eulerlab.daily",
        command="{repo}/tools/daily_guard.sh",
        hour=19,
        minute=30,
        weekdays=(),
        log="daily",
        what="make daily, every day",
        why_then=(
            "19:30 IST is the default because NSE bhavcopy and the AMFI NAV file are\n"
            "both published in the evening. Running earlier fetches yesterday."
        ),
    ),
    "india-live": Job(
        name="india-live",
        label="com.eulerlab.indialive",
        command="cd {repo} && make india-live",
        hour=15,
        minute=31,
        weekdays=WEEKDAYS,
        log="india_live",
        what="make india-live, Monday to Friday",
        why_then=(
            "15:31 IST is one minute after the NSE close. It retries every 10 minutes until\n"
            "the bhavcopy and the minute bars are in, or 21:00, using minute bars as\n"
            "provisional daily bars meanwhile (ADR-079). It exits at once on an NSE holiday."
        ),
    ),
    "depth": Job(
        name="depth",
        label="com.eulerlab.depth",
        command="cd {repo} && make depth-day",
        hour=9,
        minute=10,
        weekdays=WEEKDAYS,
        log="depth",
        what="make depth-day, Monday to Friday",
        why_then=(
            "09:10 IST is five minutes before the open. It records Kite's five-level depth\n"
            "for the Nifty 50 until 15:31, then uploads the day to B2 and deletes the local\n"
            "copy only after the size and SHA-256 match (ADR-095). It needs a Kite token\n"
            "made that morning; without one it says so and exits."
        ),
    ),
    "gap-signal": Job(
        name="gap-signal",
        label="com.eulerlab.gapsignal",
        command="cd {repo} && make gap-signal SCHEDULED=1",
        hour=15,
        minute=20,
        weekdays=WEEKDAYS,
        log="gap_signal",
        what="make gap-signal SCHEDULED=1, Monday to Friday",
        why_then=(
            "15:20 IST is ten minutes before the close: late enough that the day's candle\n"
            "and VIX are nearly final, early enough to act. It needs a Kite token made that\n"
            "day; without one the message says so."
        ),
    ),
    "fundamentals": Job(
        name="fundamentals",
        label="com.eulerlab.fundamentals",
        command="cd {repo} && make fundamentals-update",
        hour=10,
        minute=0,
        weekdays=(SUNDAY,),
        log="fundamentals",
        what="make fundamentals-update, every Sunday",
        why_then=(
            "Company fundamentals change quarterly and the fetch walks every company for\n"
            "hours, so it left the nightly job on 2026-10-13. Sunday morning keeps it clear\n"
            "of the 19:30 daily run and of market hours. It can also be run by hand."
        ),
    ),
    "agents-preopen": Job(
        name="agents-preopen",
        label="com.eulerlab.agentspreopen",
        command="cd {repo} && make agents-preopen",
        hour=8,
        minute=45,
        weekdays=WEEKDAYS,
        log="agents_preopen",
        what="make agents-preopen, Monday to Friday",
        why_then=(
            "08:45 IST is 15 minutes before the pre-open session: the data and operations\n"
            "agents check last night's run and the market brief goes out before 09:00 (ADR-085).\n"
            "Then the three heads split and check tasks and plan the day, and the\n"
            "work runner starts the tasks that may run by themselves (ADR-124)."
        ),
    ),
    "brief-weekend": Job(
        name="brief-weekend",
        label="com.eulerlab.briefweekend",
        command="cd {repo} && make agent NAME=market_brief",
        hour=9,
        minute=30,
        weekdays=(6, SUNDAY),
        log="brief_weekend",
        what="the market brief agent, Saturday and Sunday",
        why_then=(
            "On a closed day the brief is a markets-closed note: the last session's read,\n"
            "the week in review and the week ahead (ADR-105). One per break: Sunday's run\n"
            "finds Saturday's note and stops. Weekday holidays get theirs from the 08:45 run."
        ),
    ),
    "agents-close": Job(
        name="agents-close",
        label="com.eulerlab.agentsclose",
        command="cd {repo} && make agents-close",
        hour=16,
        minute=15,
        weekdays=WEEKDAYS,
        log="agents_close",
        what="make agents-close, Monday to Friday",
        why_then=(
            "16:15 IST is 45 minutes after the close, once india-live has its first pass:\n"
            "the after-close brief, book drift and step timings for the day."
        ),
    ),
    "agents-weekly": Job(
        name="agents-weekly",
        label="com.eulerlab.agentsweekly",
        command="cd {repo} && make agents-weekly",
        hour=7,
        minute=0,
        weekdays=(SUNDAY,),
        log="agents_weekly",
        what="make agents-weekly, every Sunday",
        why_then=(
            "Sunday 07:00 IST, before the 10:00 fundamentals job: the Quantpedia sync, the\n"
            "knowledge index and the code review. Research and the idea lab moved to the\n"
            "daily agents-ideas job (ADR-111)."
        ),
    ),
    "agents-ideas": Job(
        name="agents-ideas",
        label="com.eulerlab.agentsideas",
        command="cd {repo} && make agents-ideas",
        hour=17,
        minute=0,
        weekdays=(),
        log="agents_ideas",
        what="make agents-ideas, every day",
        why_then=(
            "17:00 IST, after india-live (15:31) and agents-close (16:15) have the day's prices,\n"
            "and with the idea lab's 90-minute limit, done before the 19:30 daily run.\n"
            "Research first, so the lab tests the day's drafts; the lab's feedback steers\n"
            "the next day's research (ADR-111). Weekends too: ideas do not need a session.\n"
            "The heads and the work runner go first, so the day's tasks are done (ADR-124)."
        ),
    ),
    "data-watch": Job(
        name="data-watch",
        label="com.eulerlab.datawatch",
        command="cd {repo} && make agent NAME=data",
        hour=6,
        minute=0,
        weekdays=(),
        hours=(6, 8, 10, 12, 14, 16, 18, 20),
        log="data_watch",
        what="the data agent, every two hours from 06:00 to 20:00 IST",
        why_then=(
            "Every two hours from 06:00 to 20:00 IST, as the operator asked (2026-11-04): grade,\n"
            "re-run what is behind, upload and clear local copies, merge what differs. The 20:00\n"
            "run usually finds make daily holding the feed lock and leaves upkeep to the next."
        ),
    ),
}

LABEL = JOBS["daily"].label
PLIST_PATH = JOBS["daily"].plist_path


def _when(job: Job, hour: int, minute: int) -> str:
    """`StartCalendarInterval`: one entry, or one per weekday."""

    def entry(weekday: int | None, pad: str) -> str:
        day = f"{pad}  <key>Weekday</key><integer>{weekday}</integer>\n" if weekday else ""
        return (
            f"{pad}<dict>\n{day}"
            f"{pad}  <key>Hour</key><integer>{hour}</integer>\n"
            f"{pad}  <key>Minute</key><integer>{minute}</integer>\n"
            f"{pad}</dict>\n"
        )

    if job.hours:
        return (
            "  <array>\n"
            + "".join(
                f"    <dict>\n      <key>Hour</key><integer>{h}</integer>\n"
                f"      <key>Minute</key><integer>{minute}</integer>\n    </dict>\n"
                for h in job.hours
            )
            + "  </array>\n"
        )
    if not job.weekdays:
        return entry(None, "  ")
    return "  <array>\n" + "".join(entry(day, "    ") for day in job.weekdays) + "  </array>\n"


def plist(repo: Path, *, hour: int, minute: int, job: Job = JOBS["daily"]) -> str:
    """The job definition.

    `RunAtLoad` is false on purpose: loading the agent should not immediately
    start a multi-hour backfill. `Nice` keeps it out of the way of interactive
    work, since this runs on the operator's own laptop rather than a server.
    """
    log = repo / LOG_DIR
    home = Path.home()
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{job.label}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/zsh</string>
    <string>-lc</string>
    <string>{escape(job.command.format(repo=repo))}</string>
  </array>
  <key>WorkingDirectory</key><string>{repo}</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>{home}/.local/bin:/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
  <key>StartCalendarInterval</key>
{_when(job, hour, minute)}  <key>RunAtLoad</key><false/>
  <key>Nice</key><integer>5</integer>
  <key>StandardOutPath</key><string>{log}/{job.log}.log</string>
  <key>StandardErrorPath</key><string>{log}/{job.log}.err</string>
</dict>
</plist>
"""


def install(repo: Path, *, hour: int, minute: int, job: Job = JOBS["daily"]) -> int:
    (repo / LOG_DIR).mkdir(parents=True, exist_ok=True)
    path = job.plist_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(plist(repo, hour=hour, minute=minute, job=job), encoding="utf-8")

    print(f"wrote {path}")
    print(f"  runs: {job.what}, at {hour:02d}:{minute:02d} local time")
    print(f"  logs: {repo / LOG_DIR}/{job.log}.log")
    print()
    print("It is NOT loaded yet. To start it:")
    print(f"  launchctl load -w {path}")
    print()
    print("To check it is registered, and to stop it:")
    print(f"  launchctl list | grep {job.label}")
    print(f"  launchctl unload -w {path}")
    print()
    print(job.why_then)
    return 0


def uninstall(job: Job = JOBS["daily"]) -> int:
    path = job.plist_path
    if not path.exists():
        print(f"{path} does not exist; nothing to remove")
        return 0
    subprocess.run(
        ["/bin/launchctl", "unload", "-w", str(path)],
        check=False,
        capture_output=True,
    )
    path.unlink()
    print(f"removed {path} and unloaded {job.label}")
    return 0


def status(job: Job = JOBS["daily"]) -> int:
    path = job.plist_path
    print(f"plist: {'present' if path.exists() else 'not installed'} at {path}")
    result = subprocess.run(["/bin/launchctl", "list"], check=False, capture_output=True, text=True)
    rows = [line for line in result.stdout.splitlines() if job.label in line]
    if rows:
        print(f"loaded: yes — {rows[0].strip()}")
        print("  columns are PID, last exit status, label. Exit status 0 is a clean run.")
    else:
        print("loaded: no")
    log = Path(LOG_DIR) / f"{job.log}.log"
    if log.exists():
        size = log.stat().st_size
        print(f"log:    {log} ({size:,} bytes)")
    else:
        print(f"log:    {log} (nothing yet)")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Schedule the daily ingest, the gap signal or the weekly fundamentals."
    )
    parser.add_argument(
        "action", choices=["install", "uninstall", "status"], nargs="?", default="status"
    )
    parser.add_argument("--job", choices=sorted(JOBS), default="daily")
    parser.add_argument("--hour", type=int, default=None)
    parser.add_argument("--minute", type=int, default=None)
    args = parser.parse_args(argv)
    job = JOBS[args.job]
    hour = job.hour if args.hour is None else args.hour
    minute = job.minute if args.minute is None else args.minute

    if sys.platform != "darwin" and args.action == "install":
        print("launchd is macOS only. On Linux use a systemd timer running the same command.")
        return 2

    repo = Path(__file__).resolve().parents[1]
    if args.action == "install":
        return install(repo, hour=hour, minute=minute, job=job)
    if args.action == "uninstall":
        return uninstall(job)
    return status(job)


if __name__ == "__main__":
    raise SystemExit(main())
