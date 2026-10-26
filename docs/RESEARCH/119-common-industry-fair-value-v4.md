# 119 — Shared Indian equity fair-value engine, version 4.1

**Date:** 2026-10-21 · **Status:** implemented, low confidence, not back-test validated

## Design decision

One valuation service, one cost-of-equity policy, one residual-income equation,
and one output schema serve every industry. Industry labels do not select a
different valuation formula or earnings adjustment. They only trigger specific
data-limit warnings where the held statements miss major value drivers.

This is a common tool, not a claim that a single equation fits every business
equally well. Residual income is an equity-value method that works from book
equity and ROE. It is suitable for banks where deposits are operating inputs
and enterprise-value DCF is a poor fit. For property developers, commodity
producers, and intangible-heavy software firms, the common model can omit
important operating or asset information; those cases carry explicit warnings.
The model does not invent a NAV, reserve value, regulatory-capital path, or
analyst forecast from missing data.

## Shared calculation

The central case starts with positive reported book value per share and held
TTM EPS. Current ROE is the TTM EPS-to-ending-BVPS proxy. Historical annual ROE
is net profit divided by average reported equity (equity capital plus
reserves). All observed ROEs are retained; the previous 1%–50% filter was
removed because it discarded both weak and unusually profitable years.

The model values equity as book value plus discounted residual income:

```text
RI_t = (ROE_t − cost_of_equity) × book_value_(t−1)
value = book_value_0 + Σ RI_t / (1 + cost_of_equity)^t + terminal_value
```

The central path fades from current TTM ROE to the median held annual ROE in
years 1–5, then to the issuer's cost of equity by year 10. With ROE equal to
the discount rate thereafter, the central terminal residual income is zero.
That avoids capitalizing a permanent competitive advantage without evidence.
It remains an assumption, not a forecast.

Where at least four annual ROEs are held, the lower case uses the historical
25th-percentile ROE as its year-5 anchor and fades to cost of equity by year
10. The upper case uses the 75th-percentile anchor. If that ROE exceeds cost
of equity, the upper case assumes excess returns persist beyond year five;
stable growth is bounded by retained earnings, the India 10-year yield, and
cost of equity. This is an optimistic persistence scenario, not a probability
or confidence interval. No cases are averaged to create the central value.

Payout uses the median of up to five reported annual dividend-payout ratios.
If those are missing, it is inferred from dividend yield, price, and EPS. If
that also fails, the model assumes full earnings retention. Sustainable
payout is capped at 100%, with a warning when observed payout is above that.

The cost of equity uses the same inputs for every issuer: current held India
10-year yield, Damodaran's 6.9202% India total ERP dated July 1, 2026, and
unshrunk issuer three-factor betas estimated on up to five years of daily
total-return stock data. IIMA SMB/HML premia use the held monthly factor file.
The former 10%–16% rate clamp and unexplained 20% beta shrink were removed.
Raw estimates are shown with their observation counts; factor data and ERP
dates are included in each result.

Peer P/E and P/B remain visible market cross-checks only. Neither a peer
multiple nor a peer median can set the headline value when the intrinsic
calculation is unavailable. A company without positive book value or usable
earnings now reports an unavailable value instead of a peer-derived estimate.

## HDFC Bank and cross-industry spot check

The latest HDFC Bank fundamentals snapshot is dated 2026-10-18. The price panel
runs through 2026-10-21; total-return adjustment factors run through
2026-08-25; the IIMA daily factor release runs through 2025-12. The table shows
the central value and the low-to-high model scenarios. These are calculations
from held data, not recommendations or validated price targets.

| Company | Industry | Price | Central | Scenario range |
| --- | --- | ---: | ---: | ---: |
| Cummins India | Capital goods | ₹4,440 | ₹496 | ₹435–₹801 |
| Godrej Properties | Realty | ₹1,564 | ₹328 | ₹315–₹364 |
| HDFC Bank | Banks | ₹707 | ₹519 | ₹487–₹1,305 |
| ICICI Bank | Banks | ₹1,385 | ₹749 | ₹727–₹1,898 |
| JSW Steel | Metals & mining | ₹1,223 | ₹354 | ₹278–₹892 |
| Linde India | Chemicals | ₹5,883 | ₹480 | ₹468–₹489 |
| L&T Finance | Finance | ₹246 | ₹82 | ₹73–₹83 |
| Pidilite Industries | Chemicals | ₹1,485 | ₹213 | ₹199–₹1,508 |
| RBL Bank | Banks | ₹359 | ₹113 | ₹110–₹122 |
| SRF | Chemicals | ₹2,305 | ₹494 | ₹465–₹1,448 |
| Tata Steel | Metals & mining | ₹172 | ₹40 | ₹33–₹46 |
| TCS | IT software | ₹2,529 | ₹1,083 | ₹1,053–₹6,014 |

