# Total return and annualised return (CAGR)

*Family: Strategy performance. Id: `total-and-annual-return`.*

**In one line:** How much the money grew over the test, and the same as a yearly compound rate.

**Where you see it:** Reports and tables; `total_return`, `annualised`, `cagr`.

**How we compute it:** End / start − 1; annualised = (end / start)^(1 / years) − 1 with years = trading days / 252 (`src/eulerlab/reports.py` (`_figures`)).

**Data and freshness:** Equity curve, net of modelled costs.

**What is normal (our data, as of 2026-10-30):** Compare with Nifty over the same window (`nifty_return`).

**How to read it:**

- Always against the benchmark and the drawdown suffered to get it.

**What it does not tell you:** Risk.

**Traps:**

- Short windows annualise wildly: 10% in three months is 46% a year on paper.
- Live books use the time-weighted return, so deposits and withdrawals do not count (see time-weighted-return).

**Related:**

- [time-weighted-return](../performance/time-weighted-return.md)
- [benchmark-return](../performance/benchmark-return.md)
- [max-drawdown](../performance/max-drawdown.md)

**Sources:**

- `src/eulerlab/reports.py` (`_figures`)

## Example answers

**Q:** It made 40% in 4 months. Annualised 175%?

**A:** That is the arithmetic, but four months is far too short to annualise meaningfully. Say the 40% and the drawdown along the way.
