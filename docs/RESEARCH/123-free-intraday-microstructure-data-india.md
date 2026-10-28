# 123 — Can we get Indian intraday microstructure data for free?

**Checked:** 2026-10-28
**Question:** Can the five new microstructure strategy leads use free data or
permitted collection, or do they need a paid historical feed?

## Short answer

I found no open, free historical NSE dataset with the order-book and trader
fields needed by most of these candidates. Public daily reports and the local
minute-candle archive cannot reproduce the flow rules; the local archive also
lacks single-stock futures minute bars. NSE does offer a **conditional trial of
up to six months** of historical tick-by-tick order and trade data to prospective
or new trading clients. It requires an NSE request and a declaration that the
applicant does not currently trade in the requested market or segment; approval
is not automatic. The normal historical products are costly. Automated
scraping of NSE's website is expressly prohibited by its current terms.

Kite can stream five levels of live depth and sells real-time plus historical
candle API access, but its current terms and support guidance do not give a
clear basis for permanently storing a new depth history for this research. Ask
Zerodha for written clarification before building a recorder. Kite candles do
not contain order-level flow or historical depth.

## Candidate-by-candidate feasibility

| Candidate | Data a faithful test needs | Free or low-cost path | Verdict |
|---|---|---|---|
| Repetitive institutional half-hour continuation | Timestamped orders, buyer/seller category, and a stable trader key to identify repeat institutions over days | NSE trial may provide timestamped orders and category flags. The published product schema lists order numbers and custodian/proprietary/client category flags, but no stable trader identity. | **Exact paper replication remains blocked.** A custodian-flow proxy may be possible; it is a different hypothesis. |
| Algorithmic-trader timing | Timestamped trades, algo flag, trade side, and price path for VWAP attribution | NSE full order/trade specification includes buy/sell algo-terminal flags and buy/sell client-category flags. Trial eligibility and whether the trial includes these full-version fields must be confirmed. | **Potentially testable on a short trial sample** as a clearly labeled NSE adaptation. |
| Signed order-flow imbalance | Timestamped orders/trades with price, quantity and side, plus next-price outcomes | NSE tick-by-tick order/trade trial; paid historical CM trade-only product is listed at ₹1.10 lakh/year/site, while full historical order & trade is ₹12.50 lakh/year/site. | **Trial can support a first screen** if the relevant fields are included. Candles and daily files cannot substitute for signed flow. |
| Multi-level limit-book pressure | Timestamped order entries, modifications, cancels and trades to reconstruct the book | NSE full order/trade trial or paid full history. Kite WebSocket exposes five levels prospectively, but not historical depth; storage terms need written clarification. | **Can start only after authorized NSE trial data or written broker retention permission.** |
| Single-stock futures lead cash | Matched minute or tick prices for cash and the correct dated futures contract | Kite has historical candles for valid instrument tokens; the local archive has cash minute bars but no single-stock futures minute archive. NSE can provide CM and F&O data by trial if eligible, or separately paid. | **Best candidate for a low-cost price-only start** if old contract tokens/data can be obtained; currently missing history. |

## What the official sources say

- NSE's policy says it **may** provide up to six months of historical tick-by-
  tick order and trade data to prospective/new trading clients for strategy
  evaluation, after an NSE request and a declaration that the applicant is not
  already trading in the requested market/segment. More than six months and up
  to 12 months requires additional written approvals. This is a conditional
  trial, not an anonymous public download.
- The current NSE pricing sheet (effective 2026-04-01) lists historical trade
  data at ₹1,10,000/year/site for each of Capital Market and Futures & Options,
  and historical order & trade data at ₹12,50,000/year/site for each segment,
  excluding applicable taxes. The CM full trade schema contains buy/sell order
  references and algo/client-category flags. It does not list a stable trader
  identifier, so it cannot on its face reproduce the repeated-trader design
  from Murphy and Thirumalai.
- NSE Research Initiative 2.0 accepts data requests for research, but its page
  restricts research data to academic and non-commercial use. NSE's policy
  defines this activity as research for purposes other than trading or profit;
  that route does not fit this strategy-development objective.
