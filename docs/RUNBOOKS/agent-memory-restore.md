# The agents' memory is lost or damaged

**Symptom.** `data/agents/`, `research/agent_drafts/` or `research/papers/` is missing
or damaged (a new Mac, a failed disk, a bad edit), or the trial ledger is gone.

**Diagnosis.** `make agents-backup DRY=1` says what differs from the bucket. The
bucket holds the last copy sent by the 17:00 job (`make agents-ideas`, ADR-128).

**Fix.**
1. Move the damaged folder aside, so its place is empty: `mv data/agents data/agents.broken`.
2. `make agents-restore`. It writes only into missing or empty folders and says
   which it refused.
3. For an older copy of one file, B2 keeps earlier versions (A-098): read them with
   `S3ObjectStore.versions(key)` and `get_version`.
4. Run `make verify`, then `make agents-backup` once so the bucket and disk agree.

**Prevention.** The backup runs every day at the end of `make agents-ideas`. Never
delete the bucket's `memory/` or `derived/trials.jsonl` keys.
