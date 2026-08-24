"""`make schedule` — install (or remove) the daily ingest as a launchd job.

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
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

LABEL = "com.eulerlab.daily"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
LOG_DIR = Path("data/logs")


def plist(repo: Path, *, hour: int, minute: int) -> str:
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
  <key>Label</key><string>{LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/zsh</string>
    <string>-lc</string>
    <string>{repo}/tools/daily_guard.sh</string>
  </array>
  <key>WorkingDirectory</key><string>{repo}</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>{home}/.local/bin:/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key><integer>{hour}</integer>
    <key>Minute</key><integer>{minute}</integer>
  </dict>
  <key>RunAtLoad</key><false/>
  <key>Nice</key><integer>5</integer>
  <key>StandardOutPath</key><string>{log}/daily.log</string>
  <key>StandardErrorPath</key><string>{log}/daily.err</string>
</dict>
</plist>
"""


def install(repo: Path, *, hour: int, minute: int) -> int:
    (repo / LOG_DIR).mkdir(parents=True, exist_ok=True)
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    PLIST_PATH.write_text(plist(repo, hour=hour, minute=minute), encoding="utf-8")

    print(f"wrote {PLIST_PATH}")
    print(f"  runs: make daily, every day at {hour:02d}:{minute:02d} local time")
    print(f"  logs: {repo / LOG_DIR}/daily.log")
    print()
    print("It is NOT loaded yet. To start it:")
    print(f"  launchctl load -w {PLIST_PATH}")
    print()
    print("To check it is registered, and to stop it:")
    print(f"  launchctl list | grep {LABEL}")
    print(f"  launchctl unload -w {PLIST_PATH}")
    print()
    print(
        "19:30 IST is the default because NSE bhavcopy and the AMFI NAV file are\n"
        "both published in the evening. Running earlier fetches yesterday."
    )
    return 0


def uninstall() -> int:
    if not PLIST_PATH.exists():
        print(f"{PLIST_PATH} does not exist; nothing to remove")
        return 0
    subprocess.run(
        ["/bin/launchctl", "unload", "-w", str(PLIST_PATH)],
        check=False,
        capture_output=True,
    )
    PLIST_PATH.unlink()
    print(f"removed {PLIST_PATH} and unloaded {LABEL}")
    return 0


def status() -> int:
    print(f"plist: {'present' if PLIST_PATH.exists() else 'not installed'} at {PLIST_PATH}")
    result = subprocess.run(["/bin/launchctl", "list"], check=False, capture_output=True, text=True)
    rows = [line for line in result.stdout.splitlines() if LABEL in line]
    if rows:
        print(f"loaded: yes — {rows[0].strip()}")
        print("  columns are PID, last exit status, label. Exit status 0 is a clean run.")
    else:
        print("loaded: no")
    log = Path(LOG_DIR) / "daily.log"
    if log.exists():
        size = log.stat().st_size
        print(f"log:    {log} ({size:,} bytes)")
    else:
        print(f"log:    {log} (nothing yet)")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Schedule the daily ingest.")
    parser.add_argument(
        "action", choices=["install", "uninstall", "status"], nargs="?", default="status"
    )
    parser.add_argument("--hour", type=int, default=19)
    parser.add_argument("--minute", type=int, default=30)
    args = parser.parse_args(argv)

    if sys.platform != "darwin" and args.action == "install":
        print("launchd is macOS only. On Linux use a systemd timer running `make daily`.")
        return 2

    repo = Path(__file__).resolve().parents[1]
    if args.action == "install":
        return install(repo, hour=args.hour, minute=args.minute)
    if args.action == "uninstall":
        return uninstall()
    return status()


if __name__ == "__main__":
    raise SystemExit(main())
