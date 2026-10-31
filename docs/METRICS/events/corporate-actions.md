# Corporate actions: dividends, splits, bonuses, rights

*Family: Market events and calendar. Id: `corporate-actions`.*

**In one line:** Company events that change the share count or pay out cash, and so the price.

**Where you see it:** Price adjustment everywhere; company pages.

**How we compute it:** Prices are back-adjusted with factors on the ex-date (`docs/ARCHITECTURE.md` §3.4).

**Data and freshness:** NSE corporate actions feed.

**Do we hold it:** Yes, with adjustment factors.

**What is normal (our data, as of 2026-10-30):** n/a

**How to read it:**

- A split or bonus lowers the price with no change in value; a dividend lowers the price by the dividend on the ex-date.

**What it does not tell you:** Value created.

**Traps:**

- Unadjusted prices make a bonus look like a crash (HISTORY #36).

**Related:**

- [new-highs-lows](../market/new-highs-lows.md)

**Sources:**

- `docs/ARCHITECTURE.md` §3.4; research 008, 009, 010.

## Example answers

**Q:** Reliance fell 50% on 28 Oct 2024?

**A:** That was a 1:1 bonus: twice the shares at half the price. Adjusted prices show no fall.
