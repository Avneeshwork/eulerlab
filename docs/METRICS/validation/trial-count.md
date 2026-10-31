# Trial count (the ledger)

*Family: Validation and the gate. Id: `trial-count`.*

**In one line:** How many strategy configurations have been evaluated; every statistic below depends on it.

**Where you see it:** Strategies page, gate output; `data/derived/trial_ledger.jsonl`.

**How we compute it:** One hash-chained entry per configuration evaluated (`validation/ledger.py`; `docs/ARCHITECTURE.md` §5.7).

**Data and freshness:** Append-only ledger; the battery refuses to report if the chain is broken.

**What is normal (our data, as of 2026-10-30):** It only goes up. Never reset.

**How to read it:**

- Every extra trial raises the noise bar for everyone, including evaluations run 'just to check' (T-2609).

**What it does not tell you:** How good any one strategy is.

**Traps:**

- Re-testing the same idea under a new id still counts and is visible.

**Related:**

- [noise-bar](../validation/noise-bar.md)
- [deflated-sharpe](../validation/deflated-sharpe.md)

**Sources:**

- `docs/ARCHITECTURE.md` §5.7; research 015.

## Example answers

**Q:** Why did the noise bar go up when nothing was promoted?

**A:** Every evaluated configuration is a trial, promoted or not. More trials mean pure noise is expected to produce a higher best Sharpe, so the bar rises.
