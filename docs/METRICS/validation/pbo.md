# Probability of backtest overfitting (PBO)

*Family: Validation and the gate. Id: `pbo`.*

**In one line:** How often the configuration that won in sample finishes below the median out of sample.

**Where you see it:** Gate; optimisation walk; `pbo`.

**How we compute it:** For each CPCV split, rank the in-sample winner out of sample; PBO = share of splits where its logit rank ≤ 0 (`validation/statistics.probability_of_backtest_overfitting`; `docs/ARCHITECTURE.md` §5.4).

**Data and freshness:** Scores per configuration per split.

**What is normal (our data, as of 2026-10-30):** The gate allows at most 0.25 (`mandate.yaml` (operator-owned)). Above 0.5 is worse than a coin flip.

**How to read it:**

- It judges the act of choosing, not one strategy.
- Read it with the share of settings profitable out of sample (`docs/ARCHITECTURE.md`, Reading PBO requires a second number).

**What it does not tell you:** Whether a single configuration works.

**Traps:**

- When nearly every setting is profitable, PBO climbs toward 0.5 by construction: the parameter does not matter, which is not overfitting (A-039).
- Intraday walks are not purged, so their PBO is mildly optimistic (A-040).

**Related:**

- [cpcv](../validation/cpcv.md)
- [deflated-sharpe](../validation/deflated-sharpe.md)

**Sources:**

- Bailey, Borwein, López de Prado & Zhu (2017), Journal of Computational Finance 20(4): https://escholarship.org/uc/item/4w1110bb (abstract read 2026-10-31).

## Example answers

**Q:** PBO 0.47 but all 9 settings profitable?

**A:** That high PBO mostly says the settings perform alike, so which one wins in sample is a coin toss. That is a different story from 0.47 with few profitable settings.
