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

(Added after the runs.)
