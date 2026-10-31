# Information coefficient (IC) and its t-statistic

*Family: Validation and the gate. Id: `information-coefficient`.*

**In one line:** Rank correlation between a feature today and returns that followed, averaged over dates.

**Where you see it:** Feature research; `make ic`.

**How we compute it:** IC_t = Spearman(f_i,t, r_i,t→t+h), h = 21 by default; t = mean(IC) / (std(IC) / √T) (`docs/ARCHITECTURE.md` §4.1).

**Data and freshness:** Price panel and features.

**What is normal (our data, as of 2026-10-30):** Genuine equity signals: mean IC about 0.02 to 0.05.

**How to read it:**

- Consistency matters more than size.

**What it does not tell you:** Tradable return after costs.

**Traps:**

- The Sprint 8 IC figures used unadjusted prices and should not be relied on (T-1317).

**Related:**

- [t-statistic](../validation/t-statistic.md)

**Sources:**

- `docs/ARCHITECTURE.md` §4.1.

## Example answers

**Q:** IC 0.03?

**A:** Typical for a real equity signal; it matters whether it is steady across dates (its t-statistic), and whether it survives costs.
