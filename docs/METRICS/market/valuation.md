# Index valuation: P/E, P/B and dividend yield

*Family: Market context. Id: `valuation`.*

**In one line:** How expensive Nifty is against its own history, from NSE's published ratios.

**Where you see it:** Dashboard valuation bars; brief scorecard row Valuation; `valuation.indices[].pe/pb/dy`.

**How we compute it:** NSE's own P/E, P/B and yield; we rank today against the index's history (P/E only since 1 April 2021, A-062).

**Data and freshness:** NSE index history, daily.

**What is normal (our data, as of 2026-10-30):** Nifty 50 P/E since April 2021: median 22.1, 5th-95th 19.9 to 28.3. P/B since 2015: median 3.56 (2.95 to 4.41). Dividend yield: median 1.27% (1.07% to 1.51%).

**How to read it:**

- Low percentile: cheap against its own past. The brief calls under the 20th percentile supportive (A-082).
- Valuation is slow: it matters over months and years, not days.

**What it does not tell you:** Timing. Markets can stay cheap or dear for years.

**Traps:**

- NSE moved P/E to consolidated earnings on 1 April 2021; Nifty's fell from about 40 to 33 overnight. Comparing across that date is wrong (A-062).
- A P/E falls when earnings rise as well as when prices fall.

**Related:**

- [company-pe](../fundamentals/company-pe.md)

**Sources:**

- Capitalmind and PrimeInvestor on the 2021 switch (research 120). NSE's methodology note was not fetched (A-062).
- `docs/ARCHITECTURE.md`, Market context on the dashboard

## Example answers

**Q:** Is Nifty cheap?

**A:** Against the last five years, yes: P/E 19.3 is at the 1st percentile since April 2021 (median 22.1). That is a slow signal; it says little about the next few weeks.
