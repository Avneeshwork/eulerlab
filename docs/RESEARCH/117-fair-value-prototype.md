# 117 — Fair-value prototype from held Indian equity data

**Date:** 2026-10-21 · **Status:** implemented as an internal estimate

**Update:** the equal-weight v1 composite described below was superseded on
2026-10-21 by the multi-stage residual-income model in
[research note 118](118-bank-aware-fair-value-v2.md). The old runs remain stored
with their original model version for auditability.

## Inputs

- Consolidated company snapshots from `data/landing/fundamentals/`.
- Book value per share, trailing EPS, dividend yield, industry classification,
  and peer P/E/P/B/ROE from the existing company digest.
- Split/bonus-adjusted closes from the existing company price panel.
- IIMA survivorship-bias-adjusted daily and monthly four-factor files from
  `data/landing/india_factors/` (see research note 116).
- The newest held `INDIA 10Y` macro reading from `data/landing/macro/`.

## Calculation

The base model uses the Frankel-Lee three-year residual-income form. Year-one
EPS is trailing EPS (or the latest annual EPS if TTM EPS is unavailable), and
year-one FROE is EPS divided by current book value per share. FROE fades halfway
to the industry median in year two and to the industry median in year three;
when no peer ROE median exists, year three fades to the cost of equity. Cyclical
industries use the median of the last three annual EPS values when available.
Book value rolls forward under clean-surplus accounting. Payout is inferred
from dividend yield and trailing EPS, capped at 80%; missing payout assumes
full retention and is disclosed.

Daily OLS estimates market, size and value betas over at most five years, using
stock returns less the daily IIMA RF return. Estimates are shrunk 20% toward
the priors (1, 0, 0). Market ERP uses the roadmap's IIMB estimate of 7.78%;
the long-run arithmetic averages of monthly SMB and HML, annualized by
multiplying by 12, supply size and value premia. WML is excluded from cost of
equity. Cost of equity uses the latest held India 10-year yield plus the
beta-weighted premia and is clamped to the proposed 10%-16% range. If the macro
yield is absent, the recent IIMA RF series is used and flagged.

The composite equally weights all available positive values. Financial
companies use residual income and peer P/B; other companies may also use peer
P/E. Peer multiples are initial cross-checks and are not adjusted for growth or
ROE differences. DCF, analyst consensus, and investor-facing output are outside
this prototype.

## Storage and limitations

The company API writes each distinct output under
`data/derived/fair_value/<SYMBOL>/<run_id>.json`, including model version,
input paths, factor hashes, assumptions, model values, and warnings. The stock
page shows the estimate, model range, cost-of-equity inputs, sensitivity,
confidence, freshness, and provenance.

Every estimate is labelled low confidence. The current fundamentals capture
date is not the original filing date; analyst forecasts are unavailable; IIMA
releases can revise historical values; current factor coverage ends in
December 2025; price beta returns omit cash dividends; and the peer multiple
checks are raw medians. As a result these outputs must not be presented as
point-in-time back-test results or investor recommendations.
