# Participation card

*Family: Market context. Id: `pulse-participation`.*

**In one line:** Broad, Mixed or Narrow from the 200-day breadth share and the High-Low Index.

**Where you see it:** Dashboard pulse.

**How we compute it:** Both 50 or more: Broad. Both under 50: Narrow. Else Mixed. Tag from the 50-day share: under 30 Washed out, over 70 Stretched (`market_pulse.participation_card`).

**Data and freshness:** Breadth series.

**What is normal (our data, as of 2026-10-30):** See the breadth and High-Low pages.

**How to read it:**

- Narrow plus Washed out: most stocks in downtrends and short-term oversold.

**What it does not tell you:** Direction of the index.

**Traps:**

- Thresholds from StockCharts' US conventions (A-063).

**Related:**

- [breadth-above-average](../market/breadth-above-average.md)
- [high-low-index](../market/high-low-index.md)

**Sources:**

- Research 122; ADR-083.

## Example answers

**Q:** Participation: Narrow, Washed out?

**A:** Fewer than half of stocks are above their 200-day average and lows outnumber highs, and fewer than 30% are above their 50-day. The selling is wide, not just in a few names.
