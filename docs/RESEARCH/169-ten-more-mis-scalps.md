# 169 — Ten more stock scalps at Zerodha MIS size

**Question.** Operator, 2026-11-07, after research 168 (two PAPER of ten):
"yeah go ahead and research 10 more strategies". NSE cash stocks only,
intraday at 5x MIS.

**Status.** H-0121 to H-0130 pre-registered and committed before any run.
Results follow under "Results".

## Set-up

Identical to research 168 (ADR-146): research 161's 5-minute snapshots, the
most traded F&O stocks by 20-session traded value, decisions on 5-minute
closes, fills at the next minute's open, ₹5 lakh a trade, at most ten open
on ₹10 lakh of margin, flat by 15:10, 8.46 bps a round trip, 2021-11-01 to
2024-10-15. One fixed setting each.

These were written knowing research 168's results. H-0121 is H-0118 at
another hour, and H-0122 and H-0125 share H-0115's gap events; their cards say
so. With twenty scalps tried and no search correction, one or two passes
are expected from luck alone.

| Card | Idea |
|---|---|
| H-0121 | H-0118's trend pullback at 13:30 |
| H-0122 | Gap and go with the Nifty's gap |
| H-0123 | Relative strength against the Nifty at 11:00 |
| H-0124 | Tight-range break after a morning move |
| H-0125 | Gap reclaimed: trade the fill's direction |
| H-0126 | Yesterday's 2% winner that opens higher and holds |
| H-0127 | Nifty V-rebound: buy high-beta stocks |
| H-0128 | Industry breadth day: buy its laggards |
| H-0129 | Quiet-Nifty fade of a 1.5% move |
| H-0130 | Buy yesterday's 3% winner after a 1% dip |

## Results

Screen 2026-11-07 (`make mft-screen`, which also re-ran research 168's ten
with identical results), then the gate for the three with both halves net
positive. Bps a trade at ₹5 lakh; Sharpe and drawdown on ₹10 lakh of margin.

| Card | Trades a day | Gross | Net | Net Sharpe | Halves | Drawdown | Verdict |
|---|---|---|---|---|---|---|---|
| H-0121 | 3.89 | 15.41 | 6.94 | 0.839 | 0.871 / 0.807 | -23% | **PAPER** |
| H-0122 | 4.06 | 1.73 | -6.74 | -0.709 | -0.237 / -1.271 | -82% | screen fail |
| H-0123 | 1.43 | 1.48 | -6.98 | -0.459 | -0.372 / -0.684 | -46% | screen fail |
| H-0124 | 1.43 | 11.81 | 3.34 | 0.61 | 0.415 / 0.907 | -14% | **PAPER** |
| H-0125 | 4.44 | -4.09 | -12.55 | -1.139 | -1.669 / -0.757 | -95% | screen fail |
| H-0126 | 3.74 | 4.71 | -3.76 | -0.382 | -0.239 / -0.503 | -67% | screen fail |
| H-0127 | 0.19 | -76.38 | -84.81 | -1.153 | -1.175 / -1.141 | -46% | screen fail |
| H-0128 | 0.54 | 14.87 | 6.4 | 0.369 | 0.077 / 0.728 | -14% | KILL |
| H-0129 | 5.8 | -2.28 | -10.74 | -5.124 | -4.609 / -5.628 | -90% | screen fail |
| H-0130 | 2.98 | 3.45 | -5.01 | -0.557 | -0.29 / -0.792 | -54% | screen fail |

1. **Two more PAPER, no PROMOTE.** H-0121 (H-0118's pullback at 13:30) and
   H-0124 (tight-range break after a morning move). Both turn negative at 2x
   costs; H-0124 also needs its five best stocks.
2. **H-0121 is not new evidence.** It was chosen because H-0118 passed, and
   their daily returns correlate 0.57. Treat the pair as one trend-pullback
   bet seen at two hours.
3. **The four PAPER scalps are nearly uncorrelated otherwise**: H-0115 with
   the others -0.09 to -0.03, H-0124 with the others -0.05 to 0.13. An equal
   blend of the four has a daily Sharpe of 1.33 over the same window. That
   blend was chosen after seeing the results and is not a tested strategy.
4. Gap continuation is the losing side of the gap: gap-and-go (H-0122) made
   +1.7 bps gross and gap reclaimed (H-0125) -4.1, while the fade (H-0115) made
   +13.3. Quiet-day fades (H-0129) and the Nifty V-rebound (H-0127) lose
   outright.
5. H-0128 (industry-breadth laggards) KILL: 396 trades, all of its first half
   near zero, negative at 2x costs.
