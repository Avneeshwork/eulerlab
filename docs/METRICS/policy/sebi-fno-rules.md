# SEBI's index derivatives rules (2024 framework)

*Family: Government policy and regulators. Id: `sebi-fno-rules`.*

**In one line:** The rules SEBI tightened in 2024 to curb speculative index F&O trading.

**Where you see it:** Affects options strategies, lot sizes and expiry-day behaviour.

**How we compute it:** SEBI circular of 1 October 2024 (SEBI/HO/MRD/TPD-1/P/CIR/2024/132): minimum index contract size raised to ₹15 lakh; one weekly-expiry index per exchange; 2% extra extreme loss margin on short options on expiry day; intraday position-limit monitoring from 1 April 2025.

**Data and freshness:** SEBI circulars.

**Do we hold it:** Lot sizes are time-versioned in the instrument data (CLAUDE.md rule).

**What is normal (our data, as of 2026-10-30):** n/a

**How to read it:**

- Fewer weekly expiries concentrated volume on the remaining one; larger lots priced out small traders.

**What it does not tell you:** Later amendments.

**Traps:**

- Rules change; check the official circular or notification before quoting a rate or a date (A-085).
- Never hardcode lot sizes: they change with these rules and with the index level.

**Related:**

- [expiry-day](../events/expiry-day.md)
- [margins](../structure/margins.md)

**Sources:**

- SCC Online summary of the circular; Business Standard (search summary, 2026-10-31).

## Example answers

**Q:** Why did my options backtest change after November 2024?

**A:** SEBI's 2024 rules took effect from 20 November 2024: bigger minimum lots and fewer weekly expiries changed volumes and expiry-day behaviour, so earlier data is a different regime.
