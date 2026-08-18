#!/usr/bin/env bash
# Keep syncing until every dataset tree is fully mirrored to B2.
#
# A single `make sync-cloud` pass exits when it finishes, so if a backfill is
# still writing files the pass always leaves a tail behind. This loops until a
# pass uploads nothing, which is the only reliable "done" signal.
#
# It also prunes once complete, and waits for any running backfill first --
# the previous scratchpad watchdog only watched the minute/OI jobs and exited
# while fundamentals was still producing, which is how a tail got stranded.
set -uo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a

BACKFILL_PATTERN='backfill_minute|backfill_oi|fundamentals\.backfill'
MAX_PASSES=${MAX_PASSES:-40}

wait_for_producers() {
  while pgrep -f "$BACKFILL_PATTERN" >/dev/null 2>&1; do
    echo "[$(date +%H:%M:%S)] backfill still running, waiting..."
    sleep 120
  done
  echo "[$(date +%H:%M:%S)] no backfill running"
}

wait_for_producers

for pass in $(seq 1 "$MAX_PASSES"); do
  echo "[$(date +%H:%M:%S)] sync pass $pass"
  out=$(uv run python -m eulerlab.ingest.sync_cloud 2>&1)
  echo "$out" | grep -E '^(uploaded|  uploaded)' | sed 's/^/    /'

  # Total uploaded across every tree this pass. Zero means fully mirrored.
  total=$(echo "$out" | grep -oE '^\s*uploaded\s*:\s*[0-9]+' | grep -oE '[0-9]+' | paste -sd+ - | bc)
  total=${total:-0}
  echo "[$(date +%H:%M:%S)] pass $pass uploaded $total"

  if [ "$total" -eq 0 ]; then
    echo "[$(date +%H:%M:%S)] COMPLETE - nothing left to upload"
    uv run python -m eulerlab.ingest.prune_local | sed 's/^/    /'
    exit 0
  fi

  # A producer may have restarted; re-check before the next pass.
  wait_for_producers
done

echo "[$(date +%H:%M:%S)] gave up after $MAX_PASSES passes - still files outstanding"
exit 1
