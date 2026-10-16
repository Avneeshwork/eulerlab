# 097 — What FII/DII entry and exit tells us about Indian equities

**Date:** 2026-10-15 · **Status:** research screened; one lagged positioning adaptation tested

## Question

Can institutional entry or exit be used as a profitable intraday signal for Indian stocks?

## Findings from the literature

The best stock-level Indian evidence is Acharya, Anshuman and Kumar's NSE–NYU paper, *Foreign Fund Flows and Stock Returns: Evidence from India*. It studies daily FII trades by individual stock in 2006–2011. Stocks with unusually high FII flow innovations rose on the formation day, with much of that move persisting. Stocks with unusually low innovations fell, and part of that loss reversed over roughly the following week. The spread was larger during market stress and high global volatility. The paper's evidence is consistent with both information in FII trading and temporary price pressure from sales. This is a stock-specific daily result, not an intraday rule, and its flow series is not in our local archive.

Dhingra, Gandhi and Bulsara (2016) find that FIIs behave as positive-feedback traders when investing and negative-feedback traders when withdrawing; FII selling raises market volatility in their daily-data analysis. Chhimwal, Bapat and McMillan (2020) find unexpected FPI flow shocks increase volatility, with the effect reduced by unexpected DII flows; unexpected FPI selling has a stronger volatility effect than buying. These findings support asymmetric risk effects, not a deterministic direction call.

The results are not uniform. Naik and Padhi (2015) find that the FII-flow/volatility relation weakens after controlling for market fundamentals, while mutual-fund flows retain lagged explanatory power. Usmani, Ghayas and Shamshad (2022) report that the volatility conclusion depends on the flow measure, sample frequency and model. Krishnan and Rangan (2016) report that quarterly FII net buying is negatively related to subsequent 3- and 12-month stock returns, and stocks with no FII trading outperform their positive- and negative-flow portfolios in their sample. Entry is therefore not automatically informed buying, and exit can combine information, liquidity pressure and portfolio rebalancing.

## What is and is not testable here

- The NSE cash FII/DII endpoint in `docs/RESEARCH/004-india-macro-data-sources.md` supplies the latest daily observation only. It has no trustworthy historical date query. Its daily totals are published after the trading day, so they can only be used from the next session onward in a causal test.
- NSE participant-wise F&O OI files are a different measurement: daily outstanding positions by participant category and contract family, not cash-market buys/sells or the time of entry/exit. The manifest lists 1,750 dates (2020-01-01 through 2026-10-14). I verified the matching B2 checksum and restored 245 files covering 2023-12-01 through 2024-11-30; all 245 passed SHA-256 checks and parsed. No reports after the price cutoff were read.
- Aggregate FII/DII cash flow cannot identify which stock was bought or sold. A stock-level signal requires stock-level institutional trades. The NSE–NYU study had those data; the local archive does not.
- Daily participant positions cannot locate intraday entry/exit time. Minute price bars plus end-of-day flows do not create an intraday institutional order-flow series.

## Candidate hypotheses, not strategy claims

1. **Previous-session FII futures positioning as a broad market filter.** Use lagged changes in FII index-futures long/short positioning to filter or set the direction of an intraday stock basket; keep DII positioning separate. A fixed first test now exists below. It is an OI-position adaptation, not an FII cash-flow signal.
2. **Flow-shock reversal in stock names.** If authorized stock-level institutional trade data can be obtained with timestamps and historical coverage, rank liquid names on unexpected FII selling, then test a next-session or multi-day partial reversal. The source supports a partial reversal over days, not a one-minute fade. Do not substitute aggregate market flows for stock-level flows.
3. **DII positioning as a volatility moderator.** A first, lagged OI-proxy screen is now recorded in [Research 105](105-fii-dii-positioning-and-next-session-risk.md). Its mean volatility ratio was marginally lower with positive DII net-OI change, but its median comparison went the other way; the sample does not support a usable risk filter.

