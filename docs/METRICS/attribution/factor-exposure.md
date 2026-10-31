# Factor exposures and rolling exposure

*Family: Attribution. Id: `factor-exposure`.*

**In one line:** How much the strategy behaves like the market, small caps, momentum or low volatility.

**Where you see it:** Strategy report → factors.

**How we compute it:** Monthly regression on house factors and IIMA Indian factors; rolling windows (`attribution_detail.factors`, `rolling`).

**Data and freshness:** Monthly returns; research 116.

**What is normal (our data, as of 2026-10-30):** n/a

**How to read it:**

- A 'new' strategy with a large momentum loading may be momentum in disguise.

**What it does not tell you:** Causation.

**Traps:**

- Short histories give unstable loadings.

**Related:**

- [beta-and-alpha](../performance/beta-and-alpha.md)

**Sources:**

- Research 116 (India factor download).

## Example answers

**Q:** Momentum loading 0.8?

**A:** Most of its behaviour tracks the momentum factor; check whether it adds anything beyond a plain momentum portfolio.
