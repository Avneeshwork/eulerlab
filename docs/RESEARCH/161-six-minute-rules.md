# 161 — Six more minute-level cash rules: laggards, pairs, ex-dates, VWAP

**Question.** Operator, 2026-11-06: "research more 6 intraday tests on minute
bars", after thirty-six intraday rules (research 153-160) found no effect
larger than its costs. Cash stocks at 1x, minute bars.

**Status.** H-0077 to H-0082 pre-registered and committed before any run.
Results follow under "Results".

## What is different this time

Every stock rule so far ranked a stock on its own history. Three of these
rules rank a stock against **other stocks moving at the same minute**: its
industry, the Nifty, and a matched partner. Two use **ex-dates**, which are
known weeks ahead and were not used. One is the commonest practitioner
intraday rule not yet tried here, the stretch from VWAP.

## Sources, searched 2026-11-06

| Rule | Source | Read |
|---|---|---|
| H-0077 industry laggards | Hou (2007), "Industry information diffusion and the lead-lag effect in stock returns", *RFS* 20(4), 1113-1138 ([IDEAS](https://ideas.repec.org/a/oup/rfinst/v20y2007i4p1113-1138.html)) | Search abstracts: the big-to-small lead-lag is mostly within industries; slow diffusion of industry news, stronger for bad news |
| H-0078 market-move laggards | Chordia and Swaminathan (2000), "Trading volume and cross-autocorrelations in stock returns", *J. Finance* 55(2), 913-935 ([RePEc](https://econpapers.repec.org/RePEc:bla:jfinan:v:55:y:2000:i:2:p:913-935)); Lo and MacKinlay (1990) | Abstract: high-volume portfolios lead low-volume ones at daily and weekly horizons; slower adjustment of thinly traded stocks |
| H-0079 intraday pairs | Bowen, Hutchinson and O'Sullivan (2010), "High frequency equity pairs trading: transaction costs, speed of execution and patterns in returns", *J. Trading* ([CXO summary](https://www.cxoadvisory.com/technical-trading/success-factors-for-high-frequency-pairs-trading/), fetched 2026-11-06) | FTSE 100, 2007, 60-minute bars; distance pairs, 264-hour formation, 132-hour trading; open at 2 or 3 standard deviations. 0.15% one-way friction cuts profit by more than half; a one-bar delay turns it negative; 75% of profit in the first and last hours |
| H-0080 bonus/split ex-date | Indian bonus-issue event studies via search (NSE 2004-2016: positive abnormal returns on announcement and ex-bonus days, then a fall; [core.ac.uk](https://core.ac.uk/download/234647529.pdf), 403 on fetch) | Search abstracts only; the full papers could not be fetched |
| H-0081 ex-dividend day | Ramachandran, Sanju and Nirmala (2011), "Ex-dividend day stock price behaviour: evidence from India", *Prabhandan* 1(2), 35-42 ([journal page](https://prabhandan.git.edu/index.php/ojs/article/view/21), fetched 2026-11-06) | 2005-2007: prices fall less than the dividend; significant positive abnormal return and volume on the ex-day, blamed on short-term traders |
| H-0082 VWAP stretch | Practitioner material only (e.g. [TradeZella](https://www.tradezella.com/blog/vwap-trading-strategy), StockSharp examples) | No academic test of VWAP-deviation reversion was found. Absence of evidence is recorded |

**Dropped:** Zarattini and Aziz (2023), "VWAP: the holy grail for day trading
systems" (SSRN 4631351), long above VWAP and short below on QQQ minutes. A
public reproduction ([QuantConnect](https://www.quantconnect.com/terminal/cache/embedded_backtest_b115d0894231d55994b1068202f6c0ae.html),
fetched 2026-11-06) reports the edge breaks even below about 1 bp a round trip.
NIFTYBEES costs about 8 bps. Running it would spend effort to confirm arithmetic.

## The rules, fixed before running

Kite minute bars of F&O stocks to 2024-11-29. Decisions use the close of a
completed minute and fill at the next minute's open; 09:20 entries fill at the
first open from 09:20; every exit is 15:10. ₹1 lakh a position, 1x;
cash-intraday charges plus 2 bps a side. Industry is the NSE industry in
`data/derived/company_digest.json` (A-112).

1. **H-0077 industry laggards.** At 11:15, for stocks in an industry with at
   least four members measured that day: score = the industry's mean return
   from 09:20 to 11:15 without the stock, minus the stock's own. Long the top
   decile (behind a rising industry), short the bottom decile, 11:16 to 15:10.
2. **H-0078 market-move laggards.** If the Nifty moved 0.5% or more from 09:20
   to 10:30: among the half of stocks with the lowest 20-session mean traded
   value, the ten that moved least in the Nifty's direction (own return minus
   the Nifty's, signed) are traded in the Nifty's direction, 10:31 to 15:10.
3. **H-0079 intraday pairs.** Every 20 sessions, within each industry, the 20
   pairs (across all industries) with the smallest sum of squared differences
   of normalised 15:10 prices over the previous 40 sessions. σ is the standard
   deviation of the pair's 09:20-to-15:10 spread change over those 40 sessions.
   During the next 20 sessions, on 5-minute closes from 09:25 to 14:30, the
   first time the spread since 09:20 is 2σ or more: short the stock that is
   ahead, buy the one behind, at the next minute; close when the spread
   crosses zero (next minute) or at 15:10. ₹1 lakh a leg; one trade per pair
   a day.
4. **H-0080 bonus or split ex-date.** On the ex-date of a bonus or split, buy
   at 09:20, sell at 15:10.
5. **H-0081 ex-dividend day.** On the ex-date of a dividend of 1% or more of
   the prior close, buy at 09:20, sell at 15:10.
6. **H-0082 VWAP stretch.** From 10:00 to 14:30, the first minute a stock's
   close is 1.5% or more from its session VWAP (typical price, from 09:16):
   trade toward VWAP at the next minute; exit when a close crosses VWAP (next
   minute) or at 15:10. At most ten a day, earliest first.

Event rules (H-0080, H-0081) take at most ten a day, by symbol.

Judged as before: positive net in both halves (before 2024, and 2024). No
trial spent.

## Confidence

Low. The pairs rule is the best documented and pays two round trips a trade;
its own source says costs halve it at 15 bps one way. The ex-date rules have
few events among F&O stocks. The VWAP rule has no academic support.

## Open questions

- Industries come from today's NSE classification, not the one at the time.
- Turnover in Chordia and Swaminathan is volume over shares outstanding; this
  uses traded value, which also tracks size (Lo and MacKinlay's version).

## Results (run 2026-11-06, after the rules were committed in `32b89ad`)

`make minute-six` → `data/derived/minute_six.json`. 416 stocks, 322 with an
industry; 98 sessions with a 0.5% Nifty move by 10:30; 1x; no trial spent.

| Rule | Trades | Gross a trade | Net a trade | Net Sharpe | Before 2024 / 2024 (net Sharpe) |
|---|---|---|---|---|---|
| H-0077 industry laggards | 40,587 | -1.27 bps | -13.53 bps | -8.13 | -8.07 / -8.35 |
| H-0078 market-move laggards | 980 | **16.68 bps** | **+4.42 bps** | 0.21 | **0.44 / -0.60** |
| H-0079 intraday pairs (per leg) | 4,126 | 5.87 bps | -6.40 bps | -1.71 | -0.88 / -4.04 |
| H-0080 bonus or split ex-date | 64 | 2.95 bps | -9.30 bps | -0.11 | -0.17 / 0.00 |
| H-0081 ex-dividend day | 561 | -18.16 bps | -30.40 bps | -1.96 | -1.57 / -3.34 |
| H-0082 VWAP stretch | 8,070 | 1.31 bps | -10.95 bps | -1.95 | -2.15 / -1.42 |

**None passes** (positive net in both halves).

- **Market-move laggards has the largest gross edge in research 153-161**
  (16.7 bps against a 12.24 bps round trip), but it is one year: 2022 earned
  +15.6%, and 2021, 2023 and 2024 all lost. 2022 had the most big Nifty
  mornings. Its settings are not changed.
- **Industry laggards do not catch up within the day.** The spread is -1.3 bps
  gross: stocks ahead of their industry at 11:15 stay ahead.
- **Intraday pairs converge, but not enough to pay two round trips:** 5.9 bps
  gross a leg, as Bowen et al. warned. Worse in 2024.
- **Ex-dividend stocks fall after the open**, -18 bps gross from 09:20 to
  15:10. The Indian ex-day gain (close to close) is not available intraday.
  This is an observation, not a short rule: a short would be a new hypothesis.
- **Bonus and split ex-dates** are flat after costs on 64 events.
- **VWAP stretch** reverts by 1.3 bps, a tenth of the cost.
