# MSCI, FTSE and passive funds

*Family: Institutions and money flows. Id: `global-index-providers`.*

**In one line:** Global index weights decide how much passive money must buy or sell Indian stocks.

**Where you see it:** Events (rebalance days).

**How we compute it:** MSCI reviews quarterly; FTSE semi-annually with quarterly changes. Passive funds trade at the close on the effective date.

**Data and freshness:** MSCI and FTSE announcements.

**Do we hold it:** No.

**What is normal (our data, as of 2026-10-30):** n/a

**How to read it:**

- An added stock or a raised weight brings forced buying at the close of the effective day; cuts bring forced selling.
- India's MSCI EM weight fell in 2026 as Taiwan and Korea grew on AI chips (secondary report).

**What it does not tell you:** Active fund behaviour.

**Traps:**

- Moves often happen before the effective day as traders front-run.

**Related:**

- [index-inclusion](../events/index-inclusion.md)
- [fii-fpi](../institutions/fii-fpi.md)

**Sources:**

- Business Standard and other reports on MSCI reviews (search summary, 2026-10-31).

## Example answers

**Q:** Stock X added to MSCI India.

**A:** Passive funds tracking MSCI must buy it at the close on the effective date; much of the price move often happens in the days before.
