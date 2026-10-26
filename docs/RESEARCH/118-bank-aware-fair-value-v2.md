# 118 — Bank-aware multi-stage fair value model

**Date:** 2026-10-21 · **Status:** historical version 2 snapshot; superseded by [research note 119](119-common-industry-fair-value-v4.md)

The ₹824 HDFC Bank base estimate and method below are from version 2. Version
4 replaces its perpetual historical-ROE assumption with explicit persistence
scenarios and a common cost-of-equity policy; use note 119 for current method
and figures. This note remains to preserve the audit trail.

## Why v1 was replaced

The prior headline equally averaged residual income with raw peer P/E and P/B.
Those are not independent estimates: the peer multiples are market prices
applied to the subject's earnings or book value, and they ignore differences in
growth and profitability. For HDFC Bank this produced ₹487 from a ₹436
residual-income estimate and a ₹538 peer-P/B cross-check, despite the market
price being ₹707. It also faded the bank's ROE almost immediately to the peer
median.

The v2 headline uses residual income as the primary intrinsic estimate. Peer
multiples remain visible as cross-checks and do not mechanically pull the
headline down. This choice is provisional until an out-of-sample valuation and
return study can estimate defensible model weights.

## Method

Residual income is book value plus the present value of future earnings after
the equity charge. The engine now projects five years of ROE, fading from
current TTM ROE to a terminal ROE, and rolls book value forward under clean
surplus accounting. It then calculates a growing terminal residual-income
value. Terminal growth is bounded by the held India 10-year yield and the cost
of equity; the implied terminal payout is adjusted to support that growth.

The base terminal ROE is the median of the company's last five reported annual
ROEs. The bear case uses the lower of current TTM ROE and the historical 25th
percentile; the bull case uses the 75th percentile. ROE is computed as annual
net profit divided by average reported shareholders' equity. When there is not
enough company history, the peer median or current ROE supplies the anchor and
the output remains low confidence.

P/E and P/B are raw peer medians and are shown as cross-checks only. A bank's
P/B must be interpreted with ROE, growth, and the cost of equity: a low peer
median alone does not establish fair value. A full bank model should also
project regulatory capital and risk-weighted assets; those are not yet held in
the current company-page data and remain a stated limitation.

## HDFC Bank reconciliation

The held company snapshot is dated 2026-10-18; price is ₹706.95 on 2026-10-21.
It reports book value per share of ₹391 and TTM EPS of ₹52.02, with a cost of
equity of 12.08%. The last five calculated annual ROEs are 16.69%, 17.20%,
17.55%, 15.02%, and 14.30%. The scenarios therefore use 15.02%, 16.69%, and
17.20% terminal ROE, rather than substituting the peer median of 13.25% for the
company's own history.

Using the stored beta estimate and current held risk-free rate, v2 gives:

| Case or cross-check | Value per share |
| --- | ---: |
| Bear | ₹505 |
| Base | ₹824 |
| Bull | ₹875 |
| ROE-justified P/B cross-check | ₹777 |
| Raw peer P/B cross-check | ₹538 |

The base case is about 16.6% above the held market price, while the bear case
is about 28.5% below it. This is a scenario result, not evidence that the market is
mispriced. The 25th–75th percentile band does not include the higher analyst
consensus target and should not be presented as analyst consensus.

HDFC Bank's Q2 FY27 release reports Q2 NII growth of 9.7%, NIM of 3.16% on
total assets, deposit growth of 16.8%, advances-under-management growth of
14.1%, and PAT growth of 4.7% (12.6% excluding treasury gains). These support
showing recovery and margin scenarios, but do not by themselves establish a
specific long-run ROE.

## Research and limitations

- CFA Institute's residual-income framework defines equity value as book value
  plus discounted expected residual income and relates residual income to ROE
  and book value.
- Damodaran's financial-services valuation notes explain why banks cannot be
  valued with ordinary enterprise DCF in the same way as industrial companies;
  regulatory capital is part of reinvestment and bank P/B is driven by ROE,
  growth, and cost of equity.
- Damodaran's terminal-value guidance emphasizes consistency among stable
  growth, reinvestment, and excess returns. The explicit stable-growth cap and
  payout transition are intended to make those assumptions visible.
- Simply Wall St reported a ₹959.02 one-year average analyst target from 41
  analysts on 2026-10-21. This is a useful comparison point, not an input to
  the intrinsic model; analyst targets are forecasts rather than independent
  proof of fair value.

Sources:

- [CFA Institute — Residual Income Valuation](https://www.cfainstitute.org/insights/professional-learning/refresher-readings/2026/residual-income-valuation)
- [Damodaran — Financial Service Companies](https://pages.stern.nyu.edu/~adamodar/New_Home_Page/littlebook/financialsvccompanies.htm)
- [Damodaran — Financial Service Value Drivers](https://pages.stern.nyu.edu/~adamodar/New_Home_Page/littlebook/bankvaluedriver.htm)
- [Damodaran — Terminal Value](https://pages.stern.nyu.edu/~adamodar/New_Home_Page/littlebook/terminalvalue.htm)
- [HDFC Bank — Q2 FY27 Financial Results](https://www.sec.gov/Archives/edgar/data/1144967/000119312526424680/d166042dex99.htm)
- [Simply Wall St — HDFC Bank Analyst Price Targets](https://simplywall.st/stocks/in/banks/nse-hdfcbank/hdfc-bank-shares/valuation)

## Release status

This remains a low-confidence research model. The repository does not yet hold
point-in-time analyst EPS/ROE estimates, a regulatory-capital forecast, or a
walk-forward calibration of valuation weights. No parameter should be tuned
just to match one platform's price target. The next validation step is a
point-in-time cross-sectional study by sector and year, followed by a
cost-aware forward-return test as laid out in research note 117.
