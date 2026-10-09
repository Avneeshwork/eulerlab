# Runbook — paper books are a day behind even though the data landed

**Symptom.** Live & Risk → Paper trading shows yesterday's equity and the
warning "the price panel ends YYYY-MM-DD, 1 trading day(s) behind". Run now
does not help. The day's bhavcopy is in `data/landing/nse/cm/`.

**Diagnosis.** The paper runner reads `data/derived/price_panel.jsonl`, not
landing. Check its last day: `tail -1 data/derived/price_panel.jsonl`. If that
is behind the landed bhavcopy, the panel was not rebuilt. First seen
2026-10-08: `make daily` built the panel and ran `paper-daily` only as its
last steps. The 03:50 run died when the B2 sync failed (network down; it was
the only step that could stop the run). The 19:30 run was still working
through fundamentals an hour later.

**Fix.**
```bash
make build-panel && make paper-daily
```
Both are idempotent. The workbench picks up the new panel by itself (T-4025).

**Prevention (T-4030).** `make daily` now builds the panel and runs
`paper-daily` straight after the NSE files. `sync-cloud` failing no longer
stops the run (`prune-local` still deletes only what B2 confirms). The panel
reads a day still in local landing from disk and uses B2 only for pruned days.

**Since 2026-10-09 (T-4035)** the API checks every 5 minutes and catches the
panel and the books up by itself, and any button that fetches NSE files runs
them too. If they are still behind: is the API running? Is
`EULERLAB_AUTOUPDATE=0` set? Is a data run holding the feed lock (the
Instruments page says so)? The API's console prints `[autoupdate]` lines.
