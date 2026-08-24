#!/bin/zsh
# Run the nightly job and tell the operator if it fails.
#
# This wrapper exists because `make daily` under launchd reported to nobody: it
# exited 2 every evening for six days and the first signal was a human noticing
# a stale date on a screen. A job that runs unattended and writes only to a log
# file is logged, not monitored.
#
# Deliberately thin. Scheduling stays in launchd, the work stays in the
# Makefile, and the only thing added here is that a non-zero exit becomes a
# message rather than a line in a file nobody opens.

set -u
ROOT="/Users/avneesh/EulerLab"
LOG="$ROOT/data/logs/daily.log"
ERR="$ROOT/data/logs/daily.err"

cd "$ROOT" || {
  # Cannot cd, so cannot use the repo's own notifier. This is exactly the TCC
  # failure that went unnoticed for six days, so it gets its own line.
  echo "daily_guard: cannot cd to $ROOT" >&2
  exit 2
}

mkdir -p "$ROOT/data/logs"
make daily
code=$?

if [ $code -ne 0 ]; then
  # Prefer the stderr log: a failing step writes there, and it is the part
  # worth putting in front of the reader.
  tail_source="$ERR"
  [ -s "$ERR" ] || tail_source="$LOG"
  uv run python -c "
from pathlib import Path
from eulerlab import notify
d = notify.job_failed('make daily', code=$code, log=Path('$tail_source'))
print('notified' if d.sent else f'notify failed: {d.reason}')
" 2>&1
fi

exit $code
