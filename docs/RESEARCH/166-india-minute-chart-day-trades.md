# 166 — Nine more Indian day-trading rules: index futures on 15-minute bars, index-option expiry days, the F&O ban exit

**Question.** Operator, 2026-11-07: "research more on the minute level
strategies means trade taken based on 5 min, 15 min etc charts and closed at
day end. set a goal to find 5 strategies if profitable register in library
and generate report"; then "we have to work on indian market only".

**Status.** H-0099 to H-0106 pre-registered and committed before any run,
with H-0041 (research 153, screened alive, never gated) as the tenth
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

1. Screen all ten (no trial spent).
2. A rule that is net positive in each half of its window goes to
   `make validate` and `make gate`. Each run adds two permanent ledger
   entries. A rule that fails the screen is not gated.
3. PROMOTE or PAPER rules are registered in the strategy library.

## Results

(Added after the runs.)
