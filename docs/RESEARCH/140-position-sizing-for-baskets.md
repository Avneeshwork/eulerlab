# 140 — How should a basket strategy split its money?

**Date:** 2026-11-02 · **Confidence:** high that no model beat equal rupees on Sharpe by more than noise on these baskets; medium on the papers, of which only abstracts were read

## Question

For daily basket strategies on NSE equities with ₹50,000 to ₹10 lakh, does a risk-based split (inverse volatility, HRP, shrinkage minimum variance) beat equal rupees per name, after costs, whole shares and the ADR-120 caps?

## Sources (abstracts and listing pages, fetched 2026-11-02)

| Source | What it says |
|---|---|
| [DeMiguel, Garlappi & Uppal (2009), RFS 22(5)](https://ideas.repec.org/a/oup/rfinst/v22y2009i5p1915-1953.html) | None of 14 optimised models consistently beats 1/N out of sample on Sharpe, certainty equivalent or turnover. Beating it with 25 assets needs about 3,000 months of data |
| [Kirby & Ostdiek (2012), JFQA 47(2)](https://ideas.repec.org/a/cup/jfinqa/v47y2012i02p437-467_00.html) | 1/N's win comes mostly from optimisers' turnover. Volatility timing and reward-to-risk timing beat 1/N even with high costs |
| [Maillard, Roncalli & Teiletche (2010)](https://econbiz.de/Record/the-properties-of-equally-weighted-risk-contribution-portfolios-maillard-s%C3%A9bastien/10008445483) | Equal risk contribution sits between 1/N and minimum variance. Only the listing page was opened. That it equals inverse volatility under equal correlations is from memory, not this page |
| [López de Prado (2016), JPM](https://papers.ssrn.com/abstract=2708678) | HRP needs no inverse covariance and had lower out-of-sample variance than CLA in Monte Carlo |
| [Ledoit & Wolf (2004)](https://ideas.repec.org/p/bge/wpaper/92.html) | The sample covariance should not be used for optimisation; shrinkage to constant correlation improves it |
| [Jagannathan & Ma (2003), JF 58(4)](https://nber.org/papers/w8922) | A no-shorts rule on minimum variance acts as shrinkage |
| [Moreira & Muir (2017)](https://www.nber.org/papers/22208) | Scaling exposure down when volatility is high raised factor Sharpe ratios |
| [Cederburg, O'Doherty, Wang & Yan (2020), JFE 138(1)](https://econpapers.repec.org/RePEc:eee:jfinec:v:138:y:2020:i:1:p:95-117) | Across 103 strategies, real-time volatility-managed versions usually earn lower Sharpe than unmanaged ones |

## Test

Tier A engine, realistic costs, next-day fills, whole shares, Jan 2016 to 30 Oct 2026, panel from the operator's Mac. The strategy picks the names; only the split differs; every split keeps the strategy's gross. The ADR-120 caps and affordability fit applied. 126-day windows; Ledoit-Wolf constant-correlation covariance. ₹50,000, ₹1 lakh, ₹10 lakh. Script and all 60 results: project files `sizing-study/`.

At ₹1 lakh (CAGR / Sharpe / max drawdown / one-way turnover a year):

| Strategy | Equal rupees | Inverse volatility | HRP | Min-variance |
|---|---|---|---|---|
| Clenow, top 25 weekly | 21.9% / 1.08 / -30.2% / 7.6 | 21.4% / 1.10 / -28.0% / 8.0 | 20.2% / 1.09 / -26.3% / 10.3 | 19.1% / 1.07 / -23.7% / 11.2 |
| Sharpe momentum, top 30 monthly | 22.5% / 1.04 / -44.6% / 3.8 | 20.4% / 1.02 / -41.4% / 4.0 | 18.6% / 1.00 / -42.2% / 4.5 | 14.8% / 0.85 / -37.1% / 4.9 |
| Minervini, top 20 monthly | 20.1% / 0.89 / -43.9% / 5.4 | 20.6% / 0.93 / -43.1% / 5.6 | 20.3% / 0.95 / -44.6% / 6.0 | 21.2% / 0.98 / -39.3% / 6.6 |
| Weinstein, top 20 weekly | 21.9% / 0.91 / -48.2% / 7.1 | 20.5% / 0.91 / -49.0% / 9.5 | 20.5% / 0.93 / -50.4% / 12.3 | 14.7% / 0.72 / -47.1% / 14.2 |
| Illiquid winners, about 37 monthly | 19.5% / 0.90 / -45.8% / 4.1 | 20.7% / 0.98 / -40.1% / 4.3 | 21.2% / 1.05 / -33.1% / 4.8 | 22.1% / 1.13 / -27.7% / 5.5 |

## Findings

1. No split beat equal rupees by more than noise across the baskets. A Sharpe standard error over 10.8 years is about 0.3.
2. Risk models lower drawdown and raise turnover. Min-variance hurt Sharpe momentum and Weinstein badly.
3. Capital between ₹50,000 and ₹10 lakh moved CAGR by at most 1.3 points per split, once the ADR-120 fit was in place.
4. Illiquid winners is the one basket where min-variance helped in both halves (Sharpe 0.91 and 1.31 against 0.62 and 1.12).

## Decision

Equal by default, a strategy's own weights when declared, models by name (ADR-122, the operator's choice). The research first proposed inverse volatility as the default; the operator chose equal.

## Not found or not done

- Full texts were not read; only abstracts and listing pages.
- The 60 runs were not written to the trial ledger: they are sizing variants, not gate candidates. The operator has not yet said whether to log them.
- Kelly sizing was not tested: it needs expected returns per stock.
- Sharpe uses a 0% risk-free rate.
