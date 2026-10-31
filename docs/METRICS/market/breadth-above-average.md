# Breadth: share of stocks above their 20, 50 and 200-day averages

*Family: Market context. Id: `breadth-above-average`.*

**In one line:** How many NSE stocks are in their own uptrend, rather than what the index did.

**Where you see it:** Brief scorecard row Breadth (50-day); Participation card (200-day); `breadth.latest.above_20/50/200`.

**How we compute it:** Split- and bonus-adjusted closes for every NSE stock (funds and ETFs dropped). A stock counts when its close is above its simple moving average and at least 90% of the window is present (`market_context.breadth`).

**Data and freshness:** The price panel, last 520 sessions; about 2,560 stocks.

**What is normal (our data, as of 2026-10-30):** Past year, above the 50-day: median 38.6%, 25th-75th 25.6% to 53.5%, 5th-95th 13.8% to 79.5%. Above the 200-day: median 37.5%.

**How to read it:**

- Below 30% above the 50-day: most stocks are in short-term downtrends; the brief calls breadth weak (A-082). Below about 15% is washed out (5th percentile).
- Breadth falling while the index rises is a narrow market: a few large caps hold the index up.
- StockCharts uses 50% of stocks above the 200-day as the line between a broad bull and bear bias (research 122).

**What it does not tell you:** Timing. Washed-out breadth can stay washed out for weeks.

**Traps:**

- Equal weight: a tiny stock counts the same as Reliance. That is the point, but it is not the index.
- Our universe is all NSE stocks, not Nifty 500, so levels are not comparable with figures quoted elsewhere.

**Related:**

- [new-highs-lows](../market/new-highs-lows.md)
- [pulse-participation](../market/pulse-participation.md)
- [index-returns](../market/index-returns.md)

**Sources:**

- StockCharts ChartSchool, Percent Above Moving Average: https://chartschool.stockcharts.com/table-of-contents/market-indicators/percent-above-moving-average (research 122).
- `docs/ARCHITECTURE.md`, Market context on the dashboard

## Example answers

**Q:** Breadth is 16%. What does that mean?

**A:** Only 16% of NSE stocks closed above their 50-day average, near the bottom 5% of the past year (median 39%). Most stocks are falling even though Nifty is near its 20-day average: the index is being held up by a few large names.
