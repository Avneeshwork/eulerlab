# 159 — Five cash rules from the overnight-daytime tug of war

**Question.** Operator, 2026-11-06: "next 5 strategies", after research 153-158
(twenty-five intraday cash rules, none passing). The only rule whose gross edge
beat the round trip was H-0065, shorting stocks with strong 20-day overnight
returns in the daytime (13.9 bps gross against 12.24). The operator chose not
to gate it once it was clear it fails three gate rules. This round tests
**other, separately sourced effects from the same literature**, not variants
of H-0065's settings.

**Status.** H-0066 to H-0070 pre-registered and committed before any run.
Results follow under "Results".

## Sources, searched 2026-11-06

| Rule | Source | Read |
|---|---|---|
| H-0066, H-0068 | Lou, Polk and Skouras (2019), *JFE* 134(1) ([LSE](https://researchonline.lse.ac.uk/id/eprint/87481), [FMG DP744](https://www.fmg.ac.uk/sites/default/files/publications/DP744.pdf)) | Abstract and working paper summary: all of momentum's abnormal return is earned overnight and reverses during the day; reversal-strategy profits are also overnight; stronger for large and high-price stocks |
| H-0067, H-0070 | Akbas, Boehmer, Jiang and Koch (2022), "Overnight returns, daytime reversals, and future stock returns", *JFE* 145(3), 850-875 ([RePEc](https://econpapers.repec.org/RePEc:eee:jfinec:v:145:y:2022:i:3:p:850-875)) | Abstract and a summary: frequent positive-overnight, negative-daytime days predict higher future returns; the market-level effect is economically very small. Keiber and Luczak (2024) replicate in the US and Canada, not in five other developed markets; a China study finds no effect |
| H-0069 | Cliff, Cooper and Gulen (2008), "Return differences between trading and non-trading hours: like night and day" (US); H-0065 here | The US equity premium accrues overnight. For India only unverified online figures (Nifty intraday points negative 2000-2023) were found, no peer-reviewed study |

**Dropped:** shorting NIFTYBEES every day (the night effect itself): even the
unverified Indian figures imply about -1 bp a day intraday, against a 7.99 bps
round trip. Long-short daytime portfolios on value, profitability or low
volatility (Lou et al. place those profits intraday): annual premia of a few
percent are 1-5 bps a day, below the cost of two legs. A same-weekday
seasonality rule: Keloharju, Linnainmaa and Nyberg (2016) document monthly
seasonality; the weekday cross-section was not confirmed.

## The rules, fixed before running

Stock signals from the india-five cache (each stock-day's overnight move to
09:19 and its 09:20 and 15:10 fills); index signals from Kite Nifty minutes;
to 2024-11-29; stocks ₹1 lakh a position, NIFTYBEES ₹10 lakh, 1x; cash-intraday
charges plus 2 bps a side.

1. **H-0066 momentum daytime reversal.** Short the top decile of the 252-to-21
   session compounded return, buy the bottom, 09:20 to 15:10.
2. **H-0067 tug-of-war intensity.** Buy the top decile by count of
   overnight-up, daytime-down days in the last 20 sessions, short the bottom.
3. **H-0068 past-month winners in the daytime.** Buy the top decile of the
   20-session return, short the bottom.
4. **H-0069 Nifty overnight extremes.** The Nifty's 20-session mean overnight
   move in the top fifth of its last 250 values: short NIFTYBEES for the day;
   bottom fifth: buy.
5. **H-0070 Nifty tug of war.** A top-fifth count of overnight-up,
   daytime-down Nifty days: buy NIFTYBEES for the day.

Judged as before: positive net in both halves (before 2024, and 2024). No
trial spent.

## Confidence

Low. The stock rules rest on the one family that has shown a gross edge
larger than the cost here; the index rules have small sources.

## Results (run 2026-11-06, after the rules were committed in `85cde1b`)

`make tug-of-war` → `data/derived/tug_of_war.json`. No stock minute file
opened; 1x; no trial spent.

| Rule | Trades | Gross a trade | Net a trade | Net Sharpe | Before 2024 / 2024 (net Sharpe) |
|---|---|---|---|---|---|
| H-0066 momentum daytime reversal | 38,596 | 1.77 bps | -10.50 bps | -3.38 | -4.50 / -2.52 |
| H-0067 tug-of-war intensity | 55,677 | -9.55 bps | -21.81 bps | -10.67 | -10.66 / -10.71 |
| H-0068 past-month winners in the daytime | 55,746 | -4.64 bps | -16.91 bps | -5.80 | -6.78 / -3.95 |
| H-0069 Nifty overnight extremes, NIFTYBEES | 159 | -9.64 bps | -17.64 bps | -2.38 | -2.60 / -2.58 |
| H-0070 Nifty tug of war, NIFTYBEES | 100 | **12.08 bps** | **+4.08 bps** | **0.49** | **0.07 / 1.07** |

- **H-0070 is the first rule in research 153-159 that is positive net in both
  halves**, so it passes the screen's rule. It is weak evidence. The signal
  needs 270 sessions of history, so its first trade is in 2023: the "before
  2024" half is 2023 alone, where it made +0.24% (Sharpe 0.07, about zero), and
  almost all of its +4.0% came in 2024 (67 trades, Sharpe 1.07). One hundred
  trades over two years give a t-statistic of about 0.8 (0.49 x the square root of 2.9 years); the gate asks for 3.
  Akbas et al. call the market-level effect economically very small.
- **The stock rules are dead.** Momentum does not reverse by day here (1.8
  bps gross). The tug-of-war intensity rule lost 9.6 bps gross, the opposite
  of the US finding (and of the null found in China and five developed
  markets). Past-month winners lost 4.6 bps in the daytime.
- **Nifty overnight extremes** lost 9.6 bps gross: after a run of strong
  overnight gains, the next daytime did not give them back.

**What H-0070 needs next** (T-4469, operator): nothing here can confirm it.
Its rule is fixed; the evidence that could is new sessions: a paper book from
today, or the holdout read, which the mandate allows only after the gate, and
at t of about 0.8 it would not pass the gate.
