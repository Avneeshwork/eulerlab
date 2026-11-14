#!/bin/zsh
# Angel minute backfill that restarts itself (operator, 2026-11-13: "set auto
# start if limit over"; "push all data to B2, don't keep local").
#
# Run by launchd (`make angel-backfill-supervise ACTION=install`) with KeepAlive
# on a non-zero exit and a five-minute throttle, so a rate limit, a timed-out
# login or a killed process is retried until the history is complete. Every
# step resumes from its manifest, so a restart never re-downloads.
#
# Exit 0 only when a whole pass of the history fetched nothing new and failed
# nothing, and every minute tree is in B2 with its local copies deleted.
set -u
cd "${0:A:h}/.."
export LC_ALL=en_US.UTF-8
TREES=(kite_minute kite_index_minute angel_minute_history angel_minute)
log() { print -r -- "$(date -u +%FT%TZ) $*"; }

upload() {
  uv run python -m eulerlab.ingest.verified_prune "${TREES[@]}" 2>&1 | grep -v '^\[' | tail -8
}

# Upload and delete every 30 minutes while the fetch runs.
( while sleep 1800; do log "periodic upload"; upload; done ) &
uploader=$!
trap 'kill $uploader 2>/dev/null' EXIT

# One fetcher at a time: a hand-started run finishes first.
while pgrep -f "eulerlab.ingest.angel_minute --history" >/dev/null; do
  log "another Angel history run is active; waiting"
  sleep 120
done


log "fetch: Angel history from 2018-11-01"
raw=data/logs/angel_history_pass.log
uv run --extra angel python -m eulerlab.ingest.angel_minute --history --from 2018-11-01 >"$raw" 2>&1
fetch_status=$?
out=$(grep -v '^\[' "$raw")
print -r -- "$out" | tail -5
kill $uploader 2>/dev/null

log "final upload"
upload

done_line=$(print -r -- "$out" | grep "done:" | tail -1)
if [[ $fetch_status -eq 0 && "$done_line" == *"'landed': 0,"* && "$done_line" == *"'failed': 0,"* ]]; then
  log "history complete and in B2; stopping"
  exit 0
fi
log "not finished yet (or a request failed); launchd will start the next pass"
exit 1
