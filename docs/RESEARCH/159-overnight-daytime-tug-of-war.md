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
