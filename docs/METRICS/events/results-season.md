# Quarterly results season

*Family: Market events and calendar. Id: `results-season`.*

**In one line:** The weeks when listed companies report quarterly earnings.

**Where you see it:** Company pages; `make nse-earnings-announcements`.

**How we compute it:** SEBI listing rules give companies 45 days after a quarter (60 for the March quarter) to publish results (not fetched; recheck).

**Data and freshness:** NSE corporate announcements.

**Do we hold it:** Results announcements via `make nse-earnings-announcements`; fundamentals from screener.in (not point in time, A-066).

**What is normal (our data, as of 2026-10-30):** n/a

**How to read it:**

- Stocks move on results against expectations and on guidance; the market reacts to large index weights' results (banks, IT, Reliance) at index level.

**What it does not tell you:** Estimates: analyst forecasts are not held (company page says so).

**Traps:**

- Backtests using fundamentals can see results before they were public (A-066).

**Related:**

- [company-pe](../fundamentals/company-pe.md)
- [big-banks](../institutions/big-banks.md)

**Sources:**

- `docs/ARCHITECTURE.md`, Company pages.

## Example answers

**Q:** Does any of my holdings report this week?

**A:** Check the earnings announcements data for held names; a result day can move a single stock far more than the market.
