# NSE upper-circuit exhaustion: next-session intraday reversal

**Screen date:** 2026-10-15
**Disposition:** new event hypothesis; source-faithful local backtest blocked by zero events in the available universe.
**Research Library record:** `banerjee-2026-circuit-exhaustion-reversal`

## Source finding

Banerjee, “Price discovery after circuit breaker exhaustion: evidence from the
National Stock Exchange of India” ([SSRN abstract and paper link](https://ssrn.com/abstract=6621599)),
reports a study of 3,363 NSE equities using daily bhavcopy data from 2008 through
2024. The abstract identifies circuit-hit days when the day's high equals its
low. It reports that after an upper-circuit day, the next opening price
overshoots by 1.86% on average and gives back 0.23% intraday, with stronger
overshooting among liquid stocks. The abstract says clustered standard errors
and a near-miss placebo support the result.

The full SSRN PDF returned HTTP 403 during this review. The details above are
limited to the abstract; we have not verified its precise return definitions,
event filters, liquidity breakouts, or whether the reported intraday reversal is
net of any execution costs.

## Candidate rule and deduplication

Candidate adaptation: if a stock was locked at its upper circuit on session
`t`, short it after the next session's opening auction and cover before that
session ends. This attempts to capture the paper's reported same-session
reversal after the next-day opening overshoot. No overnight position is held.

This is distinct from the library's generic overnight-extreme/gap fades because
the signal requires a prior actual circuit lock. It is not a generic large-gap
proxy. The source paper also proposes a pre-open call auction; that is a market
design recommendation, not itself a trading rule.

## Local coverage audit

The historical one-minute reader was restricted to its existing 2024-11-30
cutoff; no post-cutoff bars were opened. Available pre-cutoff minute history
covers RELIANCE, HDFCBANK, ICICIBANK, INFY, TCS and GOLDBEES, from 2021-08-20
through 2024-11-29 (806 or 807 sessions per symbol). Applying the paper
abstract's literal high-equals-low event definition to each traded session
found **zero events across all six instruments**. This is a coverage/event
count audit, not a performance backtest.

The archive does not have a historical broad NSE universe or official daily
circuit-band history locally. Therefore this sample cannot test the event. Do
not infer circuit hits from generic gaps or from rounded equality in minute
bars. A source-faithful evaluation needs point-in-time eligible stock
membership, official daily upper/lower price bands or a validated locked-session
flag, and next-session minute data. It must model whether a short sale was
available after the open, use a next-observable-price fill, include date-aware
NSE charges and spread/slippage, and keep an untouched later sample.

## Decision

Keep the source as an `idea` in the Research Library, with its exact data and
paper-access blockers. No Strategy Library card, fabricated candle proxy, or
profitability claim is added. The paper's 0.23% reported reversal is a useful
test target, not evidence that a retail short can capture it after costs.
