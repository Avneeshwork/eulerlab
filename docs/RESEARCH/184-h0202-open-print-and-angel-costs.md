# 184 — Is H-0202's Sharpe of 7 real, and what does Angel One charge

**Question.** Operator, 2026-11-09: trade H-0202 and H-0194 with real money on Angel One. H-0202 screened at a net Sharpe of 7.1 (research 181), which is not believable. Does it survive research 180's open-print check? What does a small Angel intraday order cost?

**Method.** Information only, no trial. As research 180: the card's engine rule on the research window, ETFs (INF ISINs) dropped, then for trades in stocks with minute snapshots (`minute_six_parts`, F&O names) the gross move from the official open to the close against the move from the 09:20 fill to the 15:10 fill. Same for H-0194, split by side. Script in the session scratchpad, not committed (`rule_engine.card_spec`, `dm.day_book`, `minute_six_screen.PARTS`).

## Results, 2026-11-09

| Card | Trades (no ETFs) | Net bps, official prints | Minute trades | Gross from open | Gross from 09:20 | Long 09:20 | Short 09:20 |
|---|---|---|---|---|---|---|---|
| H-0202 quiet-volume gap fade | 8,386 (205 ETF trades dropped) | 128.7 | 1,154 | 85.0 | **19.2** | 8.2 | 27.0 |
| H-0194 no-news gap fade | 4,593 | 98.6 | 1,589 | — | — | 31.3 (open 106.2) | 48.0 (open 71.9) |

H-0194 net by year (official prints): 2021 +101, 2022 +102, 2023 +80, 2024 +111 bps.

**Angel One charges** ([angelone.in support, brokerage charges](https://www.angelone.in/support/charges-and-cashbacks/brokerage-charges), fetched via search 2026-11-09): equity intraday ₹20 or 0.1% per executed order, whichever is lower, minimum ₹5. Third-party pages disagree on the minimum (₹2 or ₹5); the official page says ₹5. A ₹5,000 position pays about ₹10 brokerage a round trip (20 bps), ~₹13.6 all-in.

**Angel intraday leverage.** `make angel-readonly` (2026-11-09): Angel's intraday list has 1,871 NSE names, sampled at multiplier 5.0. Available cash was ₹0.

## Findings

1. **H-0202's edge is the opening auction.** 85 bps from the open, 19 from 09:20; its long side (8 bps) loses after ~12 bps of costs. It is also the same bet as H-0194 (both fade a 3% gap). Not traded.
2. **H-0194 keeps an edge from 09:20 on both sides** (31 and 48 bps gross on F&O names), about half the backtest. Smaller stocks have no minute data here.
3. **Below ~₹20,000 a name, Angel's 0.1% brokerage takes ~20 bps a round trip**, most of what is left. Amounts under that test the plumbing, not the strategy.

**Decision.** ADR-162: H-0194 alone goes live at the operator's size.

**Confidence.** Medium for direction, low for size: F&O names only, one look at 2016-2024.

**Not found.** Whether Angel accepts API market orders without a registered static IP under SEBI's 2025 retail-algo framework (A-133).
