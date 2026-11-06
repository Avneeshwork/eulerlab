# 163 — Five cash rules read from stock options: skew, call-put spread, IV changes, put-call volume, volatility spread

**Question.** Operator, 2026-11-06: "another 5 strategies", after research
153-162 tested forty-seven minute-level intraday rules, none passing. Cash
stocks at 1x; options read as signals, not traded.

**Status.** H-0088 to H-0092 pre-registered and committed before any run.
Results follow under "Results".

## What is different this time

Every rule so far found an effect of 1-17 bps a day against a 12.24 bps round
trip. The largest *daily* effects in the US literature come from single-stock
options, where informed traders act first: 40 bps the next day for the
put-call ratio, 50 bps a week for the call-put volatility spread. The NSE
F&O bhavcopy (daily, landed from 2015) carries every stock option's close,
volume and open interest, and has not been used as a signal for stocks here.

## Sources, searched 2026-11-06

| Rule | Source | Read |
|---|---|---|
| H-0088 volatility skew | Xing, Zhang and Zhao (2010), "What does the individual option volatility smirk tell us about future equity returns?", *JFQA* 45(3), 641-662 ([IDEAS](https://ideas.repec.org/a/cup/jfinqa/v45y2010i03p641-662_00.html)) | Abstract: steep smirks (OTM put IV minus ATM call IV) predict low returns for at least six months; about 15% a year long-short, weekly, before costs (secondary summary) |
| H-0089 call-put IV spread | Cremers and Weinbaum (2010), "Deviations from put-call parity and stock return predictability", *JFQA* 45(2), 335-367 ([IDEAS](https://ideas.repec.org/a/cup/jfinqa/v45y2010i02p335-367_00.html)) | Abstract: stocks with expensive calls beat those with expensive puts by about 50 bps a week; stronger where options are liquid; weaker over the sample |
| H-0090 IV changes | An, Ang, Bali and Cakici (2014), "The joint cross section of stocks and options", *J. Finance* 69(5), 2279-2337 ([NBER w19590](https://www.nber.org/papers/w19590.pdf)) | Abstract: rising call IV predicts higher returns, rising put IV lower, about 1% a month |
| H-0091 put-call volume | Pan and Poteshman (2006), "The information in option volume for future stock prices", *RFS* 19(3), 871-908 ([NBER w10925](https://www.nber.org/papers/w10925)) | Abstract: low put-call ratios beat high by over 40 bps the next day. Their ratio uses only buyer-opened volume, which NSE does not publish; the paper finds the publicly observable part much weaker |
| H-0092 volatility spread | Bali and Hovakimian (2009), "Volatility spreads and expected stock returns", *Management Science* 55(11), 1797-1812 ([RePEc](https://econpapers.repec.org/RePEc:inm:ormnsc:v:55:y:2009:i:11:p:1797-1812)) | Abstract: returns fall with realised minus implied volatility, and rise with the call-put IV spread |

## The rules, fixed before running

For each stock and session t, from the F&O bhavcopy: the nearest stock-option
expiry at least seven calendar days away. Implied volatility is Black-Scholes
(European; NSE stock options are European) from the option's close where it
traded that day, with S the stock's last cash close (research 161's
snapshots), T = calendar days to expiry / 365, r = 6.5% (A-113), no
dividends. "At the money" is the strike nearest S where both a call and a put
traded.

Each signal is formed after the close on t and traded on t+1, 09:20 to 15:10,
₹1 lakh a position, 1x, cash-intraday charges plus 2 bps a side. Deciles need
100 names a day; days with fewer are skipped.

1. **H-0088 skew.** IV of the traded put with strike/S closest to 0.95 (between
   0.90 and 0.98) minus the ATM call's IV. Short the top decile, buy the bottom.
2. **H-0089 call-put spread.** ATM call IV minus ATM put IV, same strike. Buy
   the top decile, short the bottom.
3. **H-0090 IV changes.** The change since t-1 in ATM call IV minus the change
   in ATM put IV. Buy the top decile, short the bottom.
4. **H-0091 put-call volume.** Put volume / (put + call volume) across the
   chosen expiry. Short the top decile, buy the bottom.
5. **H-0092 volatility spread.** 20-session realised volatility (close to
   close, annualised) minus the mean of the ATM call and put IVs. Short the top
   decile, buy the bottom.

Judged as before: positive net in both halves (before 2024, and 2024). No
trial spent.

## Confidence

Low to moderate. These are the largest daily effects in the literature, but
from US data in 1996-2005, and three papers say the effect has weakened. The
option close is the last trade, which may be hours before the stock's close.
About 180 stocks have options; the 100-name floor may drop days.
