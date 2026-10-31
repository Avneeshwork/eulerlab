# Combinatorial purged cross-validation (CPCV)

*Family: Validation and the gate. Id: `cpcv`.*

**In one line:** Fifteen train/test splits over time with leaks removed, instead of one.

**Where you see it:** Validation battery; walk.

**How we compute it:** 6 contiguous blocks, every pair as test (15 paths), purge the label horizon, embargo 5 days (`validation/cpcv.py`; `docs/ARCHITECTURE.md` §5.1).

**Data and freshness:** Daily panel.

**What is normal (our data, as of 2026-10-30):** n/a

**How to read it:**

- Many paths show the spread of out-of-sample results, not one lucky split.

**What it does not tell you:** Live performance.

**Traps:**

- Leakage checks must use the days actually present, not the calendar (a mistake the project made).

**Related:**

- [pbo](../validation/pbo.md)

**Sources:**

- `docs/ARCHITECTURE.md` §5.1.

## Example answers

**Q:** Why 15 splits?

**A:** Six time blocks taken two at a time give 15 test sets, so the result is a spread over many held-out periods instead of one.
