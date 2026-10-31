# Invested fraction and exposure

*Family: Strategy performance. Id: `invested-fraction`.*

**In one line:** Share of days (or capital) actually in the market.

**Where you see it:** Reports (`invested_fraction`); attribution exposure; the brief's books ('% invested').

**How we compute it:** 1 − flat days / all days (`src/eulerlab/reports.py` (`_figures`)). Live: 1 − cash / equity (`market_brief._books`).

**Data and freshness:** Daily returns; deployment state.

**What is normal (our data, as of 2026-10-30):** n/a

**How to read it:**

- Low exposure flatters drawdown and hurts return; compare strategies at similar exposure.

**What it does not tell you:** Leverage.

**Traps:**

- Zero-return days are counted as flat even if a position happened to be unchanged.

**Related:**

- [sharpe-ratio](../performance/sharpe-ratio.md)

**Sources:**

- `src/eulerlab/reports.py` (`_figures`)

## Example answers

**Q:** Why is hit rate 14%?

**A:** It held cash most days. On the days it was invested, check `hit_rate_invested`.