For HDFC Bank, the central estimate is below the held price, while the price is
inside the upper ROE-persistence scenario. The model therefore does not support
a confident one-direction call from held data. The earlier version 2 point
value of ₹824 assumed historical ROE persisted indefinitely; version 4 shows
that assumption explicitly as an upper scenario instead of embedding it in the
central estimate.

The B2 listing held 86,752 dated fundamentals snapshots for 2,360 symbols. The
stored digest covered 2,352 symbols in 13 top-level sector groups and 40
industry labels (including Unknown). I then calculated a cross-sectional
sample of the largest and median-market-cap company in each industry label
where available: 80 companies total. All 80 latest snapshots and price series
were read. Seventy-four produced a positive residual-income value; six were
unavailable because the held inputs did not support one. The current price was
inside the model range for 17, above it for 51, and below it for 6. The central
case was below market in 67 of the 74 available cases. Nine of the 80 estimates
used the neutral beta fallback.

This sample checks that the same calculation runs across all stored industry
labels; it is not a full-market backtest or a calibration exercise. The broad
downside skew is a warning that the central path is conservative by
construction: it fades excess ROE to cost of equity by year ten, without
analyst forecasts or an empirically calibrated persistence probability. It is
not evidence that 51 stocks are objectively overvalued. The model should be
read as a low-confidence scenario range until that persistence assumption is
validated against forward outcomes.

## Known limitations

- There are no point-in-time analyst EPS forecasts or company-specific
  forward ROE projections. A growth-priced company can appear expensive under
  the central fade even when the persistence case supports a higher value.
- The ten-year fade is an explicit conservative assumption, not a fitted
  probability. The 80-company all-industry sample showed a broad central-value
  downside skew, so the central case must not be treated as an unbiased point
  forecast.
- The upper persistence scenario is intentionally not blended into the
  central value because no validation dataset supports a scenario weight.
- The IIMA factor release is through December 2025. Betas use
  dividend-reinvested closes, but factor returns and corporate-action factors
  lag the October 2026 price date; the API surfaces those dates in warnings.
- The ERP is a dated annual country-risk estimate, not a live implied premium.
  Alternative India ERP estimates differ; the cost-of-equity sensitivity is
  visible.
- Banks and other regulated financial firms need regulatory-capital,
  solvency, and risk-weighted-asset projections. Realty needs project-level
  presales, completions, and land-bank NAV. Commodity producers need a full
  cycle and forward price inputs. Software companies' internally generated
  intangibles are missing from reported book value.
- Screener snapshot time is not the original filing publication time. The
  current statement set is not suitable for historical point-in-time testing.

## Research sources

- CFA Institute, [Residual Income Valuation](https://www.cfainstitute.org/insights/professional-learning/refresher-readings/2026/residual-income-valuation)
- Damodaran, [Country Risk Premiums](https://pages.stern.nyu.edu/~adamodar/pc/datasets/ctrypremJuly26.xlsx) (July 1, 2026 update; India total ERP 6.9202%)
- Damodaran, [Financial Service Companies](https://pages.stern.nyu.edu/~adamodar/New_Home_Page/littlebook/financialsvccompanies.htm) and [Financial Service Value Drivers](https://pages.stern.nyu.edu/adamodar/New_Home_Page/littlebook/bankvaluedriver.htm)
- Damodaran, [Commodity Company Value Drivers](https://pages.stern.nyu.edu/~adamodar/New_Home_Page/littlebook/commodityvaluedrivers.htm)
- Damodaran, [Price-to-Book and ROE](https://pages.stern.nyu.edu/~adamodar/New_Home_Page/lectures/pbv.html)
