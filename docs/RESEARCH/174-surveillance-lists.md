# 174 — NSE's surveillance and trade-for-trade lists, for shorting intraday

**Question.** Operator, 2026-11-07: "build it" (the ASM/T2T check and H-0161's
paper book). Which NSE lists bar an intraday short, where are they, and how
far back do they go?

## Sources, fetched 2026-11-07

| List | Address | What came back |
|---|---|---|
| ASM (additional surveillance) | `https://www.nseindia.com/api/reportASM` | JSON, `longterm.data` and `shortterm.data`, 191 rows; each has symbol, stage, `asmTime` (06-Nov-2026) |
| GSM (graded surveillance) | `https://www.nseindia.com/api/reportGSM` | JSON list, 76 rows; symbol, `gsmStage`, `gsmTime` |
| Securities list | `https://nsearchives.nseindia.com/content/equities/sec_list.csv` | CSV, 3,608 rows: Symbol, Series, Security Name, Band, Remarks (e.g. "GSM STAGE - 0") |
| Cash bhavcopy series (history) | already landed, `nse/cm` 2015 on | Each row's series: EQ, BE, BZ, ... |

All three snapshots now land nightly with `make nse-reports` (A-075's rule:
a moved address shows as malformed, never as a quiet gap).

## Findings

1. **ASM and GSM have no history here.** NSE's API serves today's list; no
   archive of past lists was found. Absence of evidence: none searched beyond
   the two endpoints.
2. **Trade-for-trade has history.** Series BE and BZ mark it in every cash
   bhavcopy; 219 such stocks on 2023-06-15. `make trade-for-trade` builds
   `data/derived/trade_for_trade.jsonl` from 2015.
3. Brokers block MIS on more stocks than NSE's lists (Zerodha's own list was
   not read); the paper book's fills are therefore an upper bound.

## Decision

H-0161's paper book (ADR-148) skips stocks in BE/BZ the previous session and
stocks on the latest ASM/GSM snapshot on or before the previous session, and
does not trade a day with no snapshot. H-0161's backtest is re-scored without
trade-for-trade stock-days below, as information (no new trial).

## Results

2026-11-07, information only (no trial). `trade_for_trade.jsonl` holds 2,925
days, 2015-2026. H-0161's backtest without stocks in BE/BZ on the trade day or
the day before: 9,865 of 9,867 trades remain, +34.08 bps net a trade (from
+34.11), Sharpe 2.29, halves 2.55 / 2.02, 1.47 at 2x costs; every year
unchanged to the third decimal except 2023-2024. **Trade-for-trade does not
touch the result**: the 500 most traded stocks are almost never in BE/BZ.

ASM and GSM cannot be checked historically. Today's lists (191 ASM, 76 GSM)
include some of the stocks H-0161 shorted; how many of its past trades were
on an ASM list at the time is unknown, and that is now the largest unknown
in the result (A-120 stays open). As a gauge: on 2026-11-06, 30 of the 500
most traded stocks (6%) were on the ASM or GSM list (e.g. ACUTAAS, HFCL,
EMUDHRA, ESDS). Stocks that just rallied on thin delivery are the kind NSE
puts there, so H-0161's share is likely higher than 6%. An ASM stage raises
margin (up to 100%); whether that bars an intraday short at 1x or only its
leverage was not established from NSE's own pages here.
