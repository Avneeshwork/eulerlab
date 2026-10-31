# Component VaR and VaR without a book

*Family: Risk on the live book. Id: `component-var`.*

**In one line:** Each deployment's share of the book's VaR, and the book's VaR if it were removed.

**Where you see it:** Live & Risk per-deployment rows; what-if dialog.

**How we compute it:** VaR × cov(pnl_d, pnl_book) / var(pnl_book); the parts sum to the VaR (`risk/book.components`). What-if: VaR before and after adding a strategy at a stated capital (A-060).

**Data and freshness:** As VaR.

**What is normal (our data, as of 2026-10-30):** n/a

**How to read it:**

- A book whose share of VaR is far above its share of capital is the risk concentration.

**What it does not tell you:** Its return contribution.

**Traps:**

- A negative component is possible: that book hedges the others.

**Related:**

- [value-at-risk](../risk/value-at-risk.md)
- [correlation](../risk/correlation.md)

**Sources:**

- `docs/ARCHITECTURE.md`, Risk on the deployed book (ADR-071)

## Example answers

**Q:** One book is 20% of capital but 45% of VaR?

**A:** It carries most of the book's risk, either because it is volatile or because it moves with everything else.
