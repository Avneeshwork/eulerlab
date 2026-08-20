# 014 — Low-volatility anomaly in Indian equities

**Sprint:** 15 · **Date:** 2026-08-19 · **Confidence:** medium on the
literature, **zero on whether it survives this project's own gate**

## Question

Sprint 15 needed a real candidate to exercise the paper-scout machinery. What
cross-sectional anomaly is documented specifically for Indian equities, and is
it worth a hypothesis card given what a card costs?

## Finding: the low-risk effect is reported repeatedly on NSE data

- A study of the NSE from January 2001 to June 2016 reports low-risk
  portfolios — sorted on total, systematic and unsystematic risk — earning
  higher returns than high-risk portfolios across large, mid and small caps,
  with differences described as economically and statistically significant.
  [IRA-International Journal of Management & Social Sciences](https://research-advances.org/index.php/RAJMSS/article/view/289),
  fetched 2026-08-19.
- A separate study of the top 500 liquid NSE stocks from January 2004 to
  December 2018 also reports a low-risk effect.
- Quantpedia catalogues the low-volatility factor as a general cross-sectional
  effect, not India-specific.
  [Quantpedia](https://quantpedia.com/strategies/low-volatility-factor-effect-in-stocks),
  fetched 2026-08-19.

The effect is claimed to persist after controlling for size, value and
momentum, which is the part that makes it interesting rather than a restatement
of a known factor.

## Finding: our own supporting evidence is not usable

Sprint 8 scored `low_volatility` at an IC t-statistic of **+5.78**, the highest
of the ten seed features. That number **cannot be cited in support of this
hypothesis**, for two independent reasons:

1. It was computed on **raw, unadjusted prices** — the bug found in Sprint 13.
2. It used the **2023–2026 panel**, three years of a bull market, not the
   eleven now available.

Both are fixed and neither has been recomputed (T-1317). Citing the old figure
would be using a number known to be wrong because it points the right way.

## Finding: this cluster is not four ideas

Sprint 13 measured `low_volatility`, `max_drawdown` and `price_to_52w_high` as
a single group with internal IC correlation of **+0.86 to +0.95**. A card
offering four configurations drawn from that cluster is offering closer to one
finding, and its PBO must be read with that in mind.

## Decision

Draft `H-0002` as a **draft, not registered**. It is a genuine candidate with
real sources, and it exists partly to exercise the Sprint 15 machinery
end to end.

Registering and validating it is a separate, deliberate act, and the arithmetic
argues for caution: the trial ledger stands at 17, so a candidate must already
beat a Sharpe of **1.83** from pure noise. The best real Sharpe this project
has produced is **1.27**. Low volatility is not expected to exceed momentum.

## What I could not verify

- **The primary papers themselves.** These are search-result summaries and
  abstracts, not the full texts. The card records the URL and fetch date and
  claims nothing beyond what the abstracts state.
- **Whether the reported effect survives Indian transaction costs.** None of
  the cited studies is described as netting them, and Sprint 9 exists because
  those costs are substantial.
- **Whether it is distinct from the buy-and-hold control.** Low-volatility
  books concentrate in large liquid names — exactly the cohort that returned
  only +4.6% annualised in our own 2016–2026 control. The anomaly may hold
  against zero and not against that.
