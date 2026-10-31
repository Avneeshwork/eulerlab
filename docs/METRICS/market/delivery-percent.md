# Delivery percentage and delivery spikes

*Family: Market context. Id: `delivery-percent`.*

**In one line:** Share of a stock's traded shares that were delivered rather than squared off the same day.

**Where you see it:** Stocks to watch → delivery spikes; `delivery.stocks[]`.

**How we compute it:** Delivered quantity / traded quantity from NSE's security-wise delivery file. A spike is today's % at least 1.5× its mean over the previous 20 sessions (75% present), among names with ₹10 crore median turnover.

**Data and freshness:** `delivery.jsonl`, daily after the close.

**What is normal (our data, as of 2026-10-30):** Varies by stock; the payload shows each name's own usual %.

**How to read it:**

- High delivery with a price rise: buyers taking stock home. High delivery with a fall: holders selling outright.
- Low delivery means mostly intraday trading.

**What it does not tell you:** Who bought, or their intent.

**Traps:**

- Block deals inflate delivery for one day.
- Illiquid names have noisy percentages.

**Related:**

- [new-highs-lows](../market/new-highs-lows.md)

**Sources:**

- NSE security-wise delivery position (definition from a QuantShare summary; NSE's file layout not confirmed, research 134 search).

## Example answers

**Q:** NIACL delivery 62% vs usual 24%?

**A:** About 2.6 times its usual share of shares changed hands for keeps. With the price down 4.6%, that reads as holders selling outright rather than traders churning.
