# 123 — Can we get Indian intraday microstructure data for free?

**Checked:** 2026-10-29
**Question:** Can the five new microstructure strategy leads use free data or
permitted collection, or do they need a paid historical feed?

## Short answer

I found no open, free historical NSE dataset with the order-book and trader
fields needed by most of these candidates. Public daily reports and the local
minute-candle archive cannot reproduce the flow rules; the local archive also
lacks single-stock futures minute bars. NSE's conditional trial is not
available to this operator: they trade CM and apply as an individual, while the
current policy defines trial applicants as commercial entities not trading in
the requested segment. The FYERS Standard API exposes expired NSE F&O candles
at no API subscription cost, but its current terms restrict use of exchange
data for tool development or paper trading. The operator reports that FYERS
provided written permission for local storage and historical backtesting; the
approval was not independently reviewed in this workspace. An active daily
access token is still missing, so no API request has been made. Automated
scraping of NSE's website is expressly prohibited by its current terms.

Kite can stream five levels of live depth and sells real-time plus historical
candle API access, but its current terms and support guidance do not give a
clear basis for permanently storing a new depth history for this research. Ask
Zerodha for written clarification before building a recorder. Kite candles do
not contain order-level flow or historical depth.

## Candidate-by-candidate feasibility

| Candidate | Data a faithful test needs | Free or low-cost path | Verdict |
|---|---|---|---|
| Repetitive institutional half-hour continuation | Timestamped orders, buyer/seller category, and a stable trader key to identify repeat institutions over days | The published NSE schema has no stable trader identity, and this individual is ineligible for the conditional trial. | **Exact replication remains blocked** even if order files are later sourced; a custodian proxy is a different hypothesis. |
| Algorithmic-trader timing | Timestamped trades, algo flag, trade side, and price path for VWAP attribution | NSE full order/trade records have algo flags, but this individual cannot use the conditional trial; the paid historical feed is not justified for an initial screen. | **Blocked for lack of accessible authorized history.** |
| Signed order-flow imbalance | Timestamped orders/trades with price, quantity and side, plus next-price outcomes | The individual is ineligible for the NSE trial; the paid historical CM trade-only product is listed at ₹1.10 lakh/year/site, while full history is ₹12.50 lakh/year/site. | **Blocked.** Candles and daily files cannot substitute for signed flow. |
| Multi-level limit-book pressure | Timestamped order entries, modifications, cancels and trades to reconstruct the book | The individual is ineligible for the NSE trial. Kite exposes five levels prospectively, but not historical depth; its data-retention terms need written clarification. | **Blocked pending an authorized historical feed or explicit retention permission.** |
| Single-stock futures lead cash | Matched minute or tick prices for cash and the correct dated futures contract | FYERS Standard exposes expired NSE F&O candles. The operator reports written permission for this backtest and local storage. The active daily access token is missing. | **Fetch path is coded; awaiting the operator's local FYERS login.** |

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
- FYERS Standard is documented as a free API plan. Its expired-F&O endpoint
  returns one-minute candles from 2018-10-10 onward for NSE, permits up to 100
  days per request, and limits expired-F&O intraday history to ten API
  requests per day. A valid FYERS account and an individual API app are
  required. However, FYERS API Terms §11 says exchange data may not be used to
  develop charting/technical tools or for paper trading; §12 places conditions
  on creating copies of API content. Because this task is a stored strategy
  backtest, do not fetch or retain FYERS candles until FYERS confirms this
  exact internal research use in writing. The operator confirmed receiving
  that approval on 2026-10-29; the letter was not independently reviewed here.
