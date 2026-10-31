# Capital gains tax and securities transaction tax (STT)

*Family: Government policy and regulators. Id: `capital-gains-and-stt`.*

**In one line:** The taxes on investment profits and on each trade.

**Where you see it:** The cost model uses STT on every fill (research 013).

**How we compute it:** Budget 2024 (from 23 July 2024): long-term capital gains on listed equity 12.5% above ₹1.25 lakh a year; short-term 20%. STT on F&O sales raised from 1 October 2024: futures 0.0125% → 0.02%, options 0.0625% → 0.1% of premium.

**Data and freshness:** Finance Act; CBDT.

**Do we hold it:** STT rates are in the cost model (`costs/`), research 013.

**What is normal (our data, as of 2026-10-30):** n/a

**How to read it:**

- Higher STT raises the cost of high-turnover strategies directly; the backtest cost drag reflects it.

**What it does not tell you:** Your personal tax position.

**Traps:**

- Rules change; check the official circular or notification before quoting a rate or a date (A-085).
- Any later Budget may change these again; the cost model must be updated, not just this page.
- Sources gave conflicting old futures STT figures; the circular is authoritative.

**Related:**

- [turnover-and-costs](../performance/turnover-and-costs.md)
- [union-budget](../policy/union-budget.md)

**Sources:**

- Business Standard, 23 July 2024; Zerodha summary (search summary, 2026-10-31); research 013.

## Example answers

**Q:** Did STT on options go up?

**A:** Yes, from 1 October 2024 STT on option sales rose from 0.0625% to 0.1% of the premium (Budget 2024). Check whether a later Budget changed it.
