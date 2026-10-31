# F&O positioning: index futures long share by FII, DII, Pro, Client

*Family: Market context. Id: `participant-long-share`.*

**In one line:** What share of each group's index-futures contracts are long, against what is usual for that group.

**Where you see it:** Big money card; brief scorecard row FII futures; brief detail F&O positioning; `positioning.participants[]`.

**How we compute it:** Long share = index futures long / (long + short) contracts, from NSE's end-of-day participant-wise OI file. Change over 1 and 5 files; percentile against the group's earlier files (about a year) (`market_context.positioning`).

**Data and freshness:** NSE participant-wise OI, one file per trading day after the close.

**What is normal (our data, as of 2026-10-30):** Last 60 files: FII median 10.9% long (5th-95th 8.6% to 12.6%); DII 71.7%; Pro 60.5%; Client 82.5%.

**How to read it:**

- Compare a group with its own normal, never with 50%. FIIs have been mostly short index futures for the whole year, so 11% long is ordinary.
- Big money card: under the 25th percentile, more bearish than usual; above the 75th, more bullish (our thresholds).
- Clients (retail and HNIs) are usually long; a falling client share in a falling market can mean capitulation.

**What it does not tell you:** Their whole position: index futures only, in contracts, not rupees. Many FII shorts hedge cash holdings.

**Traps:**

- Client is everyone not FII, DII or Pro (BSE's definition), not only retail.
- A 'percent long' is not a 'percent change': 11% long reads like a change on a quick look. Say 'held long'.

**Related:**

- [fii-dii-cash-flows](../market/fii-dii-cash-flows.md)
- [pulse-big-money](../market/pulse-big-money.md)

**Sources:**

- BSE participant-wise disclosures (Client is the residual category): https://bseindia.com/markets/Derivatives/DeriReports/DeriMarketDisclosures.aspx (search summary, 2026-10-31; the page returned 403).
- AlgoTest explainer: https://algotest.in/blog/participant-wise-open-interest/ (research 120).
- Research 105 on whether positioning predicts the next session.

## Example answers

**Q:** FIIs are only 11% long. Very bearish?

**A:** No more than usual. FIIs held 11% of their index futures long, close to their own one-year median (10.9%) and at the 39th percentile. They have been heavily net short futures all year, partly to hedge cash holdings.
