# Expected shortfall

*Family: Risk on the live book. Id: `expected-shortfall`.*

**In one line:** The average loss on the days beyond VaR.

**Where you see it:** Live & Risk.

**How we compute it:** Mean of the k worst pnl(t) (`risk/book.quantile_loss`).

**Data and freshness:** As VaR.

**What is normal (our data, as of 2026-10-30):** Always at least as large as VaR.

**How to read it:**

- The size of a bad day once you are in the tail.

**What it does not tell you:** The worst possible day.

**Traps:**

- Few tail days in a year: noisy.

**Related:**

- [value-at-risk](../risk/value-at-risk.md)

**Sources:**

- `docs/ARCHITECTURE.md`, Risk on the deployed book (ADR-071)

## Example answers

**Q:** ES ₹6,000 vs VaR ₹4,200?

**A:** On the worst one-in-twenty days, the average loss was ₹6,000.
