# Book beta and market-fall stress

*Family: Risk on the live book. Id: `book-beta-and-stress`.*

**In one line:** How much the book moves per 1% Nifty move, and its loss in a set market fall.

**Where you see it:** Live & Risk.

**How we compute it:** Beta = cov(r, r_m) / var(r_m) against NIFTYBEES; stress = Σ v_i β_i × shock, names with no beta take 1 (`risk/book.beta`, `scenario_pnl`).

**Data and freshness:** Last 250 days.

**What is normal (our data, as of 2026-10-30):** Near 1 for long-only stock books.

**How to read it:**

- Beta 1.2: a 5% Nifty fall costs about 6%.

**What it does not tell you:** Stock-specific losses.

**Traps:**

- Illiquid names that do not trade every day can show a beta that is too low.

**Related:**

- [beta-and-alpha](../performance/beta-and-alpha.md)
- [value-at-risk](../risk/value-at-risk.md)

**Sources:**

- `docs/ARCHITECTURE.md`, Risk on the deployed book (ADR-071)

## Example answers

**Q:** What happens if Nifty falls 5%?

**A:** With book beta 1.1, about a 5.5% loss, before anything stock-specific.
