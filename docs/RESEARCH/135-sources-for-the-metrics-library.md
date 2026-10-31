# 135 — Sources for the metrics library

**Date:** 2026-10-31 · **Confidence:** high where a primary page was read; medium where only an abstract or a search summary was available (marked).

## Question

What do the primary sources say each metric on the platform means, so that `docs/METRICS/` (ADR-103) can teach the models to answer correctly?

## Sources

| Source | URL | Fetched | Read |
|---|---|---|---|
| Sharpe (1994), The Sharpe Ratio, JPM 21(1) | https://web.stanford.edu/~wfsharpe/art/sr/sr.htm | 2026-10-31 | Whole article |
| Bailey, Borwein, López de Prado & Zhu, The Probability of Backtest Overfitting, J. Comp. Finance 20(4), 2017 | https://escholarship.org/uc/item/4w1110bb | 2026-10-31 | Abstract and front matter |
| Pan & Poteshman, The Information in Option Volume for Future Stock Prices (NBER w10925; RFS 2006) | https://www.nber.org/papers/w10925 | 2026-10-31 | Abstract |
| Ni, Pearson & Poteshman (2005), Stock price clustering on option expiration dates, JFE 78(1) | https://econpapers.repec.org/RePEc:eee:jfinec:v:78:y:2005:i:1:p:49-87 | 2026-10-31 | Search summary only |
| NSE, India VIX page and white paper | https://www.nseindia.com/static/products-services/indices-indiavix-index | 2026-10-31 | **Not read** (timed out); method from search summaries of the white paper |
| BSE participant-wise OI disclosures | https://bseindia.com/markets/Derivatives/DeriReports/DeriMarketDisclosures.aspx | 2026-10-31 | **Not read** (403); Client-as-residual definition from search summary |
| RiskMetrics Technical Document (1996), MSCI listing | https://www.msci.com/research-and-insights/paper/1996-riskmetrics-technical-document | 2026-10-31 | Listing only; λ = 0.94 from secondary summaries |
| Sortino & Price (1994), J. of Investing 3(3) | https://www.rdocumentation.org/packages/PerformanceAnalytics/versions/2.0.4/topics/SortinoRatio | 2026-10-31 | Formula via PerformanceAnalytics docs |
| Brinson, Hood & Beebower (1986); Brinson & Fachler (1985) | https://ryanoconnellfinance.com/brinson-attribution-model/ | 2026-10-31 | Secondary summary |
| Black (1976), The pricing of commodity contracts, JFE 3 | https://en.wikipedia.org/wiki/Black_model | 2026-10-31 | Secondary summary |
| SqueezeMetrics, Gamma Exposure (2017) | https://squeezemetrics.com/monitor/docs | 2026-10-31 | **Not read**; formula and sign convention from third-party summaries |
| Already in the repo: Bailey & López de Prado DSR, Harvey-Liu-Zhu (research 015); StockCharts breadth and High-Low, Faber, Brock et al. (research 122); participant OI explainers (research 120); costs (research 013); FII/DII (research 104, 105, 127, 128) | | | |

## Findings that changed something

1. **Our Sharpe has no risk-free rate.** Sharpe defines the ratio on differential returns against a riskless asset; `validation/statistics.sharpe_stats` uses raw returns. Recorded as A-083, T-4249.
2. **Our Sortino divides by losing days only**, not all days as Sortino & Price do. A-084, T-4251.
3. **Pan & Poteshman's put-call evidence is for buyer-opened single-stock volume**; a secondary summary says no such effect for index options. The PCR page says not to cite it for Nifty.
4. **Pinning evidence is for single stocks on expiry**, not index max pain.
5. Reading the code against the mandate (not a web source): `min_t_statistic` is in `mandate.yaml` and no code reads it. HISTORY #42, T-4250.

## Normal ranges

Computed on 2026-10-31 from data held to 2026-10-30, read-only: index history since 2015 (VIX, Nifty moves, P/E since April 2021, P/B, yield), the market-context breadth and positioning series (past year and last 60 files), the option history cache (34 sessions, 2026-09-10 to 2026-10-30: thin), and FII/DII cash since 2025-10-01 (266 days). Each page states its window.

## Not found

- NSE's own India VIX white paper and index P/E methodology were not read (A-062 still open).
- No primary definition of NSE's delivery-position file fields.
- No India-specific evidence on PCR, max pain or gamma exposure.
