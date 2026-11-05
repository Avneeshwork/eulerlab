# 156 — Five more minute-level cash rules: bursts and calendar days

**Question.** Operator, 2026-11-05: "research on other 5 strategies then",
after research 155's five rules and the H-0050 filter search all died. Cash
stocks and NIFTYBEES only, 1x, minute bars.

**Status.** H-0051 to H-0055 pre-registered and committed before any run.
Results follow under "Results".

## Where to look, after nine dead rules today

Research 153-155 found real effects that were all smaller than a round trip
(shock reversal 7.7 bps, in-play ORB 6.3, NIFTYBEES premium 4.6, against 12.24
bps for ₹1 lakh of a stock and 7.99 for ₹10 lakh of NIFTYBEES). Two ways out
remain inside the operator's limits: **rarer, bigger events** (a 3% fall in 30
minutes, not a 1% minute), and **days that published work says are different
as a whole** (turn of the month, pre-holiday, results days), held from 09:20 to
15:10 so the trade faces one round trip against a whole session's move.

## Sources, searched 2026-11-05

| Rule | Source | Read |
|---|---|---|
| H-0051, H-0055 drift burst | Christensen, Oomen and Renò (2022), "The drift burst hypothesis", *J. Econometrics* 227(2), 461-497 ([RePEc](https://econpapers.repec.org/RePEc:eee:econom:v:227:y:2022:i:2:p:461-497), [arXiv 2601.08974](https://arxiv.org/abs/2601.08974)) | Abstract: locally explosive trends, about one a week per market across equities, bonds, FX and commodities; most reverse; the reversal is stronger for **negative bursts on large volume** |
| H-0052 pre-holiday | Ariel (1990), *J. Finance*; FIIB Business Review 14(2), 2025 ([IDEAS](https://ideas.repec.org/a/sae/fbbsrw/v14y2025i2p173-183.html)): persistent pre-holiday anomaly in Indian indices; a 2002-2014 NSE/BSE study ([publishingindia](https://publishingindia.com/storage/PDFBrochures/1795.pdf)) finds none | Search summaries; the Indian evidence disagrees |
| H-0053 turn of the month | McConnell and Xu (2008), "Equity returns at the turn of the month", *Financial Analysts Journal* 64(2), 49-64 ([RePEc](https://econpapers.repec.org/RePEc:taf:ufajxx:v:64:y:2008:i:2:p:49-64)) | Abstract: the four-day turn of the month carries the month's return in 31 of 35 countries; US 0.15% a day against about zero otherwise. India's inclusion not confirmed |
| H-0054 results-day premium | Barber, De George, Lehavy and Trueman (2013), "The earnings announcement premium around the globe", *JFE* 108(1), 118-138 ([RePEc](https://econpapers.repec.org/RePEc:eee:jfinec:v:108:y:2013:i:1:p:118-138)) | Abstract: a premium in announcement periods worldwide, significant in 9 of 20 countries, driven by uncertainty before the news |

**Dropped:** ex-dividend-day trades (no corporate-action history is stored:
`data/landing/nse/corp_actions` is empty); an India VIX spike rule (it would
largely repeat H-0048's signal, already dead); pre-RBI-policy drift (about 20
events in the window).

## The rules, fixed before running

Kite one-minute bars to 2024-11-29; stocks ₹1 lakh a trade, NIFTYBEES ₹10
lakh, 1x; cash-intraday charges plus 2 bps a side. Exact settings in each
hypothesis file.

1. **H-0051 drift burst, stocks.** 09:45-14:10, a close 3% or more below the
   highest close of the previous 30 minutes, on 30-minute volume at least 3×
   the stock's 14-session norm: buy the next open, sell 15:10.
2. **H-0052 pre-holiday, NIFTYBEES.** The session before a weekday holiday:
   long 09:20 to 15:10.
3. **H-0053 turn of the month, NIFTYBEES.** The last session of the month and
   the first three of the next: long 09:20 to 15:10.
4. **H-0054 results day, stocks.** A stock whose results reach NSE that
   evening (15:30 or later): long 09:20 to 15:10.
5. **H-0055 drift burst, Nifty.** The Nifty 1% or more below its 30-minute
   high, 09:45-14:10: buy NIFTYBEES at the next open, sell 15:10.

Holidays are read from the gaps in the session calendar (A-110); results days
from NSE's disclosure times (A-111). A rule is worth taking to the operator
only if positive net in both halves (before 2024, and 2024). No trial spent.

## Confidence

Low. H-0051 has the strongest source; the calendar rules rest on close-to-close
evidence of which the intraday share is unknown.
