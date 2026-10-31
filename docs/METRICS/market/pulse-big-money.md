# Big money card

*Family: Market context. Id: `pulse-big-money`.*

**In one line:** FII index-futures long share against its own year: more bearish, usual or more bullish than usual.

**Where you see it:** Dashboard pulse.

**How we compute it:** Under the 25th percentile of the last 249 files: More bearish than usual; above the 75th: More bullish; else Usual (`market_pulse.money_card`).

**Data and freshness:** NSE participant OI.

**What is normal (our data, as of 2026-10-30):** Usual about half the time by construction.

**How to read it:**

- Read with cash flows: futures and cash can point opposite ways.

**What it does not tell you:** FII cash buying.

**Traps:**

- Thresholds are ours.

**Related:**

- [participant-long-share](../market/participant-long-share.md)
- [fii-dii-cash-flows](../market/fii-dii-cash-flows.md)

**Sources:**

- ADR-081.

## Example answers

**Q:** Big money says Usual while FIIs sold ₹5,000 cr cash?

**A:** The card reads index futures only. Their futures positioning is ordinary for them; the cash selling is a separate figure.
