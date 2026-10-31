# Value at risk (VaR), 95% and 99%

*Family: Risk on the live book. Id: `value-at-risk`.*

**In one line:** A one-day loss today's holdings would have exceeded on only 5% (or 1%) of the last 250 days.

**Where you see it:** Live & Risk; `/api/risk/book`; Risk watch level `book_var_pct`.

**How we compute it:** Today's holdings run through the last 250 days: pnl(t) = Σ v_i r_i(t). VaR 95% = the k-th worst pnl, k = ceil(0.05 × days) (`risk/book.quantile_loss`, `var_table`).

**Data and freshness:** Price panel; deployment holdings. No VaR with fewer than 60 days of prices.

**What is normal (our data, as of 2026-10-30):** Risk watch warns at 2% of equity for the book (`config/risk_watch.yaml`, proposed, not measured).

**How to read it:**

- A typical bad day, not the worst day. One day in twenty should be worse.

**What it does not tell you:** How much worse the bad days get (see expected shortfall).

**Traps:**

- Built from the last year: a calm year gives a small VaR before a storm.
- Names with no price on a day count as flat; the payload says how much of the book that covers.

**Related:**

- [expected-shortfall](../risk/expected-shortfall.md)
- [ewma-var](../risk/ewma-var.md)
- [component-var](../risk/component-var.md)

**Sources:**

- `docs/ARCHITECTURE.md`, Risk on the deployed book (ADR-071)

## Example answers

**Q:** VaR 95% is ₹4,200 on ₹1 lakh. Meaning?

**A:** On about one day in twenty over the past year, today's holdings would have lost more than ₹4,200 (4.2%). That is above the 2% watch level.
