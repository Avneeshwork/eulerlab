# Block and bulk deals; insider (SAST) disclosures; pledges

*Family: Market events and calendar. Id: `block-and-bulk-deals`.*

**In one line:** Large trades by named parties, and promoters' buying, selling or pledging.

**Where you see it:** Deals & filings tab.

**How we compute it:** NSE publishes bulk deals (a client trading over 0.5% of a company's shares in a day) and block deals (large trades in a separate window). SAST and insider filings report promoter and insider changes; pledge data shows shares pledged by promoters.

**Data and freshness:** NSE evening reports (`make nse-reports`).

**Do we hold it:** Yes (ADR-095, ADR-096).

**What is normal (our data, as of 2026-10-30):** n/a

**How to read it:**

- A promoter buying in the open market is a stronger signal than a fund rotating a position.
- Rising pledges can force selling if the price falls.

**What it does not tell you:** Why a party traded.

**Traps:**

- The 0.5% bulk-deal threshold is from general knowledge here; check NSE's definition (A-085).

**Related:**

- [supply-ipos-ofs-qip](../events/supply-ipos-ofs-qip.md)
- [delivery-percent](../market/delivery-percent.md)

**Sources:**

- ADR-095, ADR-096; research 130.

## Example answers

**Q:** A fund sold 2% of a midcap in a block deal.

**A:** A large holder exited in one trade; it removes an overhang if the buyer is a long-term holder, or signals concern if the seller was a long-term holder.