- NSE website terms prohibit systematic or automated collection, including
  scraping, data mining, extraction and harvesting. Use an expressly provided
  subscription/trial delivery route instead of scraping pages or endpoints.
- Kite's official WebSocket documentation describes five bid and five offer
  depth entries. Its historical endpoint returns OHLCV candles, not historical
  order-book events. Kite Connect terms restrict scraping, database building
  and permanent copies unless expressly permitted; a current support response
  says personal analysis is allowed but permanent storage is restricted. Get
  written confirmation before retaining a live stream for replay/backtesting.

## Decision

Do not scrape NSE pages. No data was downloaded in this check. First determine
whether the operator is eligible for NSE's free trial in CM, F&O, or both. If
eligible, request a sample explicitly asking whether it includes full CM/FO
order and trade records, algo and client-category flags, and all required
historical periods; verify the response before building parsers. If not
eligible, do not buy the ₹12.50 lakh product for this exploratory search.

For a no-cost path, continue using existing minute OHLCV only for the
futures-to-cash price-lead screen if sufficient dated contracts can be sourced
under the applicable license. It cannot validate trader-flow, signed-flow or
book-imbalance rules. Do not make synthetic flow from OHLCV.

## Sources

| Source | URL | Fetched | Use |
|---|---|---|---|
| NSE Data Sharing & Usage Policy, free trial provisions | https://nsearchives.nseindia.com/web/sites/default/files/inline-files/NSE_Data_Sharing%26Usage_Policy.pdf | 2026-10-28 | Eligibility and up-to-six-month trial |
| NSE Historical Order & Trade Specification v1.19 | https://nsearchives.nseindia.com/web/mediaattachment/2026-09/NSE_Hist_Order_Trade_Data_1.19_20260902144045.pdf | 2026-10-28 | Fields, timestamps, order references, algo/client flags |
| NSE domestic data pricing, effective 2026-04-01 | https://nsearchives.nseindia.com/web/mediaattachment/2026-04/Download_Pricing_file_-_Domestic_clients_20260424122229.pdf | 2026-10-28 | Historical trade and order/trade tariffs |
| NSE paid EOD/historical data page | https://www.nseindia.com/static/market-data/eod-historical-data-subscription | 2026-10-28 | Product scope and delivery route |
| NSE Research Initiative 2.0 | https://www.nseindia.com/static/research/research-initiatives | 2026-10-28 | Non-commercial research route |
| NSE Terms of Use | https://www.nseindia.com/static/nse-terms-of-use | 2026-10-28 | Automated website collection prohibition |
| Kite WebSocket documentation | https://kite.trade/docs/connect/v3/websocket/ | 2026-10-28 | Live five-level depth |
| Kite historical candle documentation | https://kite.trade/docs/connect/v3/historical/ | 2026-10-28 | Candle fields and expired-token caveat |
| Kite Connect Terms | https://kite.trade/terms/ | 2026-10-28 | Data copying and retention terms |
| Kite Connect pricing announcement | https://kite.trade/forum/discussion/15015/revising-kite-connect-fees-from-₹2000-to-₹500-per-month | 2026-10-28 | ₹500/month data API announcement; confirm current account billing |

## What I could not verify

- Whether the NSE trial will be granted to this applicant or which segments it
  would cover.
- Whether a trial package includes the full-version CM/FO fields required for
  every rule, or only a reduced schema.
- Whether the current Kite agreement permits private, persistent storage of
  live depth for this specific research use. The public terms and support
  clarification leave a material retention question.
- Whether EulerLab's archived instrument masters preserve every expired
  single-stock futures token needed to backfill minute candles from Kite.

---

*Related strategy leads: [092 — Further Indian intraday strategy leads from
market-microstructure research](092-indian-market-microstructure-strategy-leads.md)
and [087 — Ten Indian equity intraday candidates](087-new-indian-stock-intraday-candidates.md).*
