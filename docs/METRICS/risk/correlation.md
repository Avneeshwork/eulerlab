# Correlation between books

*Family: Risk on the live book. Id: `correlation`.*

**In one line:** How closely two deployments' daily P&L moved together.

**Where you see it:** Live & Risk.

**How we compute it:** Pearson correlation of the simulated pnl series (`risk/book.correlation`).

**Data and freshness:** Last 250 days.

**What is normal (our data, as of 2026-10-30):** n/a

**How to read it:**

- The higher it is, the more the two books are the same bet; adding to both diversifies little.

**What it does not tell you:** Correlation in a crash, which is usually higher.

**Traps:**

- Two books holding many of the same names will correlate by construction.

**Related:**

- [component-var](../risk/component-var.md)

**Sources:**

- `docs/ARCHITECTURE.md`, Risk on the deployed book (ADR-071)

## Example answers

**Q:** Two momentum books correlate 0.85?

**A:** They are close to one position. Adding capital to both does not diversify.
