# 166 — Eight more Indian day-trading rules: index futures on 15-minute bars, index-option expiry days, the F&O ban exit

**Question.** Operator, 2026-11-07: "research more on the minute level
strategies means trade taken based on 5 min, 15 min etc charts and closed at
day end. set a goal to find 5 strategies if profitable register in library
and generate report"; then "we have to work on indian market only".

**Status.** H-0099 to H-0106 pre-registered and committed before any run,
with H-0041 (research 153, screened alive, never gated) as the ninth
candidate. Results follow under "Results".

## Why these and not more stock rules

About 60 intraday rules on NSE stocks and NIFTYBEES were screened in research
071-077 and 153-164 (H-0003 to H-0098). One passed (H-0096). The bar is cost:
a ₹1 lakh cash round trip is 12.24 bps (8.24 charges, 4 slippage), and price
rules made 2-8 bps gross. A new price rule on stocks would be one more draw
from a family already searched. So this note moves to instruments that are
cheaper to trade or carry a larger edge:

| Instrument | Round trip, 2021-2024, as modelled | Data |
|---|---|---|
| Nifty / BankNifty future, ₹10 lakh | 2.35 bps charges (3.10 from 2024-10-01) + 2 bps slippage | Index minutes from 2021-11-01 as the future's price (A-115) |
| Index options, sold at the open | options charges on premium + 1 point a leg a side | F&O bhavcopy OPEN and CLOSE per contract |
| Cash stock, ₹1 lakh | 12.24 bps | Minute snapshots (research 161) |

Futures STT rose to 0.05% of the sale on 2026-04-01 (research 153), so a
futures rule's cost today is about twice its 2021-2024 cost; the results
say where that matters.

## Sources

| Rule | Source | Read |
|---|---|---|
| H-0099, H-0100 noise area | Zarattini, Aziz and Barbon, "Beat the Market", SFI 24-97, v3 2025 ([St. Gallen](https://alexandria.unisg.ch/server/api/core/bitstreams/a99aba00-f967-49b3-aceb-f544dc386e0b/content)) | In full in research 071 (2026-10). Gross Sharpe 1.58 on NIFTYBEES, about 3 bps a trade |
| H-0101 opening-range breakout | Crabel (1990), *Day Trading with Short Term Price Patterns and Opening Range Breakout*; Zarattini, Barbon and Aziz (2024), SSRN 4729284 (research 019) | Book not read; the 2024 paper's rules from research 019 |
| H-0102 gap fade | Practitioner gap-fill; Lou, Polk and Skouras (2019), *JFE* 134(1) for overnight-daytime reversal (research 159) | No study of this trigger found |
| H-0103 to H-0105 expiry straddles | As H-0041 (research 153): FlashAlpha's 0DTE study, CAIA's warning on short-premium win rates | Research 153 |
| H-0106 ban exit | Broker explainers on the ban (research 164) | No academic test found |

No new web sources were fetched for this note. The operator stopped a fetch
partway through, so the Bitcoin-intraday paper that was being read is not
used. Absence of evidence: no peer-reviewed study of intraday Nifty or
BankNifty futures rules, Indian index expiry-day straddles, or F&O ban exits
was found here or in research 153 and 164.

## The rules, fixed before running

Each card holds its rule in full. Common to all:

- One configuration each. No parameter was chosen after seeing any result of
  this note.
- Window: the minute research window, to 2024-11-30. Holdout from 2024-12-01
  is unread.
- Futures: index minutes, decisions on 15-minute closes, fills at the next
  minute's open, flat at the 15:25 open, ₹10 lakh notional.
- Options: ₹10 lakh of index notional in continuous units, as H-0041.
- Stocks: H-0096's machinery (research 164), long instead of short.

## The order of work

1. Screen all nine (no trial spent).
2. A rule that is net positive in each half of its window goes to
   `make validate` and `make gate`. Each run adds two permanent ledger
   entries. A rule that fails the screen is not gated.
3. PROMOTE or PAPER rules are registered in the strategy library.

## Results

Screens, 2026-11-07 (`make index-futures`, `make index-expiry`,
`make nse-reports-intraday ARGS=--ban-exit`). No trial spent. Per trade in
bps of notional; halves are net totals split at the window's midpoint.

| Card | Rule | Trades | Gross | Net | Net Sharpe | Halves (net bps) | Screen |
|---|---|---|---|---|---|---|---|
| H-0099 | Nifty future, noise area, 15-min | 788 | 3.90 | -0.47 | -0.21 | -374 / +6 | fail |
| H-0100 | BankNifty future, noise area, 15-min | 824 | 1.33 | -3.04 | -1.17 | -1,300 / -1,201 | fail |
| H-0101 | BankNifty future, 15-min ORB | 705 | 2.26 | -2.10 | -0.49 | -305 / -1,179 | fail |
| H-0102 | Nifty future, gap fade, 15-min | 128 | 6.46 | +2.10 | 0.38 | +361 / -92 | fail |
| H-0041 | Nifty expiry-day straddle | 303 | 8.95 | +7.12 | 0.98 | +1,169 / +987 | pass |
| H-0103 | BankNifty expiry-day straddle | 302 | 20.17 | +19.05 | 1.79 | +3,769 / +1,984 | pass |
| H-0104 | FinNifty expiry-day straddle | 151 | 4.20 | +2.64 | 0.23 | +667 / -268 | fail |
| H-0105 | Nifty straddle, session before expiry | 302 | 7.07 | +3.41 | 0.61 | +1,027 / +4 | pass |
| H-0106 | Buy on F&O ban exit | 567 | -33.58 | -45.81 | -1.69 | — (negative 2022-2024) | fail |

Futures costs were 4.37 bps a round trip (2.35-3.10 charges, 2 slippage).

1. **The noise area is real before costs and is not tradable.** On the Nifty it
   made 3.9 bps a trade, gross Sharpe 1.81, the same as NIFTYBEES in research
   071 (1.58). Futures halve the cost but do not remove it. At 2026 STT (0.05%)
   it would be further behind. T-4039 is answered: no.
2. **BankNifty breakouts are worse than the Nifty's**, not better: 1.3 and 2.3
   bps gross. The larger daily move did not make a larger edge.
3. **The gap fade** was the best futures rule net (+2.1) but negative in the
   second half on 128 trades. Dead under the screen rule.
4. **Short expiry-day straddles carry the premium on the Nifty and BankNifty**,
   not FinNifty: FinNifty's opening strikes often had no trade (52 of 203
   expiries skipped) and 2024 lost 7.9% (worst -540 bps on 2024-06-04, the
   election-result day). The three survivors are **one bet**: short
   same-day index volatility; their worst days coincide (2020-03-12).
5. **The F&O ban exit** loses 34 bps gross a trade: stocks keep falling the
   day the ban lifts. Reversing it now would be a hypothesis chosen on this
   result, so it is recorded and not traded.
6. H-0041 re-screened with this note's shared code gives 303 expiries and
   +7.12 net against research 153's 299 and +6.96: the four extra days
   (2019-08-29, 2019-09-05, 2019-09-12, 2021-05-20) are expiries that
   research 153's list from `nifty_options.jsonl` did not have, because this
   note finds expiries in each day's bhavcopy instead. Why that file lacks
   them was not checked.

Gating: see the "Gate" section below.
