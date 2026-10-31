# 133 — Five Indian intraday microstructure strategies: code and data readiness

**Checked:** 2026-10-29
**Question:** Can the five sourced NSE microstructure hypotheses be coded and
backtested with data EulerLab can access without buying a high-cost archive or
scraping NSE?

## Result

The five fixed signal definitions and reusable event/quote backtest primitives
are in `src/eulerlab/intraday/microstructure_five.py`. Strategy micro-05 now
also has an FYERS-to-internal-ID normalization and a bounded, fixed-rule
backtest runner in `src/eulerlab/intraday/futures_cash_backtest.py`. **No P&L
backtest has run:** there are zero NSE historical full-order/trade files, no
FYERS expired-futures response, and no normalized microstructure input. The
readiness report records all five as `blocked_missing_data`, with
`trials_spent: 0`.

This is not evidence that the strategies lose. The required observations are
absent. I did not substitute candle volume for signed order flow or depth.

## The five fixed rules

| ID | Rule in the code | Status / caveat |
|---|---|---|
| micro-01 | Repeat the same institution's signed order submissions in a half-hour on at least two of the prior three sessions; trade the next session's same interval. | Exact source design needs a stable institution identifier. NSE's published CM order/trade layouts expose client class, order numbers and algo flags, not an institution identity. It cannot be faithfully reproduced from the offered schema. |
| micro-02 | Algo-tagged buyer minus seller notional over trailing 1- and 5-minute windows; trade when signed imbalance exceeds 20%, exit after the matching horizon. | Explicit directional adaptation. The source studies algorithmic timing/VWAP attribution; this simple directional imbalance is not its exact method. |
| micro-03 | Aggressor-signed volume imbalance over 5 minutes; trade at absolute imbalance ≥20%, exit after 1 minute. | Requires trade-side inference from order/trade records; candles do not identify the aggressor. |
| micro-04 | Inverse-level-weighted displayed size imbalance across the top 5 levels; trade at absolute pressure ≥20%, exit after 1 minute. | A fixed adaptation of deep-book predictability research. Requires replayable order-book events and executable quotes. |
| micro-05 | A stock future's completed 1-minute return leads its cash share; require positive correlation from at least 500 paired observations in the strictly prior 60 sessions, trigger at 5 bp, enter the cash share next minute and exit after 5 minutes. | Uses contract IDs and a date-valid future-to-cash mapping; contracts are not stitched across expiry. |

All equity fills in the quote replay cross the observed best bid/ask and charge
the repository's date-specific NSE intraday fee schedule. Quote replay still
assumes enough displayed size and does not model queue priority or market
impact; the code exposes slippage explicitly. The futures-led cash rule uses
next-bar open/close prices and 2 bp per-side slippage.

## Data checks

The command found **843 local Kite minute files**, all stored under cash-stock
symbols, and no future-named minute file. A non-downloading Backblaze listing
found 75 minute chunks each for RELIANCE and INFY and 82 for HDFCBANK, dated
from 2021 onward; a targeted `*FUT*` search returned zero files. The Backblaze
F&O tree contains 2,917 daily archive objects, but inspecting the local UDiFF
zip schema shows daily OHLC, volume and open-interest fields, not minute
returns. A targeted search found zero `.DAT.gz` NSE order/trade files in the
local or mirrored NSE trees.

