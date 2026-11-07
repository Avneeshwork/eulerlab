# 167 — Stock day trades on NSE's clarification queries

**Question.** Operator, 2026-11-07, after research 166: "keep 1st strategy
only and research on stocks trading". Indian stocks, cash, closed by day end.

**Status.** H-0107 to H-0110 pre-registered and committed before any run.
Results follow under "Results".

## Why these

Price-only rules on 5- and 15-minute stock charts are spent here: ORB (H-0004,
H-0045, H-0050), Keltner, Donchian, pivots, engulfing, momentum bursts, RSI(2)
(H-0014 to H-0019), NR7 and inside bars, VWAP stretch (H-0082), 52-week break
(H-0046), round numbers, shocks, drift bursts, persistence. None cleared the
12.24 bps round trip. The one stock rule that passed (H-0096) traded an
exchange action, the F&O ban. These four trade another one.

NSE asks a company to explain an unusual move ("Spurt in Volume", "Price
movement") or a news report ("News Verification") and posts the reply. In
`nse_announcements` for the 416 F&O stocks, 2021-07 to 2024-12: 445 volume
spurts, 124 price movements, 1,034 news verifications. About half are posted
in market hours.

The prior is a reversal: research 160 found that moves after intraday press
releases reverse (-29.80 bps gross for following them), and attention-driven
buying by individuals reverses (Barber and Odean 2008, *RFS* 21(2), from
memory, not fetched). No study of NSE clarification queries was found; that
absence is a finding.

## The rules, fixed before running

| Card | Event | When posted | Move faded | Trade |
|---|---|---|---|---|
| H-0107 | Spurt in Volume or Price movement | outside hours | last 3 sessions, >= 3% | next session 09:20-15:10 |
| H-0108 | News Verification | outside hours | last session, >= 2% | next session 09:20-15:10 |
| H-0109 | Spurt in Volume or Price movement | 09:20-14:30 | since previous close, >= 3% | next 5-minute close to 15:10 |
| H-0110 | News Verification | 09:20-14:30 | since previous close, >= 2% | next 5-minute close to 15:10 |

₹1 lakh a position, 1x, at most ten a day (largest move first), cash
intraday charges plus 2 bps a side, 2021-08-20 to 2024-11-29. The thresholds
were set before any run and not varied. One family: four cards, about one bet.

## Results

Screen 2026-11-07 (`make nse-queries`), no trial spent. Bps a trade.

| Card | Trades | Gross | Net | Net Sharpe | Net by year |
|---|---|---|---|---|---|
| H-0107 | 265 | -0.19 | -12.44 | -0.324 | 2021 -1.6%, 2022 -5.4%, 2023 +5.0%, 2024 -1.2% |
| H-0108 | 206 | 1.42 | -10.84 | -0.248 | 2021 -1.0%, 2022 -1.2%, 2023 +1.4%, 2024 -1.4% |
| H-0109 | 34 | -35.23 | -47.48 | -0.836 | 2021 -0.2%, 2022 -0.7%, 2023 -0.3%, 2024 -0.5% |
| H-0110 | 148 | -4.17 | -16.42 | -0.664 | 2021 +0.1%, 2022 -0.7%, 2023 -0.8%, 2024 -1.0% |

**All four are dead, and not on cost: there is no gross edge.** The moves NSE
queries neither reverse nor continue the next session on average (-0.19 and
+1.42 bps gross). Same-day fades after a reply lose (-35 and -4 bps gross):
a stock still moving when the reply lands keeps moving. Nothing here is
worth a variant; the family is closed.
