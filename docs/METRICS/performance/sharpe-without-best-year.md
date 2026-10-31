# Sharpe without the best year, and best 1% of days

*Family: Strategy performance. Id: `sharpe-without-best-year`.*

**In one line:** Whether the result depends on one lucky year or a handful of days.

**Where you see it:** Skeptic agent findings.

**How we compute it:** Sharpe recomputed after dropping the best calendar year; share of total log return from the best 1% of days (`agents/workers/skeptic.attacks`).

**Data and freshness:** Equity curve.

**What is normal (our data, as of 2026-10-30):** A robust result keeps most of its Sharpe.

**How to read it:**

- A collapse means the strategy is one episode, not an edge.

**What it does not tell you:** A formal test.

**Traps:**

- Short histories have few years to drop.

**Related:**

- [stress-tests](../validation/stress-tests.md)

**Sources:**

- `src/eulerlab/agents/workers/skeptic.py`.

## Example answers

**Q:** Sharpe drops from 1.2 to 0.3 without 2020?

**A:** The result is mostly one year. That is fragile, whatever the headline number.
