# New 52-week highs and lows

*Family: Market context. Id: `new-highs-lows`.*

**In one line:** How many stocks closed at a one-year high or low today.

**Where you see it:** Brief scorecard row Breadth; Stocks to watch lists; `breadth.latest.new_highs`, `new_lows`.

**How we compute it:** A close above every one of the previous 251 closes is a new high; below every one, a new low (adjusted closes).

**Data and freshness:** Price panel. Name lists only show stocks with a 20-day median turnover of ₹10 crore or more.

**What is normal (our data, as of 2026-10-30):** Past year: new highs median 41 (5th-95th 7 to 92); new lows median 41 (5th-95th 2 to 380). Lows spike much more than highs.

**How to read it:**

- Highs well above lows: broad strength. Lows several times highs: broad weakness, even if the index is flat.
- Look at the names: new highs among large, liquid names mean more than among illiquid ones.

**What it does not tell you:** Whether the trend continues.

**Traps:**

- Closing highs, not intraday highs.
- Corporate actions are adjusted; a missed adjustment would show as a fake new low (see data quality).

**Related:**

- [high-low-index](../market/high-low-index.md)
- [breadth-above-average](../market/breadth-above-average.md)

**Sources:**

- `docs/ARCHITECTURE.md`, Market context on the dashboard

## Example answers

**Q:** 26 new highs and 206 new lows. Bad?

**A:** Yes for the average stock. New lows ran eight times new highs; 206 is above the 75th percentile of the past year (117), while 26 highs is below the median (41).
