# 122 — What conditions should call a market "Downtrend" or "Narrow"

**Question.** The dashboard's Trend and Participation cards (ADR-081) used
thresholds chosen without a source: Nifty 50 against its 200-day average plus
its 3-month change, and 60/40% of stocks above their 50-day average. The
operator asked what conditions published work uses for these words, and to
plug those in.

All fetched or searched 2026-10-28.

## Sources

| # | Source | What it says |
|---|---|---|
| 1 | Faber, "A Quantitative Approach to Tactical Asset Allocation", Journal of Wealth Management (2007), SSRN 962461 (updated 2013). The SSRN page returned 403; read through summaries: https://ritholtz.com/2012/01/revisiting-quant-approach-to-tactical-asset-allocation, https://www.thinkadvisor.com/2015/09/02/most-downloaded-ssrn-paper-ever-says-you-should-be-in-cash/ | Hold when the month-end price is above its 10-month simple moving average, move out when below. Tested on US equities from 1900 and on other asset classes from 1973. Results are gross of costs. |
| 2 | Brock, Lakonishok & LeBaron, "Simple Technical Trading Rules and the Stochastic Properties of Stock Returns", Journal of Finance 47(5), 1992, 1731-1764. Abstract via https://ideas.repec.org/a/bla/jfinan/v47y1992i5p1731-64.html | Moving-average rules on the Dow 1897-1986: returns after sell signals were negative, and more volatile than after buy signals. The authors warn that "the dangers of data snooping are immense". |
| 3 | Gunasekarage & Power, "The profitability of moving average trading rules in South Asian stock markets", Emerging Markets Review 2(1), 2001, 17-33 (abstract and citing papers only) | Moving-average rules had predictive power on the Indian, Sri Lankan, Bangladeshi and Pakistani indices, 1990-2000. India's figures were not readable. |
| 4 | https://chartschool.stockcharts.com/table-of-contents/market-indicators/percent-above-moving-average (fetched) | "A bullish bias is present when the indicator is above 50%"; "The 50% threshold works best with the percent of stocks above their longer moving averages" (150 and 200-day). The 50-day share is "more volatile" and whipsaws. Above 70% overbought, below 30% oversold. |
| 5 | https://chartschool.stockcharts.com/table-of-contents/market-indicators/high-low-index (research 120 [7]) | High-Low Index = 10-day mean of highs / (highs + lows) x 100. Below 50 means more new lows than highs. |
| 6 | Zaremba et al., Economic Modelling 97 (2021) 348-364, https://econpapers.repec.org/RePEc:eee:ecmode:v:97:y:2021:i:c:p:348-364 (abstract) | Market breadth, rising minus falling stocks, predicts future market and industry returns in 64 countries, 1973-2018. |
| 7 | Bear market and correction convention (CMC Markets, AllianceBernstein glossaries, search summary) | Bear market: a fall of 20% or more from a peak. Correction: 10% to under 20%. A convention, not a tested threshold. |
| 8 | Minervini trend template (secondary: TradingView and ProRealCode scripts) | Price above the 150 and 200-day averages, 50 > 150 > 200, and the 200-day rising for at least a month. For single stocks. |

**Not found:**
- A peer-reviewed test of the 200-day rule on Nifty itself.
- An academic source for 60% or 40% above the 50-day average. Those were our own numbers.
- Any rule that *ensures* a market falls or narrows. Every source above describes conditions under which returns have been lower or more volatile on average. None of them is a guarantee.

## Checked on our own data (2016-2026)

This is description only: no forward returns were measured, and no trial was spent. It compares how often each rule changes its word, and what share of three known falls and two rallies it labels Down or Narrow.

| Trend rule | Flips a year | Covid crash Down | 2022 fall Down | 2024-26 slide Down | 2021 rally Down | Today |
|---|---|---|---|---|---|---|
| Current: vs 200-day and 3-month change | 16.1 | 93% | 56% | 37% | 0% | Down |
| Moving-average trio [8] (price < 200-day, 50 < 200, 200 falling) | 7.3 | 60% | 19% | 31% | 0% | Down |
| **Faber 10-month, month-end [1]** | **2.0** | **89%** | **61%** | **47%** | **0%** | **Down** |
| Trio or 10% off the high [7] | 12.1 | 78% | 56% | 44% | 0% | Down |

| Participation rule | Flips a year | Covid Narrow | 2022 Narrow | 2024-26 Narrow | 2021 rally Narrow | 2023 rally Broad | Today |
|---|---|---|---|---|---|---|---|
| Current: % above 50-day, 60/40 | 22.6 | 100% | 62% | 52% | 10% | 85% | Narrow |
| **% above 200-day vs 50 [4], confirmed by High-Low Index vs 50 [5]** | **10.5** | **96%** | **48%** | **47%** | **0%** | **86%** | **Narrow** |

Today (27 Oct 2026):
- Nifty 50 at 22,750 is 13.6% below its 52-week high: a correction under [7].
- 33% of stocks are above their 200-day average, and the High-Low Index is 22.

## Decision

- **Trend:** Faber's rule, as published [1]. The month-end close above the mean of the last 10 month-end closes is Uptrend; below is Downtrend.
  - It has the most testing behind it [1, 2, 3], the fewest flips here, and the best match to the known falls.
  - The cost is a word that changes only at a month's end.
  - Beside it, a daily badge uses the standard drawdown bands [7]: Correction at 10-20% below the 52-week high, Bear market at 20% or more.
- **Participation:** the share of stocks above their 200-day average against the 50% line [4], confirmed by the High-Low Index against 50 [5].
  - Both at 50 or above: Broad. Both below: Narrow. Otherwise Mixed.
  - The 50-day share stays as a tag only at StockCharts' own extremes [4]: below 30 Washed out, above 70 Stretched.
- **Published thresholds, no tuning.** No threshold was moved to fit our data. Three published trend rules were compared, though, and the one chosen also fits best here. That is a form of selection [2] warns about. The case for Faber rests on its testing elsewhere [1, 3], not on this table.

**Confidence.**
- High that these are the published conditions.
- Medium on their relevance to India: [3] is the only India-specific evidence, and it is 1990-2000.
- Low on any claim beyond description.
