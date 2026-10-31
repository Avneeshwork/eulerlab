# F&O ban period and market-wide position limit (MWPL)

*Family: Market structure and trading rules. Id: `fno-ban`.*

**In one line:** A stock's derivatives are frozen to new positions once open interest passes 95% of its limit.

**Where you see it:** Deals & filings tab (ban list).

**How we compute it:** When open interest crosses 95% of the stock's MWPL it enters the ban: only positions that reduce exposure are allowed; it leaves when OI falls below 80%. Index derivatives are not subject to it; the cash market keeps trading.

**Data and freshness:** NSE daily ban list.

**Do we hold it:** Yes, via `make nse-reports`.

**What is normal (our data, as of 2026-10-30):** n/a

**How to read it:**

- A stock in the ban often has heavy speculative positioning; when it exits, new positions can return quickly.

**What it does not tell you:** Direction.

**Traps:**

- Rules change; check NSE or SEBI before quoting (A-085).
- Thresholds are from broker summaries (Zerodha, IIFL), not NSE's own circular in this research.

**Related:**

- [sebi-fno-rules](../policy/sebi-fno-rules.md)

**Sources:**

- Zerodha support, IIFL (search summary, 2026-10-31).

## Example answers

**Q:** A stock I hold is in the F&O ban.

**A:** Its futures and options are frozen to new positions; the shares trade normally. It usually signals crowded derivatives positioning.
