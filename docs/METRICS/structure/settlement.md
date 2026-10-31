# Settlement (T+1)

*Family: Market structure and trading rules. Id: `settlement`.*

**In one line:** When shares and money actually change hands after a trade.

**Where you see it:** Cash management in the paper books.

**How we compute it:** Indian equities settle one trading day after the trade (T+1) (not fetched here; recheck).

**Data and freshness:** NSE/SEBI.

**Do we hold it:** n/a

**What is normal (our data, as of 2026-10-30):** n/a

**How to read it:**

- Sale proceeds are available the next day; delivery percentage is measured on settled trades.

**What it does not tell you:** Intraday trades, which are squared off.

**Traps:**

- Rules change; check NSE or SEBI before quoting (A-085).

**Related:**

- [delivery-percent](../market/delivery-percent.md)

**Sources:**

- Not fetched in this research.

## Example answers

**Q:** When do I get money from today's sale?

**A:** Under T+1 settlement, the next trading day.
