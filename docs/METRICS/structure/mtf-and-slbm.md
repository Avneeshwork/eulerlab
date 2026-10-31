# Margin trading (MTF) and securities lending (SLBM)

*Family: Market structure and trading rules. Id: `mtf-and-slbm`.*

**In one line:** Borrowed money used to buy shares, and shares lent out for short selling.

**Where you see it:** Deals & filings tab.

**How we compute it:** NSE publishes MTF positions and SLBM activity daily.

**Data and freshness:** `make nse-reports`.

**Do we hold it:** Yes (ADR-095).

**What is normal (our data, as of 2026-10-30):** n/a

**How to read it:**

- Rising MTF in a stock means more leveraged buyers who may be forced to sell in a fall.
- Heavy SLBM borrowing can mean short interest.

**What it does not tell you:** Total short positions (derivatives shorts are elsewhere).

**Related:**

- [block-and-bulk-deals](../events/block-and-bulk-deals.md)
- [fno-ban](../structure/fno-ban.md)

**Sources:**

- ADR-095; research 130.

## Example answers

**Q:** MTF book in a midcap doubled.

**A:** More shares are held with borrowed money; in a sharp fall, margin calls can add selling.
