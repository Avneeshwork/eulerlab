# 172 — Ten rules on non-price data: five swing, five intraday

**Question.** Operator, 2026-11-07, after the data inventory: "do 50% intraday
50% swing and remember we use other data to trade stocks/index". Signals from
option prices, participant positions, filings, results dates, India VIX and
delivery; trades in NSE cash stocks or NIFTYBEES only, at 1x.

**Status.** H-0151 to H-0160 pre-registered and committed before any run.
Results follow under "Results".

## Set-up

- **Swing (H-0151 to H-0155):** delivery (CNC) holds of 2-20 sessions, long
  only (an overnight cash short is not allowed). In at the 09:20 fill, out at
  the 15:10 fill of the exit session. Delivery charges from `costs.schedule`
  plus 2 bps a side: 26.2 bps a round trip on ₹1 lakh. Long-only rules in a
  rising market look good by default, so each result is also given as excess
  over NIFTYBEES held the same days.
- **Intraday (H-0156 to H-0160):** 09:20 to 15:10 (H-0158 from 09:30),
  ₹1 lakh a position, 12.24 bps a round trip.
- Window 2021-11-01 to 2024-10-15, research 168's snapshots and liquidity
  ranking. Screen as research 170: both halves and 2x costs net positive.

## Data checked before writing (the inventory was wrong twice)

The data inventory listed margin-trading (MTF) reports from 2023-03 and FX
"with USDINR". Opening the files: MTF has one file in 2023-03 and daily files
only from 2025-10; the short-selling report likewise (two files before
2024-12); FX has ten major pairs and no USDINR. Those ideas are dropped.
MCX crude minutes are empty before 2024-02, so an overnight-crude rule was replaced by H-0160 before any run. Participant-wise OI has 1,809 daily files from 2020-01-01; SAST and SLBM are
daily from 2021-07.

| Card | Kind | Signal data | Paper |
|---|---|---|---|
| H-0151 | swing, 1 week | stock-option ATM call-put IV spread | Cremers and Weinbaum (2010) |
| H-0152 | swing, ~3 days | results dates | Frazzini and Lamont (2007); Barber et al. (2013) |
| H-0153 | swing, 20 days | SAST promoter buys | Lakonishok and Lee (2001) |
| H-0154 | swing, 5 days, NIFTYBEES | Client net index futures | Kaniel, Saar and Titman (2008) |
| H-0155 | swing, 10 days | no-news 5% falls | Chan (2003) |
| H-0156 | intraday | Client index-futures change, contrarian | Kaniel, Saar and Titman (2008) |
| H-0157 | intraday | Pro index-futures change, followed | Indian participant studies |
| H-0158 | intraday | India VIX +5% at 09:30 | Whaley (2000); Nagel (2012) |
| H-0159 | intraday | FII index-put change | Pan and Poteshman (2006) |
| H-0160 | intraday | 3% rise on low delivery %, faded | Barber and Odean (2008); broker guidance |

Papers are cited from memory and earlier notes; none was re-fetched.

## Results

Screen 2026-11-07 (`make other-data-screen`), no trial spent; then the gate
for the two that passed. Bps a position or trade, net of costs; swing rules
also net of NIFTYBEES held the same days.

| Card | Count | Gross | Net | Net over NIFTYBEES | Net Sharpe | Halves | At 2x costs | Verdict |
|---|---|---|---|---|---|---|---|---|
| H-0151 | 1550 | 46.4 | 20.12 | -8.48 | 0.492 | 0.081 / 0.866 | -0.15 | screen fail |
| H-0152 | 819 | -23.81 | -50.0 | -48.43 | -1.014 | -1.647 / -0.451 | -1.548 | screen fail |
| H-0153 | 181 | 357.69 | 331.02 | 256.93 | 1.567 | 0.792 / 2.394 | 1.452 | **PROMOTE** |
| H-0154 | 28 | 51.27 | 24.99 | -26.28 | 0.529 | 0.849 / 0.39 | -0.027 | screen fail |
| H-0155 | 499 | 64.52 | 38.22 | -21.4 | 0.301 | -0.238 / 0.934 | 0.123 | screen fail |
| H-0156 | 910 | 11.98 | -0.27 |  | -0.007 | 1.232 / -0.791 | -0.466 | screen fail |
| H-0157 | 850 | 6.23 | -6.03 |  | -0.252 | -0.866 / 0.29 | -0.759 | screen fail |
| H-0158 | 345 | -28.97 | -41.21 |  | -1.01 | -1.629 / -0.504 | -1.294 | screen fail |
| H-0159 | 1195 | 5.09 | -7.16 |  | -0.363 | 0.203 / -0.846 | -0.979 | screen fail |
| H-0160 | 416 | 56.38 | 44.11 |  | 1.427 | 1.554 / 1.333 | 1.034 | **PROMOTE** |

1. **H-0160 PROMOTE (ledger #114, #115)**: shorting a 3% rally made on half
   the usual delivery earns 56.4 bps gross, +44.1 net, on 416 trades; every
   year positive, drawdown -3.8%, 0.64 Sharpe at 3x costs.
2. **H-0153 PROMOTE (ledger #116, #117)**: 20 days after a promoter purchase,
   +331 bps net a position, +257 over NIFTYBEES; 1.34 Sharpe at 3x costs.
3. **Both depend on today's F&O list** (`cs.universe`). Checked the same day,
   as information and not a trial: keeping only stocks that were in F&O on the
   trade date (from `stock_fo_daily.jsonl`), H-0160 keeps 183 of 416 trades
   at +8.6 bps net, and H-0153 keeps 90 of 181 positions at +152.6 bps net.
   H-0153's long book gains from hindsight (stocks that later grew into F&O);
   H-0160's short book does not obviously gain from it, but its edge is
   mostly in stocks that were small and speculative at the time. The honest
   test is every NSE stock that was liquid on the day, which needs a
   daily-bar version (T-4500).
4. The earnings-announcement premium is negative here (-23.8 bps gross before
   costs over about three sessions), the opposite of the papers.
5. The participant-OI intraday rules (H-0156, H-0157, H-0159) and the VIX
   open spike (H-0158) have no edge. H-0154 (retail short, buy NIFTYBEES)
   made money but less than holding NIFTYBEES.
