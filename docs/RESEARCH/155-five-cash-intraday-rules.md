# 155 — Five minute-level cash rules for NSE stocks and the Nifty, at 1x

**Question.** Operator, 2026-11-05: "research on 5 more minute level stock /
index trading strategy on indian stock market, no futures, no options only
stock trading", then "trade at 1x simply and go". Which minute-signalled rules,
traded in cash shares or NIFTYBEES without leverage, are new here and have a
source?

**Status.** Rules H-0045 to H-0049 pre-registered and committed before any
run. Results follow under "Results".

## What the earlier work says to look for

About thirty intraday rules have been screened here (research 019-111, 112,
153, 154); every one is dead after costs. Research 154 measured why: a ₹1 lakh
stock round trip costs 12.24 bps (8.24 of it charges), and the top 50 stocks
move only 20 bps in 15 minutes on average. A rule held for minutes must be
right about 80% of the time. A rule that enters on a minute signal and holds
to the close faces the same cost against a move several times larger. So four
of these five hold to 15:10, and the one true scalp trades only when the gap
is twice the cost.

## Sources, searched 2026-11-05

| Rule | Source | Read |
|---|---|---|
| H-0045 in-play ORB | Zarattini, Barbon and Aziz (2024), "A profitable day trading strategy for the U.S. equity market", [SSRN 4729284](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4729284); rules recovered in research 019 from the authors' own summary; top-20 in-play Sharpe 2.81, over 1,600% 2016-2023 ([IDEAS record](https://ideas.repec.org/p/chf/rpseri/rp2498.html)) | SSRN 403; secondary summaries. A third-party replication on index CFDs found the gross reproduced and the net zero ([mql5](https://www.mql5.com/en/blogs/post/776235)), but that test had no stock selection |
| H-0046 52-week-high break | Della Vedova, Grant and Westerholm, "Investor behavior at the 52-week high" ([AEA 2019 draft](https://topcat.aeaweb.org/conference/2019/preliminary/paper/yyd8hBtb)); Huddart, Lang and Yetman (2009), *Management Science* 55(1) ([RePEc](https://econpapers.repec.org/RePEc:inm:ormnsc:v:55:y:2009:i:1:p:16-31)); George and Hwang (2004) | Search summaries: volume spikes when price leaves its range, and returns continue; households sell heavily on the day of the high |
| H-0047, H-0048 panic reversal | Grant, Wolf and Yu (2005), *J. Banking & Finance* 29(5) ([RePEc](https://econpapers.repec.org/RePEc:eee:jbfina:v:29:y:2005:i:5:p:1311-1327)); Jagannathan et al. (2022), *J. Financial Markets* ([NBER w24098](https://www.nber.org/papers/w24098)) | Abstracts: large index moves reverse within the day, more after rises; on NSE, slow funds buy fast crashes back |
| H-0049 NIFTYBEES premium | "Pricing efficiency of Nifty BeES in bullish and bearish markets" (2011) ([record](https://www.sciencegate.app/document/10.1177/097215091101300107)); iShares premium study ([IDEAS](https://ideas.repec.org/a/pal/assmgt/v11y2010i4d10.1057_jam.2009.23.html)) | Abstracts: divergences close within about three days; returns rise with today's premium and fall with yesterday's |

**Dropped while researching:**
- *Fade the first break of a 20-day high.* The "strong one-day reversal after an
  n-day high" comes from an unattributed document on Scribd, and it is a
  next-day effect, not a same-day one. Replaced by H-0047.
- *Larry Williams' volatility breakout.* Practitioner sources only, and it is an
  opening-range rule, a dead family here (research 076).
- No 2024-2025 paper on NSE intraday anomalies was found in a fresh search.

## The rules, fixed before running

All on Kite one-minute bars, never past 2024-11-29. Stock trades are ₹1 lakh
at 1x (12.24 bps a round trip with 2 bps slippage a side); NIFTYBEES trades
are ₹10 lakh at 1x (7.99 bps). Exact settings are in each hypothesis file.

1. **H-0045 opening-range breakout on stocks in play.** Opening range
   09:16-09:20; in play = that window's volume over its 14-session mean, above
   1, top 20 a day; trade the breakout in the range's direction from 09:21,
   1.4 × daily ATR(14) stop, out at 15:10.
2. **H-0046 first intraday break of the 52-week high.** The first minute from
   09:20 above the highest high of the previous 250 sessions (not a day that
   opened above it); buy the next open, sell at 15:10.
3. **H-0047 panic-day laggards.** If the Nifty is 1% or more from the prior
   close at 12:15: among the day's 50 most-traded stocks, buy the 10 that fell
   most (or short the 10 that rose most on an up day) at 12:16, out at 15:10.
4. **H-0048 panic reversal in NIFTYBEES.** The same signal; NIFTYBEES against
   the move, 12:16 to 15:10.
5. **H-0049 NIFTYBEES premium.** Fair value = Nifty minute price × the prior
   close's NIFTYBEES/Nifty ratio; from 09:30 to 15:00, a premium of 16 bps or
   more is traded back at the next open and closed when it changes sign, or at
   15:10.

A rule is worth taking to the operator only if it is positive net in both
halves (before 2024, and 2024). Screening only: no trial spent.

## Confidence

Low to medium for H-0045 (the strongest source, never tested across NSE
stocks); low for the rest.

## Results (run 2026-11-05, after the rules were committed in `6ab607c`)

`make cash-five` → `data/derived/cash_five.json`. 416 stocks; stock window
2021-08-20 to 2024-11-29, index window from 2021-11-01. 1x. No trial spent.

| Rule | Trades | Gross a trade | Net a trade | Net Sharpe | Before 2024 / 2024 (net Sharpe) |
|---|---|---|---|---|---|
| H-0045 in-play ORB | 12,946 (904 stopped) | 6.32 bps | -5.95 bps | -1.31 | -1.04 / -1.96 |
| H-0046 52-week-high break | 4,579 | -7.02 bps | -19.30 bps | -2.35 | -1.58 / -3.81 |
| H-0047 panic-day laggards | 970 on 97 days | -21.44 bps | -33.70 bps | -2.09 | -2.21 / -1.76 |
| H-0048 panic reversal, NIFTYBEES | 97 | -10.80 bps | -18.80 bps | -1.96 | -2.02 / -1.77 |
| H-0049 NIFTYBEES premium | 538 | 4.55 bps | -3.45 bps | -1.00 | -1.08 / -0.77 |

**All five are dead**, negative net in both halves.

- **In-play ORB.** The US paper's selection does not carry over: 6.3 bps
  gross, half the cost. Choosing stocks by opening volume does not rescue the
  opening-range breakout on NSE.
- **52-week-high break.** The stock falls back after the break on the day
  (-7 bps gross), which matches Della Vedova et al.'s finding of heavy
  household selling on the day of the high, not the continuation that comes
  later.
- **Panic reversal, both forms.** On a Nifty ±1% day at 12:15, the move
  continues into the close rather than reversing: the faded stocks lost 21 bps
  gross and the faded index 11. Grant, Wolf and Yu's reversal, measured from
  large opening moves in US futures, does not appear here at midday. The
  opposite rule (follow a midday 1% move) is **not** run: choosing it now would
  be choosing on this result. If it is wanted it needs its own source,
  registration, and evidence this window cannot give (the holdout, read
  once).
- **NIFTYBEES premium.** Real but small: 4.6 bps gross against a 7.99 bps
  round trip.

With research 153 and 154, that is nine intraday cash rules screened today and
none alive after costs. The pattern holds: effects that exist (shock
reversal 7.7 bps, in-play ORB 6.3, ETF premium 4.6) are all smaller than the
round trip.

## Fewer trades: the in-play ORB filter search (H-0050)

Operator, 2026-11-05: "check we can reduce no of trades in first strategy and
make it profitable", then "first optimize then talk". Eight filters were fixed
in H-0050 (committed `3e42756` before running): top 5 or 10 a day, relative
opening volume at least 2 or 3, entry by 10:15 or any time. Chosen on
2021-08-20 to 2023-12-31 only; the chosen one alone run on 2024.
`make in-play-variants` → `data/derived/in_play_variants.json`. No minute
file opened (the H-0045 run stored every stock-day's candidate).

| Variant (2021-08 to 2023-12) | Trades | Gross a trade | Net a trade | Net Sharpe |
|---|---|---|---|---|
| top 5, volume ≥ 2×, by 10:15 | 2,095 | 6.46 | -5.81 | -0.62 |
| top 5, ≥ 2×, any time | 2,315 | 6.43 | -5.84 | -0.66 |
| top 5, ≥ 3×, by 10:15 | 2,090 | 6.41 | -5.86 | -0.62 |
| top 5, ≥ 3×, any time | 2,309 | 6.22 | -6.04 | -0.69 |
| top 10, ≥ 2×, by 10:15 | 4,204 | 7.81 | -4.46 | -0.67 |
| top 10, ≥ 2×, any time | 4,634 | 8.49 | -3.78 | -0.60 |
| top 10, ≥ 3×, by 10:15 | 4,032 | 8.93 | -3.34 | -0.49 |
| **top 10, ≥ 3×, any time (chosen)** | 4,442 | 9.48 | -2.78 | -0.43 |

**2024, the chosen variant only:** 1,802 trades, **-14.04 bps net a trade**,
net Sharpe -2.31, against a bar of 0.13 (expected best of nine worthless
variants). **Dead.**

- No filter made the rule profitable even on the data it was chosen on: the
  best kept 9.5 bps a trade, still below the 12.24 bps round trip.
- Fewer trades did not mean better trades: top 5 earned *less* a trade than
  top 10. The strongest in-play stocks are not the best breakouts here.
- The best-looking filter on 2021-2023 was the worst on 2024, the usual sign
  that the differences between variants were noise.
- H-0045 and H-0050 are closed. No further filters are tried.
