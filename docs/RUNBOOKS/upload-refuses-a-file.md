# The nightly upload refuses a file ("local … is smaller than the bucket's")

**Symptom.** `data/logs/daily.log` lists `FAILED n:` lines such as `us/actions/2016-01.jsonl.gz: local 2293 bytes is smaller than the bucket's 2295; not uploaded`, and the same files are listed every night.

**Diagnosis.** A local file differs from its B2 copy. The upload never replaces B2 with a smaller file and the prune never deletes a file B2 does not hold at the same size, so it stays. Usually it is a re-fetch of rows B2 already holds with later knowledge times; sometimes it holds rows B2 lacks (HISTORY #70).

**Fix.** `make data-merge-back DRY=1` says what a merge would do, file by file and tree by tree; `make data-merge-back` merges each file into B2 (rows once, earliest knowledge time), uploads it, confirms the size, and deletes the local copy. The data agent does this every two hours. A file it reports as "not JSON lines" needs a person: compare the two copies before deleting either.

**Prevention.** `make data-merge-back` runs at the end of `make daily` and fails the run when a file cannot be merged, so the failure reaches Telegram. The watchdog and the data agent list what is left.
