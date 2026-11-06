# 162 — Five more cash rules: beta, lottery stocks, the last half-hour, expiry pinning, futures build-up

**Question.** Operator, 2026-11-06: "research next 5", after research 153-161
tested forty-two minute-level intraday rules, none passing. Cash stocks at
1x, minute bars; stock futures and options may be read as signals, not traded.

**Status.** H-0083 to H-0087 pre-registered and committed before any run.
Results follow under "Results".

## What is different this time

Three rules come from papers that split returns into **day and night** and
find specific premia earned, or reversed, while the market is open. Two read
the **stock F&O bhavcopy** (daily, 2015 onward, in the landing zone), not yet
used for single stocks: option open interest by strike, and futures open
interest.

## Sources, searched 2026-11-06

| Rule | Source | Read |
|---|---|---|
| H-0083 beta by day | Hendershott, Livdan and Rösch (2020), "Asset pricing: a tale of night and day", *JFE* 138(3), 635-662 ([RePEc](https://econpapers.repec.org/RePEc:eee:jfinec:v:138:y:2020:i:3:p:635-662)) | Search abstracts: returns rise with beta overnight and fall with it during the day, in the US and internationally, for portfolios and single stocks |
| H-0084 lottery stocks by day | Bali, Cakici and Whitelaw (2011), "Maxing out", *JFE* 99(2), 427-446 ([NBER w14804](https://www.nber.org/papers/w14804.pdf)) | Abstract: the highest-MAX decile (largest daily return in the past month) underperforms the lowest by more than 1% a month. No day/night split was found |
| H-0085 illiquid stocks, last half-hour | Bogousslavsky (2021), "The cross-section of intraday and overnight returns", *JFE* 141(1), 172-194 ([RePEc](https://econpapers.repec.org/RePEc:eee:jfinec:v:141:y:2021:i:1:p:172-194)) | Abstracts: the size and illiquidity premia are realised in the last thirty minutes; arbitrageurs cut positions before the close (working-paper abstract; the published text was not read) |
| H-0086 stock option pinning | Ni, Pearson and Poteshman (2005), "Stock price clustering on option expiration dates", *JFE* 78(1), 49-87 ([IDEAS](https://ideas.repec.org/a/eee/jfinec/v78y2005i1p49-87.html)) | Abstract: optionable stocks close near strikes on expiry days, from hedge rebalancing and manipulation |
| H-0087 futures OI build-up | Indian trader practice ("long build-up": price and open interest both up). Searched for a test: none found. An NSE study (2004-05) finds price leads open interest, not the reverse ([IUP](https://www.iupindia.in/1207/Applied%20Finance/Empirical_Relationship.html)) | Absence of evidence is recorded; the rule is run because it is widely used |

**Dropped:** stock futures premium over cash as a next-day signal. No study
testing it was found; Tse and Kumar (2009, India) find futures *quotes* lead
stock prices within the day, which needs futures minute data this project
does not have.

## The rules, fixed before running

Kite minute bars of F&O stocks to 2024-11-29, reduced to research 161's
stock-day snapshots (`minute_six_parts`): 5-minute closes, next-minute fills,
the 09:20 entry, the 15:10 exit, the last close and traded value. Daily
returns are close to close; a return beyond ±20% is dropped as a likely split
or bonus (the minute closes are not adjusted). ₹1 lakh a position, 1x;
cash-intraday charges plus 2 bps a side. Deciles need 100 names a day.

1. **H-0083 beta by day.** Beta of daily returns on the Nifty's over the
   previous 60 sessions (at least 50). Buy the lowest-beta decile, short the
   highest, 09:20 to 15:10.
2. **H-0084 lottery stocks by day.** MAX = the largest daily return in the
   previous 20 sessions (at least 15). Buy the lowest decile, short the
   highest, 09:20 to 15:10.
3. **H-0085 illiquid stocks, last half-hour.** Rank on 20-session mean traded
   value. Buy the lowest decile, short the highest, 14:41 to 15:10.
4. **H-0086 stock option pinning.** On a monthly stock-option expiry day, the
   expiring series' strike with the most call-plus-put open interest at the
   prior close. At 13:00, if the stock is 1% to 3% from that strike, trade
   toward it from 13:01 to 15:10; at most ten, closest first.
5. **H-0087 futures OI build-up.** Yesterday a close-to-close return of +2% or
   more with total stock-futures open interest up 10% or more: buy today
   09:20 to 15:10; -2% or less with open interest up 10% or more: short. At
   most ten a day, largest open-interest rise first.

Judged as before: positive net in both halves (before 2024, and 2024). No
trial spent.

## Confidence

Low. H-0083 and H-0085 have the strongest sources, from US data. H-0086 has
about 40 monthly expiries. H-0087 has no academic support.

## Open questions

- Open interest jumps when a lot size changes; the 10% threshold will catch
  some of those days.
- Beta and MAX use the minute data's own closes, so the first 60 sessions
  (2021) are lost to H-0083.

## Results (run 2026-11-06, after the rules were committed in `e1aa443`)

`make stock-fo` → `data/derived/stock_fo.json`; F&O open interest for 844
sessions in `data/derived/stock_fo_daily.jsonl`. 416 stocks; 1x; no trial
spent.

| Rule | Trades | Gross a trade | Net a trade | Net Sharpe | Before 2024 / 2024 (net Sharpe) |
|---|---|---|---|---|---|
| H-0083 low beta beats high beta by day | 48,742 | 4.29 bps | -7.98 bps | -2.17 | -2.78 / -1.23 |
| H-0084 lottery stocks lose by day | 55,955 | 7.70 bps | -4.58 bps | -1.39 | -1.14 / -1.92 |
| H-0085 illiquid stocks, last half-hour | 55,854 | 0.77 bps | -11.49 bps | -17.03 | -18.30 / -14.25 |
| H-0086 stock option pinning | 378 | 1.38 bps | -10.92 bps | -1.11 | -1.11 / -1.31 |
| H-0087 futures OI build-up | 2,314 | -4.23 bps | -16.51 bps | -1.74 | -2.01 / -1.04 |

**None passes** (positive net in both halves). No year is positive for any
rule except 2021's partial months.

- **The two day-night papers have the right sign in India.** High-beta stocks
  lag low-beta ones during the day (4.3 bps a position) and last month's
  lottery stocks lag the calmest (7.7 bps). Both are smaller than the 12.24
  bps round trip, and both are paid every day on every name, so the loss is
  steady.
- **No last-half-hour illiquidity premium** among F&O stocks: 0.8 bps.
  These are all large, liquid stocks; the paper's premium is in small ones.
- **Stocks do not pin to their largest strike by 15:10** (1.4 bps over 378
  trades). Indian stock options settle on the closing price, after the exit.
- **Futures open-interest build-up reverses**: following it lost 4.2 bps
  before costs. The trader rule is wrong in sign, and too small to trade in
  reverse.