- The public GitHub listing
  [NSE Futures Options Historical Dataset](https://github.com/djjain21/NSE-Futures-Options-F-O-Historical-Dataset-1minute-from-2015-2026)
  claims extensive data but contains no data files or license. It offers one
  sample link for January 2026 options and says full access is priced by
  inquiry. It is not an open free source. The separate
  [nse-fno-1min-data](https://github.com/voletiramu/nse-fno-1min-data) README
  describes spot-stock OHLCV, not futures contracts, so it cannot test the
  futures-leads-cash strategy.

## Decision

Do not scrape NSE pages. No data was downloaded in this check. The operator
confirmed CM-only trading and individual status, so the commercial-entity NSE
trial route is unavailable. Do not buy the ₹12.50 lakh product for this
exploratory search. The operator reports written FYERS approval for local
storage and internal historical strategy backtesting. The fetcher is ready,
but no API request has been made because an active daily access token is not
present. Run `make fyers-auth` locally, then use `make fyers-expired-fo` for
the chosen underlying and date range. The fetcher conservatively counts all
expired-F&O endpoints against the ten-request daily limit and resumes from
immutable cached responses.

With the data currently available and authorized, no candidate has a valid
P&L backtest. Existing cash minute OHLCV lacks the dated single-stock futures
leg; it cannot validate trader-flow, signed-flow or book-imbalance rules. Do
not make synthetic flow from OHLCV. Resume strategy 5 only if dated contracts
are obtained under a license that permits this research and local storage.

## Sources

| Source | URL | Fetched | Use |
|---|---|---|---|
| NSE Data Sharing & Usage Policy, free trial provisions | https://nsearchives.nseindia.com/web/sites/default/files/inline-files/NSE_Data_Sharing%26Usage_Policy.pdf | 2026-10-29 | Eligibility and up-to-six-month trial; commercial-entity applicant |
| NSE Historical Order & Trade Specification v1.19 | https://nsearchives.nseindia.com/web/mediaattachment/2026-09/NSE_Hist_Order_Trade_Data_1.19_20260902144045.pdf | 2026-10-28 | Fields, timestamps, order references, algo/client flags |
| NSE domestic data pricing, effective 2026-04-01 | https://nsearchives.nseindia.com/web/mediaattachment/2026-04/Download_Pricing_file_-_Domestic_clients_20260424122229.pdf | 2026-10-28 | Historical trade and order/trade tariffs |
| NSE paid EOD/historical data page | https://www.nseindia.com/static/market-data/eod-historical-data-subscription | 2026-10-28 | Product scope and delivery route |
| NSE Research Initiative 2.0 | https://www.nseindia.com/static/research/research-initiatives | 2026-10-28 | Non-commercial research route |
| NSE Terms of Use | https://www.nseindia.com/static/nse-terms-of-use | 2026-10-28 | Automated website collection prohibition |
| Kite WebSocket documentation | https://kite.trade/docs/connect/v3/websocket/ | 2026-10-28 | Live five-level depth |
| Kite historical candle documentation | https://kite.trade/docs/connect/v3/historical/ | 2026-10-28 | Candle fields and expired-token caveat |
| Kite Connect Terms | https://kite.trade/terms/ | 2026-10-28 | Data copying and retention terms |
| Kite Connect pricing announcement | https://kite.trade/forum/discussion/15015/revising-kite-connect-fees-from-₹2000-to-₹500-per-month | 2026-10-28 | ₹500/month data API announcement; confirm current account billing |
| FYERS API Plans and Limits | https://fyers.in/api-docs/v3/getting-started/plans-and-limits/ | 2026-10-29 | Standard plan and historical request limits |
| FYERS Expired F&O Data API | https://fyers.in/api-docs/v3/api/market-data/expired-fo-data/get-expired-fo-data/ | 2026-10-29 | Contract candles, availability and limits |
| FYERS Individual API App | https://fyers.in/api-docs/v3/getting-started/create-an-app/individual-app/ | 2026-10-29 | Individual account app requirements |
| FYERS API Terms | https://fyers.in/terms-and-conditions-api | 2026-10-29 | Restrictions on data use, copying and storage |
| FYERS individual-app login docs | https://fyers.in/api-docs/v3/api/authentication/individual-app/ | 2026-10-29 | Daily access token and user login flow |
| FYERS auth-code endpoint | https://fyers.in/api-docs/v3/api/authentication/individual-app/generate-auth-code | 2026-10-29 | Browser login and state validation |
| FYERS validate-auth-code endpoint | https://fyers.in/api-docs/v3/api/authentication/individual-app/validate-auth-code | 2026-10-29 | Auth-code exchange and token expiry |
| GitHub vendor listing | https://github.com/djjain21/NSE-Futures-Options-F-O-Historical-Dataset-1minute-from-2015-2026 | 2026-10-29 | No open data files/license; full dataset by inquiry |
| GitHub spot-candle listing | https://github.com/voletiramu/nse-fno-1min-data | 2026-10-29 | Spot underlyings, not futures contracts |

## What I could not verify

- The exact text and retention/output limits in FYERS' written approval; the
  operator confirmed it is on file, but did not attach the approval here.
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
