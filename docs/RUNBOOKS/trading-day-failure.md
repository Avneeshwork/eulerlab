# Runbook: something failed on a trading day

**Symptom.** The pre-open or after-close market brief says a step failed, the
data agent's inbox has an alert, Telegram `agents` shows a run as failed, or
the trade desk shows a ticket as blocked.

**Diagnosis, in this order.**

1. `make data-quality` — is any dataset below its grade, or held in quarantine? A held file says why.
2. `make agent NAME=operations` — which feed step was slow or failed, and against which deadline.
3. `make agent NAME=data` — failed feed steps, launchd jobs that exited non-zero, and suggested reruns.
4. AI → Agent log — does the chain verify? If not, stop: the log was edited.
5. Live & Risk → Trade desk — which check blocks: kill switch, data, version lock, size.

**Fix.**

- A failed feed step: rerun it, `make feed`, or approve the data agent's rerun proposal and run what it names.
- A file held in quarantine after a SHA mismatch: refetch it (the landing is immutable, so it lands as a new file), then `uv run python -m eulerlab.quality.contract --release "<dataset>" <path> "<what you checked>"`.
- A version lock change: read the diff of the strategy's code, then `make relock DEPLOYMENT=<id> NOTE="<why>"`.
- A tripped kill switch: `docs/RUNBOOKS/kill-switch-tripped.md`.

**Prevention.** Load the launchd jobs (`make schedule JOB=agents-preopen`, `agents-close`, `agents-weekly`) so the checks run before the open and after the close, not when someone remembers.
