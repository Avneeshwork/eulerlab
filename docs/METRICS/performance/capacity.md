# Capacity: days to trade

*Family: Strategy performance. Id: `capacity`.*

**In one line:** How many days each buy would take at a set share of the stock's daily turnover, and the capital that fits in one day.

**Where you see it:** Strategy report → capacity; `capacity`.

**How we compute it:** days_to_trade = order value / (participation × median daily turnover over the prior 60 sessions); capital_for_one_day scales that to the book (`attribution_detail.capacity`).

**Data and freshness:** Orders and turnover from the price panel.

**What is normal (our data, as of 2026-10-30):** n/a; the report shows the median and 90th-percentile days to trade.

**How to read it:**

- The tightest names cap how much money the strategy can run.

**What it does not tell you:** Price impact cost.

**Traps:**

- Median turnover hides days when the stock barely trades.

**Related:**

- [turnover-and-costs](../performance/turnover-and-costs.md)

**Sources:**

- `src/eulerlab/attribution_detail.py`.

## Example answers

**Q:** (Illustrative) Capital where 90% trade in a day: ₹40 lakh?

**A:** Above about ₹40 lakh, some buys would need more than a day at the assumed participation, so fills would drift from the backtest.
