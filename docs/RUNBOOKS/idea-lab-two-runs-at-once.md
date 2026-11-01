# Two idea lab runs at once

**Symptom.** Two `data/agents/lab/<run>/` folders started minutes apart, both
testing the same card (first seen 2026-11-01: 05:00 and 05:06 UTC, both on
`ts_mean(sign(ret(1)), 63)`). Each test is logged as trials, so the same idea
was paid for twice.

**Diagnosis.** `make agents-ideas` and a second `make agents-ideas` or
`make agent NAME=lab` overlapped. A run takes up to 90 minutes and nothing
stopped a second one.

**Fix.** The lab holds `data/agents/lab.running` while it tests. A second run
reports "another idea lab run is testing" and stops before reading the panel.
The lock is removed when the run ends, even on an error; one older than 4
hours is from a dead run and is taken over.

**Prevention.** Let the 17:00 job run it. If you start one by hand, check the
Idea lab card is not already running. The duplicate trials stay in the log:
it is append-only, and they make the bar slightly stricter, never looser.
