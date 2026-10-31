# India VIX and its percentile

*Family: Market context. Id: `india-vix`.*

**In one line:** The market's own 30-day forecast of Nifty volatility, from option prices, ranked against the past year.

**Where you see it:** Dashboard strip and Fear card; brief scorecard row Volatility; `strip.vix.level`, `percentile_1y`, `median_1y`.

**How we compute it:** NSE computes the index (CBOE's method on Nifty options, interpolated to a constant 30 days). We read its close and rank it against the previous 251 closes (`market_context.index_strip`, `percentile_of`).

**Data and freshness:** NSE index history, daily close. Intraday VIX is in `make index-minute`.

**What is normal (our data, as of 2026-10-30):** Since 2015: median 15.3, 5th-95th percentile 11.1 to 24.7 (2,911 days). Past year: median 13.2, 5th-95th 10.0 to 22.7.

**How to read it:**

- VIX is an annualised percentage. Divide by √252 (about 15.9) for a one-day one-standard-deviation move: VIX 15.3 means about ±0.96% a day, roughly two days in three inside that.
- Rising VIX means option buyers pay more for protection; it usually rises when the market falls.
- Above the 70th percentile the brief calls it weak (A-082); the Fear card calls it Elevated.

**What it does not tell you:** Direction. A high VIX says moves will be large, not which way.

**Traps:**

- The percentile depends on the window: 15.3 was the 71st percentile of the past year but exactly the median since 2015. Say which window.
- VIX rolls to the next expiries 3 trading days before expiry (NSE), which can move it without any news.

**Related:**

- [atm-implied-volatility](../options/atm-implied-volatility.md)
- [expected-range](../market/expected-range.md)
- [pulse-fear](../market/pulse-fear.md)

**Sources:**

- NSE India VIX page and white paper: https://www.nseindia.com/static/products-services/indices-indiavix-index (method summarised from search, fetched 2026-10-31; the PDF itself was not read).
- `docs/ARCHITECTURE.md`, Market context on the dashboard

## Example answers

**Q:** VIX is 15.3. Is that high?

**A:** Above normal for the past year, not for the decade. It sits at the 71st percentile of the last 252 closes (median 13.2), but 15.3 is the median since 2015. It implies about ±0.96% a day for Nifty.

**Q:** What does a VIX jump from 13 to 16 mean for me?

**A:** Expected daily swings rise from about ±0.8% to ±1.0%. Option premiums are dearer. It does not say whether the market goes up or down.
