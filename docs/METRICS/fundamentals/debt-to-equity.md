# Debt to equity

*Family: Company fundamentals. Id: `debt-to-equity`.*

**In one line:** Borrowings against shareholders' funds.

**Where you see it:** Company page.

**How we compute it:** Borrowings / (equity capital + reserves) (`docs/ARCHITECTURE.md`, Company pages (ADR-065)).

**Data and freshness:** Balance sheet.

**What is normal (our data, as of 2026-10-30):** Banks and NBFCs run high by design.

**How to read it:**

- Above 1 for a non-financial company: lenders fund more than owners.

**What it does not tell you:** Ability to repay (see cash flow).

**Traps:**

- Leases and contingent liabilities may be missing.

**Related:**

- [returns-on-capital](../fundamentals/returns-on-capital.md)

**Sources:**

- `docs/ARCHITECTURE.md`, Company pages (ADR-065)

## Example answers

**Q:** D/E 2.1 for a manufacturer?

**A:** Heavily borrowed; rising rates or a weak year hurt it more.
