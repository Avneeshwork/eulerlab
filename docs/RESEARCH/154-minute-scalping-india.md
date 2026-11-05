# 154 — Minute-level scalping on NSE stocks and the Nifty

**Question.** Operator, 2026-11-05: "focus on trading stock and index and
look for scalping strategies", then "we are working only up to max minute
level, no tick level". Which scalps, holding minutes, can pay for a round
trip on NSE, using one-minute bars only?

**Status.** The move map is done. Rules H-0042 and H-0043 are pre-registered
and committed before they are run. Results follow under "Results".

## Step 1 — how far things move against what a trade costs

`make move-cost-map` → `data/derived/move_cost_map.json`. Every stock with
Kite minute bars (416) and NIFTYBEES, 2021-08-20 to 2024-11-29. It is the mean
absolute close-to-close move from every traded minute, so it is what a
**perfectly informed** trade would earn before costs. The cost is a
cash-intraday round trip with 2 bps slippage a side, 14.5 bps (research 112).

| Mean absolute move, bps | 1 min | 5 min | 15 min | 30 min |
|---|---|---|---|---|
| Top 50 stocks by turnover | 5.6 | 11.9 | 20.1 | 28.0 |
| Stocks 51-150 | 6.8 | 14.1 | 23.6 | 32.8 |
| The other 266 | 8.4 | 17.0 | 27.7 | 38.2 |
| NIFTYBEES (the index) | 2.4 | 4.9 | 8.3 | 11.6 |

By half-hour, moves are largest in 09:15-09:45 (top 50, 15 minutes: 34.6
bps) and after 14:45 (21.6), smallest at midday (16-17).

What it means:
- **Index scalping cannot pay at these costs.** NIFTYBEES moves less in 30
  minutes than a round trip costs, so even a trader who knew the direction
  every time would lose. Nifty futures move like the index and cost about
  9 bps a round trip before April 2026 and about 12 after, still more than a
  15-minute move (research 153).
- **A stock scalp must be right far more often than half.** A trade right
  with probability p earns about (2p - 1) times the mean move. To clear 14.5
  bps in 15 minutes it needs p of about 86% in the top 50 and 76% in the
  least-liquid stocks; in 5 minutes, more than 100% for the top 50. The
  research finds minute-level predictability worth one or two bps.
- So a minute rule can only pay where it picks moments far more volatile than
  the average minute, and calls their direction well.

## Step 2 — sources, searched 2026-11-05

| Idea | Source | Says | Read |
|---|---|---|---|
| Fade a large move | Grant, Wolf and Yu (2005), *J. Banking & Finance* 29(5) 1311-1327 — [RePEc](https://econpapers.repec.org/RePEc:eee:jbfina:v:29:y:2005:i:5:p:1311-1327) | US index futures, 1987-2002: large opening moves reverse within the day, more after rises; much weaker after a bid-ask proxy for costs | Abstract and record |
| (support) | Fung, Mok and Lam (2000), S&P 500 and Hang Seng futures — [HKBU](https://scholars.hkbu.edu.hk/en/publications/intraday-price-reversals-for-index-futures-in-the-us-and-hong-kon/) | Opening reversals, profitable after costs "though not very significant" | Search summary |
| (India) | Jagannathan, Pelizzon, Schaumburg, Getmansky Sherman, Yuferova (2022), *J. Financial Markets* — [NBER w24098](https://www.nber.org/papers/w24098) | NSE 2006, one stock: fast crashes recovered as patient mutual funds bought | Search summary |
| Round-number crossings | Osler (2003), *J. Finance*, currency stop and take-profit orders; summarised at [ATAS](https://atas.net/market-theory/the-magic-of-round-numbers/) | Stops cluster just past round numbers, so a crossing runs; take-profits sit at them, so a touch reverses | Secondary summary only |
| Order-book imbalance | [arXiv 1707.01167](https://arxiv.org/pdf/1707.01167); [NBER w30366](https://nber.org/system/files/working_papers/w30366/w30366.pdf) | Predicts the next one or two ticks; +1 bp before a 1.5 bp fee, then a loss; predictability gone within 5 minutes | Search summaries. Needs tick data: out of scope |
| VWAP-band fade | Practitioner pages; a QuantConnect replication of Zarattini and Aziz (SSRN 4631351) | No cost-adjusted study found; the replication loses its edge at retail costs | Search summary |
| Index leads stocks | Hang Seng study, *J. Futures Markets* 35(10), 2015 — [IDEAS](https://ideas.repec.org/a/wly/jfutmk/v35y2015i10p939-952.html) | Futures lead the cash index and small stocks; depends on sampling interval | Search summary |
| Retail algo rules | SEBI 4 Feb 2025 framework, as summarised by [QuantInsti](https://blog.quantinsti.com/sebi-algo-trading-guidelines-retail-investors) | Up to 10 orders a second per exchange without registering the strategy | Not verified on sebi.gov.in |

Already dead here and not repeated: volume surge (momentum), fade at the open,
late opening range (076); momentum burst, RSI-2, Donchian, Keltner, pivots,
inside bar, engulfing, Supertrend (088-111); first half-hour momentum (071).

## The filter

| Idea | Can the edge exceed costs, by the map? | Decision |
|---|---|---|
| Fade a 1% one-minute shock on heavy volume | Possibly: it trades only very volatile minutes | **H-0042** |
| Follow a stock's first round-number crossing | Unlikely: crossings are ordinary minutes; needs 76-86% accuracy | **H-0043**, run because it costs nothing extra on the same pass; expected to fail |
| Follow the Nifty's round-number crossing in NIFTYBEES | No: perfect foresight loses | Dropped without a run (was drafted as H-0044) |
| Index leads stocks | No: a laggard's catch-up is a part of a move already below cost | Dropped |
| VWAP-band fade | No sourced rule | Dropped |
| Order-book scalps | Need ticks | Out of scope (operator, 2026-11-05) |

## The rules, fixed before running

Both on F&O stocks' one-minute bars, 2021-08-20 to 2024-11-29: enter at the
next minute's open, leave 15 minutes later or at 15:10; ₹1 lakh a trade, one
trade a stock a day, ten a day, earliest signal first; cash-intraday charges
plus 2 bps a side. `make minute-scalps` → `data/derived/minute_scalps.json`.

- **H-0042 shock fade.** From 09:45, the first minute whose close is 1% or more
  from the previous minute's, on volume at least five times the mean of the 30
  minutes before: trade against it.
- **H-0043 round-number cross.** From 09:20, the first minute whose close is on
  the other side of a multiple of ₹100 (prior close ₹1,000-10,000) or ₹10
  (₹100-1,000) from the minute before: trade with it.

A rule worth taking further must be positive net in both halves (before 2024,
and 2024). No trial is spent; neither is judged by the gate.

## Confidence

Low. The map shows how little room there is.
