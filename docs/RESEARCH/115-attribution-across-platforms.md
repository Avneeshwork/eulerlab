# 115 — Return and risk attribution: what the platforms do, and what we build

**Question (operator, 2026-10-18).** Research how established platforms
attribute a portfolio's return and risk, and make this project's attribution
(research 114) the most detailed and informative it can be on the data held.

## What each platform contributes (sources fetched 2026-10-18)

| Platform | Idea | Source |
|---|---|---|
| pyfolio (Quantopian) | Rebuild positions from transactions; treat each round trip as a bet to tell "a few lucky trades" from "repeatable edge"; P&L by sector; top positions by peak weight; days to liquidate (shares held / daily volume) | https://nbviewer.org/github/quantopian/pyfolio/blob/master/pyfolio/examples/round_trip_tear_sheet_example.ipynb ; https://nbviewer.org/github/quantopian/pyfolio/blob/master/pyfolio/examples/sector_mappings_example.ipynb ; https://www.georgeho.org/pyfolio/ |
| Brinson-Fachler | Active return = allocation Σ(wp−wb)(Rb,i−Rb) + selection Σ wb(Rp,i−Rb,i) + interaction Σ(wp−wb)(Rp,i−Rb,i), exact in each period | https://ryanoconnellfinance.com/brinson-attribution-model/ |
| Carino linking | Single-period effects summed over many periods leave a residual; scaling each period by k_t = ln((1+Rp)/(1+Rb))/(Rp−Rb) over the whole-period K removes it | https://eagledocs.atlassian.net/wiki/x/DIBLmw |
| Returns-based factor regression (Portfolio Visualizer, R factorAnalytics) | Regress returns on factor returns; exposures, alpha, each factor's contribution = exposure × factor return; unconstrained regression (constraints can bias exposures, CEPR DP3181) | https://allaboutmoney.substack.com/p/how-to-use-portfolio-visualizer ; https://rdrr.io/github/sangeeuw/factorAnalytics/man/repReturn.html ; https://cepr.org/publications/dp3181 |
| Barra / BarraOne | Total risk split into factor and specific; contribution to risk by factor | MSCI factsheets (secondary summaries only; methodology not read) |
| Euler risk contribution | RC_i = w_i (Σw)_i / σ; contributions sum exactly to portfolio volatility | https://faculty.washington.edu/ezivot/econ424/riskbudgetingslides.pdf |
| QuantStats | Monthly return heatmap, drawdown periods, rolling metrics | https://cdn.jsdelivr.net/gh/ranaroussi/quantstats@main/README.md |

Not found or not read: MSCI's own Barra methodology (paywalled), Morningstar
and FactSet attribution documentation, Menchero's linking method.

## What is built (`src/eulerlab/attribution.py`)

1. **Positions, rebuilt.** Daily holdings from the report's fills and the
   panel's adjusted closes (pyfolio's approach), checked against the stored
   equity curve; holdings-based views are shown only when the rebuild agrees.
2. **Return decomposition.**
   - Holdings: contributions, concentration, the return without the best 1
     and 5 (research 114).
   - Brinson-Fachler by sector each month against an equal-weight benchmark of
     the point-in-time 250 most-traded stocks (the universe the strategies
     choose from), linked with Carino.
   - Four house factors built from the panel, monthly long-short equal weight
     within the same universe: market (Nifty 50), size (low minus high median
     turnover — market caps are not held), momentum (12-1 winners minus
     losers), low volatility (low minus high one-year volatility). Exposures,
     t-statistics, each factor's contribution and the alpha left over.
3. **Risk.** Euler contributions to volatility by holding and by sector, for
   the final book, from a year of daily returns.
4. **Time.** Each year's return and top contributor; best and worst months
   with the holdings that drove them; the three deepest drawdowns with the
   holdings that lost most inside each; rolling twelve-month alpha and beta.
5. **Trades.** Round trips by holding period and by sector, the share of
   profit from the best 1% of trades, win rate and payoff ratio by bucket.
6. **Capacity.** Each position's size against the stock's median daily
   turnover at entry: days to trade out at 20% of daily turnover.

## Limits stated on the page

Sector labels are today's (A-061). The size factor ranks by turnover, not
market cap. The benchmark for Brinson is equal-weight, not the Nifty's cap
weights. Factor returns are long-short and gross of costs; the strategies are
long only and net. Adjusted prices are as of today, so a report run before a
later corporate action may rebuild with a small error, which the check shows.

## Implementation review (2026-10-21)

The factor section now shows the full-window exposure (beta), spread return,
estimated contribution, Newey–West t-statistic, model fit (raw and adjusted
R²), and factor construction. Monthly regression components plus the
intercept reconcile to the strategy's annualized arithmetic monthly mean.
Calendar-year bars hold the full-period exposures fixed and use each year's
observed residual, so each year reconciles as well. The residual is a model
leftover, not proof of skill; returns are raw, with no risk-free rate.

The NSE regression uses NIFTYBEES for the market factor. It reports
Newey–West HAC standard errors with three monthly lags. U.S. reports use the
official Ken French monthly Fama/French five factors plus momentum, with the
published risk-free rate. The six-factor return model is fit to strategy
excess returns; SPY remains the separate benchmark comparison and the rolling
market model. The public files are cached locally and refreshed every 30 days.
NSE factors are never applied to U.S. reports. U.S. Brinson is withheld until
point-in-time U.S. sector weights are held.

These diagnostics are descriptive estimates. In particular, the custom size
spread uses turnover because point-in-time market capitalization is not held;
none of the house spreads is represented as a Fama–French or vendor factor.

Method sources: [Ken French Data Library](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html)
for the U.S. monthly factor files; [Fama and French (1993)](https://doi.org/10.1016/0304-405X(93)90023-5)
for the original common-risk-factor model; and [Newey and West (1987)](https://www.nber.org/papers/t0055)
for heteroskedasticity and autocorrelation consistent covariance estimates.
