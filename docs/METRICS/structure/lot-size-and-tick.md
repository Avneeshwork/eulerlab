# Lot size, tick size and contract multiplier

*Family: Market structure and trading rules. Id: `lot-size-and-tick`.*

**In one line:** The units contracts trade in; they change over time.

**Where you see it:** Instruments; options backtests.

**How we compute it:** Stored as time-versioned fields on each instrument; never hardcoded (CLAUDE.md).

**Data and freshness:** NSE contract files.

**Do we hold it:** Yes.

**What is normal (our data, as of 2026-10-30):** n/a

**How to read it:**

- A backtest across a lot-size change must use the size valid on each date.

**What it does not tell you:** Liquidity.

**Traps:**

- Hardcoding a lot size silently breaks old or new data.

**Related:**

- [sebi-fno-rules](../policy/sebi-fno-rules.md)

**Sources:**

- CLAUDE.md, Data integrity rules; research 006.

## Example answers

**Q:** Nifty lot size?

**A:** Look it up for the date in question from the instrument data; it changed with SEBI's 2024 rules and periodic NSE revisions.