NSE's current order/trade specification describes full order and trade events
as fixed-width records, with full orders released after 90 days and full trades
after 30 days. Trade records include buy/sell order references and the
algorithm/client-class flags; they do not identify individual institutions.
[NSE Historical Order and Trade Specification v1.19](https://nsearchives.nseindia.com/web/mediaattachment/2026-09/NSE_Hist_Order_Trade_Data_1.19_20260902144045.pdf)
(checked 2026-10-28).

NSE's conditional trial of up to six months is limited by its current policy to
commercial-entity applicants who do not trade in the requested segment. The
operator confirmed CM-only trading and individual status, so this trial route
is unavailable. **No trial request was submitted and no data was downloaded.**
Scraping NSE is not an acceptable fallback under the site's terms.

For futures-to-cash, NSE's public daily files cannot support the 1-minute rule.
The existing Kite archive supports a cash leg, but contains no stock-future
bars. FYERS Standard exposes expired F&O minute candles with ten intraday
requests per day and up to 100 days per call. Its API terms restrict
using exchange data to develop tools or for paper trading and limit copying.
The operator confirmed written permission for local storage and historical
backtesting. The app ID and secret are present in the local ignored `.env`, but
the daily access token is missing. The fetch/login command is now coded; no API
request or data download has happened yet.

## Reproduction

Run `make microstructure-five`. It inventories local files and writes
`docs/RESEARCH/133-microstructure-five-readiness.json`. It does not download,
scrape, open the holdout, or spend a hypothesis trial. The signal and replay
functions accept normalized Parquet frames keyed by EulerLab `instrument_id`;
the raw NSE files still need a point-in-time instrument-map adapter before
they can be replayed.

For the authorized futures leg, `make microstructure-five-futures` defaults to
a RELIANCE pilot: data warmup from 2026-03-01, evaluation from 2026-06-01
through 2026-08-03, which is the last date in the local instrument master.
It resumes the immutable FYERS landing, reads cash candles from the existing
Kite archive, derives a stable internal contract ID from the cash issuer ID
and expiry, then applies the fixed strategy. The signal uses each dated
contract's within-session return, the nearest expiry at each minute, positive
future-to-next-cash return correlation from the strictly prior 60 cash
sessions (at least 500 pairs), a 5 bp trigger, next-minute cash entry, and a
five-minute exit. The result and normalized Parquet go under
`data/derived/microstructure_five/micro-05/`. Raw FYERS responses are mirrored
after every fetch attempt to `nse/fyers_expired_fo/`; normalized bars and the
result are mirrored to `nse/derived/microstructure_five/micro-05/`. Both paths
verify B2 SHA-256 metadata. `make microstructure-five-b2` retries either mirror
without a fresh FYERS request. This flow has not run because the daily token is
missing.

## Decision and open question

Do not start P&L evaluation until the market data is present and the raw feed is
normalized. Candidate 1 also needs a documented stable institution key; the
published schema appears insufficient, even under a trial. The other three
order-flow/book rules can proceed only if the trial provides full CM events.
Candidate 5 needs an authorized source of dated stock-futures minute bars.

The operator confirmed they trade **CM only** and apply as an **individual**.
The current NSE trial policy specifies a commercial-entity applicant, so do
not submit an individual trial request. The operator also confirmed receiving
written FYERS permission for local storage and internal historical
backtesting. The app ID and secret are present in the ignored `.env`; the daily
access token is not. Run `make fyers-auth` locally, then run
`make microstructure-five-futures` to resume fetching and perform the pilot.
The fetcher stores immutable raw responses locally, mirrors them to B2, and
counts all expired-F&O calls against the ten-request daily budget. The operator
reports written approval;
its exact scope and retention wording has not been reviewed in this workspace.
No API request, futures download, or P&L test has happened yet.

## Sources

- NSE Data Sharing & Usage Policy (checked 2026-10-29) and historical-data
  specification (checked 2026-10-28); full source list and the
  no-scraping/data-pricing findings are in
  [132 — Free intraday microstructure data in India](132-free-intraday-microstructure-data-india.md).
- FYERS free Standard limits, expired F&O candles, and API terms, checked
  2026-10-29; see research 132. The operator reports written data-use approval.
- FYERS individual login and token endpoints, checked 2026-10-29; see research
  132. Tokens expire daily at 06:30 IST; the local auth helper does not print or
  log the token.
- Murphy and Thirumalai, repetitive institutional order flow,
  [Journal of Financial Research](https://onlinelibrary.wiley.com/doi/10.1111/jfir.12131),
  checked 2026-10-28.
- Syamala and Wadhwa, algorithmic-trader timing,
  [Research in International Business and Finance](https://doi.org/10.1016/j.ribaf.2020.101283),
  checked 2026-10-28.
- Tripathi et al., NSE order-imbalance information,
  [Finance Research Letters](https://www.sciencedirect.com/science/article/pii/S1544612320316779),
  checked 2026-10-28.
- Indian NSE limit-order-book study,
  [DOAJ record](https://doaj.org/article/f889de21e919474daf8c846021452ece),
  checked 2026-10-28.
- Indian single-stock futures lead-lag study,
  [Goa University repository record](https://irgu.unigoa.ac.in/drs/handle/unigoa/6287),
  checked 2026-10-28.
