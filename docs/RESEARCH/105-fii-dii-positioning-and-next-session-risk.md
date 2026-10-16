# 105 — Does DII positioning cushion volatility after FII exposure drops?

**Date:** 2026-10-15 · **Status:** exploratory proxy test; no trade rule

## Question

Chhimwal and Bapat (2020) report that unexpected FPI selling raises volatility,
while unexpected DII flows reduce that effect. Can the same risk pattern be
seen in NSE participant-wise index-futures positioning, after allowing time
for the end-of-day report to become usable?

## What was tested

This is a fixed descriptive screen, not a replication of the paper. It uses
the 2024 NSE participant-wise index-futures OI archive and minute closes for
RELIANCE, HDFCBANK, ICICIBANK, INFY and TCS through 2024-11-30.

- An FII exposure-drop event is a negative change in FII net index-futures OI
  (long minus short) at or below the trailing 20th percentile of up to 60
  prior report-to-report changes. At least 40 prior changes are required.
- DII “absorption” is only a proxy: DII net index-futures OI increases over
  that same reporting interval. It is not DII cash buying and may include
  hedging or position transfers.
- The report is lagged by two full NSE equity sessions before classifying the
  outcome session, because historical report release timestamps are absent.
- Each stock's outcome is full-session minute realized volatility divided by
  its own trailing 20-session mean. The daily outcome is the mean ratio across
  the five stocks.

## Result

There were 44 qualifying FII exposure-drop sessions: 23 with a positive DII
net-OI change and 21 without one.

| Group | Sessions | Mean realized-volatility ratio | Median |
|---|---:|---:|---:|
| DII net-OI increase | 23 | 1.0577 | 1.0224 |
| No DII net-OI increase | 21 | 1.0701 | 0.9886 |

The mean difference is small (−0.0124 ratio points) and the medians do not
show a consistent cushion. This one-year, small-sample OI proxy test does not
establish that DII activity reduces volatility, and it gives no return edge
or entry/exit signal. Treat it as inconclusive and do not trade it.

The earlier direction screen remains negative after modeled costs: +20.54%
gross versus −3.31% net for its lagged FII OI-direction rule (Research 097).
This risk study is a different outcome and does not rescue that strategy.

## Interpretation and next data needed

FII net OI can change through new longs, short covering, new shorts, or long
unwinding; aggregate net change cannot distinguish these paths. DII net OI
also says nothing about the participant's cash-market transactions or exact
trade time. The paper uses unexpected cash-flow shocks, so its mechanism is
not measured by this adaptation.

The next useful test requires a point-in-time daily archive of official NSE
cash FII/DII totals with first-publication timestamps. To reproduce a stock
selection result, we need timestamped institution-by-stock executions or
holdings, which this free public data does not provide. For an intraday
mechanism test, participant-tagged order or trade data is required; end-of-day
OI and minute candles cannot identify institutional entry or exit times.

Reproduce the positioning and volatility screens with
`make fii-positioning-intraday`. Results are stored in
`data/derived/fii_participant_oi_stock_strategies.json`.

## Sources

- Chhimwal & Bapat (2020), [Impact of foreign and domestic investment in stock
  market volatility: Empirical evidence from India](https://doi.org/10.1080/23322039.2020.1754321).
- Jithendranathan (2026), [Trading Activity, Open Interest, and Volatility:
  Evidence from the Indian Derivatives Market](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6675000), SSRN working paper. Its abstract distinguishes trading activity from outstanding OI and reports that volatility increases align more with trading activity than persistent OI build-up. This motivates collecting participant-wise volume; the local archive currently contains OI snapshots only.
- [NSE participant-wise OI archive and FII/DII cash-flow limits](004-india-macro-data-sources.md).
