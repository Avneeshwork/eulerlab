#!/usr/bin/env bash
# Keep the cloud mirror complete, restarting the sync if it dies.
#
# sync_until_complete already loops until a pass uploads nothing, but the
# process itself can be killed — by a crash, a disk-full, or a session ending.
# This supervises it: if no sync is running and files are still outstanding, it
# starts one. Exits cleanly once local and remote agree.
set -uo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a

outstanding() {
  uv run python - <<'PY' 2>/dev/null || echo "?"
import json, os, boto3
from pathlib import Path
c = boto3.client("s3", endpoint_url="https://s3.us-west-004.backblazeb2.com",
                 aws_access_key_id=os.environ["B2_KEY_ID"],
                 aws_secret_access_key=os.environ["B2_APP_KEY"])
remote = set()
tok = None
while True:
    kw = {"Bucket": "eulerdata", "Prefix": "nse/", "MaxKeys": 1000}
    if tok: kw["ContinuationToken"] = tok
    r = c.list_objects_v2(**kw)
    remote |= {o["Key"] for o in r.get("Contents", [])}
    if not r.get("IsTruncated"): break
    tok = r["NextContinuationToken"]
root = Path(os.environ.get("EULERLAB_DATA_DIR", "data")) / "landing"
missing = 0
for p in root.rglob("*"):
    if not p.is_file() or p.name in ("manifest.jsonl", "unresolved.jsonl"):
        continue
    rel = p.relative_to(root)
    key = f"nse/{rel.as_posix()}" if rel.parts[0] != "nse" else f"nse/{p.relative_to(root / 'nse').as_posix()}"
    if key not in remote:
        missing += 1
print(missing)
PY
}

for _ in $(seq 1 60); do
  if pgrep -f "sync_until_complete|sync_cloud" >/dev/null 2>&1; then
    echo "[$(date +%H:%M:%S)] sync running"
  else
    n=$(outstanding)
    if [ "$n" = "0" ]; then
      echo "[$(date +%H:%M:%S)] COMPLETE — local and B2 agree, nothing outstanding"
      exit 0
    fi
    echo "[$(date +%H:%M:%S)] sync not running, $n files outstanding — restarting"
    nohup ./tools/sync_until_complete.sh >> /tmp/eulerlab_resync.log 2>&1 &
  fi
  sleep 180
done
echo "[$(date +%H:%M:%S)] supervisor giving up after 3 hours"
exit 1
