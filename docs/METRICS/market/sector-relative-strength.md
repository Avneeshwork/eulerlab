# Sector relative strength and phase

*Family: Market context. Id: `sector-relative-strength`.*

**In one line:** Which sectors beat or lag Nifty 50, and whether that is improving.

**Where you see it:** Dashboard → Sectors; brief detail Sectors against Nifty; `sectors.sectors[]`.

**How we compute it:** Relative return = (1 + sector) / (1 + Nifty 50) − 1 over 5, 21 and 63 sessions. Rising: the 1-month relative is above its value 5 sessions ago. Phase: 3-month relative above or below zero, crossed with rising (leading, weakening, lagging, improving).

**Data and freshness:** 20 NSE sector indices from index history.

**What is normal (our data, as of 2026-10-30):** Not computed as a range; a sector's relative return is zero on average by construction only against an equal mix, not against Nifty.

**How to read it:**

- Leading: beating Nifty over 3 months and still improving. Lagging: behind and still worsening.
- Rotation shows as sectors moving from lagging to improving.

**What it does not tell you:** Whether the sector rises in absolute terms: a leading sector can still fall, just less.

**Traps:**

- Sector indices overlap Nifty 50, so a heavy sector moves Nifty itself and its relative return understates its effect.

**Related:**

- [index-returns](../market/index-returns.md)

**Sources:**

- `docs/ARCHITECTURE.md`, Market context on the dashboard

## Example answers

**Q:** Which sectors are leading?

**A:** IT, Pharma, Media and PSU Bank are beating Nifty over 3 months and still improving. Financial Services, Metal, Oil & Gas and Energy are behind and still slipping. Leading means beating Nifty, not rising.
