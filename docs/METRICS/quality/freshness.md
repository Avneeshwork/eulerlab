# Freshness (ok, behind, stale, missing)

*Family: Data quality. Id: `freshness`.*

**In one line:** Whether a dataset's last date is where it should be by now.

**Where you see it:** Data coverage; brief Data line 'Behind'.

**How we compute it:** Last held date against the expected calendar for the source.

**Data and freshness:** Manifests.

**What is normal (our data, as of 2026-10-30):** Behind for a day is common before the evening jobs run.

**How to read it:**

- Behind on an input means every figure built from it is old; say its date.

**What it does not tell you:** Correctness.

**Traps:**

- A source that publishes late (participant OI after 19:00) looks behind in the afternoon.

**Related:**

- [data-grade](../quality/data-grade.md)

**Sources:**

- ADR-086.

## Example answers

**Q:** Nifty options are 'behind'?

**A:** The last option data held is from an earlier day, so PCR, max pain and the straddle range are older than the rest of the brief.
