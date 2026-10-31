# Turnover, cost drag and slippage

*Family: Strategy performance. Id: `turnover-and-costs`.*

**In one line:** How much was traded relative to capital, and how much the charges ate.

**Where you see it:** Reports; `turnover_x`, `cost_drag`, `costs`, `slippage_bps_per_side`.

**How we compute it:** turnover_x = traded value / starting equity; cost_drag = total costs / starting equity (`src/eulerlab/reports.py` (`_figures`)). Costs are itemised: STT, exchange, stamp, GST, brokerage, plus modelled slippage (`docs/ARCHITECTURE.md` §4.2).

**Data and freshness:** Fills.

**What is normal (our data, as of 2026-10-30):** n/a

**How to read it:**

- Gross good but net poor: a turnover problem.
- The gate's 2× cost stress tests whether the edge survives doubled charges.

**What it does not tell you:** Market impact at larger size (see capacity).

**Traps:**

- Slippage is a model; real fills can be worse on illiquid names.

**Related:**

- [capacity](../performance/capacity.md)
- [stress-tests](../validation/stress-tests.md)

**Sources:**

- Research 013 (Indian transaction costs).
- `docs/ARCHITECTURE.md` §4.2.

## Example answers

**Q:** Cost drag 9%?

**A:** Charges ate 9% of starting capital over the test. If the strategy's total return was 20%, nearly a third went to costs: turnover is the first thing to cut.