The first OI adaptation is listed in the Strategy Library with its negative result. It does not meet the five-profitable-strategy objective. Stock-level flow remains untested; the volatility-moderation OI proxy was screened in Research 105 and was inconclusive. Do not report paper effects as achievable strategy returns.

## Local positioning screen

`src/eulerlab/intraday/fii_participant_oi_screen.py` tests one frozen, exploratory rule: calculate FII net index-futures OI as long minus short; take the sign of its change between two reports; apply that direction to RELIANCE, HDFCBANK, ICICIBANK, INFY and TCS two full NSE sessions after the later report. Enter at the first traded 09:16 minute open and exit at the first traded 15:10 minute open. Allocate ₹200,000 per name from ₹1,000,000, charge date-aware NSE intraday fees, and add 2 bp assumed slippage per side. A zero change is flat. This is not the stock-level trading rule in the cited papers and does not locate FII intraday trades.

The price cutoff is 2024-11-30. The reader rejects files whose named end date crosses that cutoff. The 245 OI reports used (2023-12-01 through 2024-11-29) were restored from B2 and each checksum matched the manifest. The additional two-session delay is conservative because the historical reports do not carry a contemporaneous release timestamp.

| Measure | Result |
|---|---:|
| Evaluation sessions | 224 |
| Stock round trips | 1,120 |
| Gross return | +20.54% |
| Gross Sharpe | 1.878 |
| Net return | **−3.31%** |
| Net Sharpe | **−0.271** |
| Net maximum drawdown | −10.45% |
| Fees plus assumed slippage | ₹220,592 |

The apparent gross direction effect does not cover the modeled costs, so this is not a profitable candidate. As an exploratory split, average daily net return was +0.0117% when DII OI-change direction agreed with FII and −0.0357% when it opposed FII (110 and 114 sessions respectively). This is an unplanned, small-sample descriptive result, not a validated DII filter; it needs pre-registration and a later untouched sample before any adaptation. The broad result is the cost failure, not the post-hoc split.

Reproduce with `make fii-positioning-intraday`; results are stored in `data/derived/fii_participant_oi_stock_strategies.json` and attached to the strategy card by `make library-sync`.

## Research Library additions

Four source records are added to `research/papers/` with their scope, findings and data caveats. The FII OI adaptation is registered as a study and its result is synchronized to the Strategy Library. Research 105 adds the DII OI risk proxy and a new participant-volume working-paper lead. Remaining blockers: obtain timestamped stock-level FII trades, a historical cash-flow archive with release times, and participant-wise transaction volume for an intraday mechanism test.

## Sources

- Acharya, Anshuman & Kumar (2013), [Foreign Fund Flows and Stock Returns: Evidence from India](https://nsearchives.nseindia.com/research/content/BS1.pdf), NSE–NYU working paper.
- Krishnan & Rangan (2016), [Foreign Institutional Investor Trading and Future Returns: Evidence from an Emerging Economy](https://nsearchives.nseindia.com/research/content/nse_nyu/F_227_17_NSE_NYU_WP5.pdf), NSE–NYU working paper.
- Dhingra, Gandhi & Bulsara (2016), [Foreign institutional investments in India: An empirical analysis of dynamic interactions with stock market return and volatility](https://www.sciencedirect.com/science/article/pii/S0970389616300854), *IIMB Management Review*.
- Naik & Padhi (2015), [Interaction of Institutional Investment Activity and Stock Market Volatility: Evidence from India](https://journals.sagepub.com/doi/10.1177/2319510X15588385), *South Asian Journal of Management*.
- Chhimwal, Bapat & McMillan (2020), [Impact of foreign and domestic investment in stock market volatility: Empirical evidence from India](https://doi.org/10.1080/23322039.2020.1754321), *Cogent Economics & Finance*.
- Usmani, Ghayas & Shamshad (2022), [Foreign institutional investors and market return volatility: Evidence from symmetric and asymmetric models](https://doi.org/10.1080/09720510.2022.2079198), *Journal of Statistics and Management Systems*.
- Existing project data audit: [`004-india-macro-data-sources.md`](004-india-macro-data-sources.md).
