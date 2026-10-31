# High-Low Index

*Family: Market context. Id: `high-low-index`.*

**In one line:** The 10-day average share of new highs among new highs plus new lows, 0 to 100.

**Where you see it:** Participation card; `breadth.latest.high_low_index`.

**How we compute it:** 10-day mean of highs / (highs + lows) × 100 (`market_context.breadth`).

**Data and freshness:** Price panel.

**What is normal (our data, as of 2026-10-30):** Past year: median 47.5, 25th-75th 23.7 to 75.2.

**How to read it:**

- Above 50: more stocks making highs than lows over two weeks. Under 30: lows dominate.
- The Participation card needs both this and the 200-day share above 50 to say Broad.

**What it does not tell you:** How many stocks are involved: 3 highs and 1 low read 75.

**Traps:**

- Small counts make it jumpy; read it with the raw counts.

**Related:**

- [new-highs-lows](../market/new-highs-lows.md)
- [pulse-participation](../market/pulse-participation.md)

**Sources:**

- StockCharts ChartSchool, High-Low Index: https://chartschool.stockcharts.com/table-of-contents/market-indicators/high-low-index (research 122).

## Example answers

**Q:** High-Low Index is 15.8?

**A:** Over the last two weeks, about one stock in six making a 52-week extreme made a high; the rest made lows. That is in the bottom quarter of the past year.
