# 066 — What an ETF trade costs in India, and whether an ETF's open is a price

**Question.** The overnight papers (Knuteson 2020, Mukherjee 2025) buy at the
close and sell at the next open. Research 064 planned to run them on NIFTYBEES.
Two things had to be checked first: what STT an ETF unit pays, since the trade
happens every day, and whether NIFTYBEES's recorded open is a tradable price.

## Sources, fetched 2026-10-07

| Source | URL | Result |
|---|---|---|
| DSP Mutual Fund, "What is STT" (an AMC; page dated 2026-03-10) | https://www.dspim.com/knowledge-hub/personal-finance-guide/what-is-securities-transaction-tax-stt-applicability-rates-and-rules-explained | Equity-oriented fund units on a stock exchange: **purchase with delivery nil; sale with delivery 0.001%, paid by the seller; sale without delivery 0.025%**. Shares: 0.1% on each side with delivery |
| Bajaj Finserv AMC, STT explainer | https://www.bajajamc.com/knowledge-centre/securities-transaction-tax | Same: 0.001% on the sale of equity-oriented fund units, none on purchase |
| Income Tax Department, Finance (No. 2) Act 2004, section 98 | https://www.incometaxindia.gov.in/w/section-98-55 | **Not read**: 403 to the fetch tool and to curl with a browser user agent. The statute is the primary source and was not seen |

Not found: the date the fund-unit rates took effect. They are understood to
date from the Finance Act 2013, before this platform's 2016-2026 window, but
that was not verified.

## Findings

1. **The cost model charged an ETF unit the share rate.** `costs/model.py`
   applies `stt_delivery` (0.1%) to both legs of every equity-delivery trade and
   cannot tell a fund unit from a share. On an ETF the real STT is 0.001% on the
   sale only, so the model overcharges a round trip by about 0.2% of the money
   traded. For a strategy trading NIFTYBEES 2,054 times (Monday/Wednesday,
   research 064) that is most of its recorded ₹10.7 lakh of costs on ₹10 lakh
   of capital. Every result that trades an ETF through the engines is too
   pessimistic, in proportion to how often it trades. HISTORY #18, T-4003.

2. **NIFTYBEES's open is not a price to trade at.** The panel's open is the
   bhavcopy's OPEN, the day's first print. For NIFTYBEES over 2016-2026 those
   prints sit up to 20% from the previous close on days the Nifty 50 moved
   under 1% (2020-03-05: +19.6% against the index's +0.5%; 2016-11-29: -19.5%
   against +0.1%). The mean overnight "gap" was +0.78% a day on the ETF against
   +0.11% on the index, by year +1.75% a day in 2020 and +3.02% in 2021.
   Trading close-to-open on those prints turned ₹1 into ₹4 million. An ETF's
   first print can come from a stray order in a thin opening; the index's open
   is computed from its constituents' opening prices.

3. **The Nifty future is the instrument for a close-to-open test.** Its open
   is the first trade in the exchange's most-traded contract. Each day's F&O
   bhavcopy carries every Nifty future's open, high, low, close, settlement and
   open interest, and is in NSE's archive from 2015 (`market_history.
   build_nifty_futures`).

## Decision

- The overnight papers are calculated on Nifty futures, one contract per leg,
  with the futures cost model (`research/session_studies.py`), and the index
  itself reported gross beside them.
- The operator approved fixing the engines' ETF cost; it was fixed and the
  nine ETF strategies re-run the same day (T-4003, research 064).

## Confidence

High that the model charged ETFs the share rate (read in the code). Medium on
the ETF rate itself: two AMC publications agree, the statute was not read.
High that NIFTYBEES's opens are unusable for this (measured above).

## Open questions

- Do other ETFs and thinly traded stocks in the panel have the same first-print
  opens? Any builder rule using `open` on them would read noise as signal.
- From when do the fund-unit STT rates apply? Needs the statute.
