# Index rebalancing (Nifty) and index inclusion

*Family: Market events and calendar. Id: `index-rebalancing`.*

**In one line:** Stocks entering or leaving an index, which forces index funds to buy or sell them.

**Where you see it:** Events.

**How we compute it:** Nifty 50 is reviewed semi-annually on data to 31 January and 31 July, with changes effective from the last trading day of March and September and about four weeks' notice.

**Data and freshness:** niftyindices.com press releases.

**Do we hold it:** No (index constituents history is not stored here).

**What is normal (our data, as of 2026-10-30):** n/a

**How to read it:**

- Additions see buying into the effective date; deletions see selling.
- The same mechanics apply to MSCI and FTSE reviews.

**What it does not tell you:** Long-term performance after inclusion.

**Traps:**

- Dates and rules change; check NSE before quoting (A-085).
- Survivorship: testing on today's constituents is biased (GLOSSARY).

**Related:**

- [global-index-providers](../institutions/global-index-providers.md)
- [index-inclusion](../events/index-inclusion.md)

**Sources:**

- Bajaj AMC and other summaries of NSE methodology (search summary, 2026-10-31).

## Example answers

**Q:** When is the next Nifty rebalance?

**A:** Changes take effect from the last trading day of March and September, announced about four weeks before. Check niftyindices.com for the actual list.
