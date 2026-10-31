# 138 — Can the Sharpe bar be set without counting raw trials?

**Date:** 2026-10-31 · **Confidence:** high on what the methods do; medium on the numbers below, which use one stored configuration per strategy

## Question

The operator (2026-10-31): "don't think about how many trials we have done ... instead of 5 trials a week make it unlimited ... check other method for sharpe ratio bar instead of no of trials."

The gate's bar today is the expected maximum Sharpe of N worthless strategies (ARCHITECTURE 5.3), with N = rows in the trial ledger (19) and an assumed spread of Sharpes σ_SR = 1.0 (A-021). Every trial raises it, whether or not it was a new idea.

## Sources

| Source | URL | Fetched | Read |
|---|---|---|---|
| López de Prado and Lewis, "Detection of false investment strategies using unsupervised learning methods", Quantitative Finance 19(9) 2019, SSRN 3167017 | https://smallake.kr/wp-content/uploads/2020/04/SSRN-id3167017.pdf | 2026-10-31 | Method sections (SSRN version) |
| Same paper, publisher record | https://ideas.repec.org/a/taf/quantf/v19y2019i9p1555-1565.html | 2026-10-31 | Search listing only |
| Harvey and Liu, "Backtesting", JPM 41(1) 2015, via quantstrat's `profitHurdle` documentation | https://www.rdocumentation.org/link/profit.hurdle | 2026-10-31 | Documentation page; the paper itself not read |
| Romano and Wolf, "Stepwise Multiple Testing as Formalized Data Snooping", working paper, October 2003 (later Econometrica 2005) | https://econ-papers.upf.edu/papers/712.pdf | 2026-10-31 | Method and comparison with White's Reality Check |

## Findings

1. **No valid method ignores the search.** All three correct for it; they differ in what they count.
2. **Effective number of trials (López de Prado and Lewis).** Cluster every strategy tried by return correlation (ONC on a distance of distances, scored by silhouette t-value). N = number of clusters. σ_SR is measured as the spread of the clusters' annualised Sharpes, each cluster formed with minimum-variance weights. The deflated Sharpe is then computed against that bar. A tenth variant of one idea adds nothing; a new kind of idea adds one.
3. **Haircut Sharpe (Harvey and Liu).** Adjust the p-value of the Sharpe for M tests with an assumed average correlation, by Bonferroni, Holm or BHY, and convert back to a Sharpe. Still needs M and an assumed correlation, so it moves the problem rather than removing it.
4. **Romano–Wolf StepM (and White's Reality Check).** Bootstrap all strategies' returns jointly (block bootstrap for time series) and take the critical value from the distribution of the maximum statistic. Correlation between strategies is captured by the bootstrap; no N or σ is assumed. It controls the chance of any false discovery in the strong sense; White's test checks only the best strategy. It needs the full return series of everything tested, on one common window.

## Measured on our stored results (2026-10-31, 68 India daily strategies, one configuration each)

| Bar | N | σ_SR | Bar (Sharpe) |
|---|---|---|---|
| Today: ledger rows, assumed σ | 19 | 1.0 (assumed) | 1.88 |
| Every stored strategy, assumed σ | 68 | 1.0 | 2.39 |
| Every stored strategy, measured σ | 68 | 0.39 | 0.94 |
| Families at correlation 0.7, measured σ | 27 | 0.48 | 0.98 |
| Participation ratio, measured σ | 2.78 | 0.48 | 0.38 |

The assumed σ_SR of 1.0 is about twice the measured spread. That, not N, is most of why today's bar is 1.88.

StepM (stationary block bootstrap, mean block 20 days, 2,000 draws, 5% level, 54 strategies with a common window 2016-01-25 to 2026-09-30):

- Return above zero: critical Sharpe 0.97; 8 survive (best `india_sharpe_momentum_opt` 1.29). Beating cash is not skill here: Nifty itself earns a positive Sharpe.
- Return above Nifty (beta 1): critical Sharpe 0.94; Reality Check p = 0.035 for the best; **1 survives, `india_sharpe_momentum_opt` (1.00)**. It is the tuned version of `india_sharpe_momentum`, and the configurations its tuning tried are not in the 54 series, so the test cannot see that search. Its pass is therefore not evidence until those runs are included.

## Decision

Proposed, not built; `gates.py` and `mandate.yaml` are operator-owned. Replace "N = ledger rows, σ = 1.0" with: (a) N = families of everything ever tested and σ_SR measured across those families, and (b) a StepM test on excess returns over Nifty across everything tested. Both stop punishing repeats of one idea and both still catch luck. Every configuration's daily returns must be stored for this to be honest, including optimiser sweeps. The weekly trial limit is lifted (ADR-107); the ledger keeps recording.

## Open questions

1. Families by our average-linkage at 0.7 or by ONC as published? ONC is not implemented here; the participation ratio (2.78) is too lenient to use as N.
2. Optimiser and walk-forward runs store only summaries, not every configuration's returns; they must be stored before (a) or (b) can see them.
3. The Harvey–Liu paper was read only through its R documentation.
