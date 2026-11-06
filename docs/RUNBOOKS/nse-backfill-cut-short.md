# NSE report backfill stops with IncompleteRead

**Symptom.** `python -m eulerlab.ingest.nse_reports --from ...` exits with a
traceback ending `http.client.IncompleteRead(... bytes read, 1 more expected)`
part way through a report (2026-11-06, the research 164 backfill, after about
730 SAST days).

**Diagnosis.** NSE closed a connection before the body was complete. The
fetcher retried URL errors, timeouts and OS errors but not `http.client`
exceptions, so one cut-short response ended the whole run.

**Fix.** `UrllibTransport.get` now turns any `http.client.HTTPException` into a
`TransportError`, which `Fetcher.get` retries with backoff. To finish a run that
stopped: re-run the same command; days already in the manifest are skipped.

**Prevention.** `tests/test_fetch_incomplete_read.py`.
