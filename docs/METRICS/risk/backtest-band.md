# Live against the backtest band

*Family: Risk on the live book. Id: `backtest-band`.*

**In one line:** Whether the live book's return so far sits inside the range its backtest produced over the same horizon.

**Where you see it:** Live & Risk.

**How we compute it:** For each horizon h, the 5th, 50th and 95th percentile of every h-day backtest return; the live time-weighted return is placed in it (`risk/book.backtest_band`, `against_backtest`).

**Data and freshness:** Stored backtest; live curve. No verdict before 20 days live.

**What is normal (our data, as of 2026-10-30):** Inside the 5-95 band about 90% of the time if live matches the backtest.

**How to read it:**

- Below the 5th percentile for long: live is not behaving like the test.

**What it does not tell you:** Why.

**Traps:**

- Short live histories land outside the band by chance.

**Related:**

- [time-weighted-return](../performance/time-weighted-return.md)

**Sources:**

- `docs/ARCHITECTURE.md`, Risk on the deployed book (ADR-071)

## Example answers

**Q:** Live is at the backtest's 3rd percentile after 25 days?

**A:** Worse than 97% of 25-day stretches in the backtest. Not proof of a break, but worth checking fills and costs.
