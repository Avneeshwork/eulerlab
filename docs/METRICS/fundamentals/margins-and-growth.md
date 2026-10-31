# Margins and growth

*Family: Company fundamentals. Id: `margins-and-growth`.*

**In one line:** Profit as a share of sales, and how fast sales and profit grow.

**Where you see it:** Company page.

**How we compute it:** Net and operating margin = profit / sales, latest year. Growth = this period / earlier − 1, blank when the earlier is zero or a loss; quarters against the same quarter a year before (`docs/ARCHITECTURE.md`, Company pages (ADR-065)).

**Data and freshness:** Statements.

**What is normal (our data, as of 2026-10-30):** n/a

**How to read it:**

- Margins rising with sales: operating leverage.

**What it does not tell you:** Cash generation.

**Traps:**

- Growth from a tiny base looks huge.

**Related:**

- [returns-on-capital](../fundamentals/returns-on-capital.md)

**Sources:**

- `docs/ARCHITECTURE.md`, Company pages (ADR-065)

## Example answers

**Q:** Profit up 80% this quarter?

**A:** Check last year's quarter: if it was depressed, 80% may only be a recovery.
