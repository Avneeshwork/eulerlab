# Beta and alpha (factor regression)

*Family: Strategy performance. Id: `beta-and-alpha`.*

**In one line:** How much of the return moved with the market and factors, and what was left over.

**Where you see it:** Attribution tab; risk (beta); `beta`, `alpha_annual`, `alpha_t`.

**How we compute it:** Regression of monthly strategy returns on the market and house factors (size, momentum, low volatility); alpha_t = coefficient / standard error (`attribution_detail.factors`). Book beta: cov(r, r_m) / var(r_m) against NIFTYBEES (`risk/book.beta`).

**Data and freshness:** Monthly returns; IIMA Indian factor files (research 116).

**What is normal (our data, as of 2026-10-30):** Beta near 1 for a long-only stock book.

**How to read it:**

- High beta: mostly market exposure. Alpha with t above about 2 is worth a look; the gate asks for t ≥ 3 on the strategy itself.

**What it does not tell you:** Future alpha.

**Traps:**

- Few monthly points make alpha_t unstable.

**Related:**

- [brinson-attribution](../attribution/brinson-attribution.md)
- [t-statistic](../validation/t-statistic.md)

**Sources:**

- Research 114, 115, 116.

## Example answers

**Q:** Alpha 6% a year, t 1.4?

**A:** Not distinguishable from zero: a t-statistic of 1.4 happens by chance often. Most of the return is explained by the market and factors.
