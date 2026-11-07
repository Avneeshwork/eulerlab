# 173 — Research 172's two PROMOTEs on every liquid NSE stock, daily bars

**Question.** HISTORY #82: the stock screens choose from today's F&O list.
Kept to stocks that were in F&O at the time, H-0160 fell from +44.1 to +8.6
bps net a trade and H-0153 from +331 to +153 bps a position. Do the two
rules hold on every NSE stock that was liquid on the day?

**Status.** H-0161 (H-0160's rule) and H-0162 (H-0153's) pre-registered and
committed before any run. Results follow under "Results".

## Set-up

- Universe each day: the 500 most traded NSE stocks by 20-session mean traded
  value (`price_panel.jsonl`, every EQ stock from 2015). Nothing about today's
  lists enters.
- Daily bars: official open and close in place of the 09:20 and 15:10 fills
  (as H-0098). An MIS short cannot reach the closing auction, so H-0161 is an
  approximation of what a 15:10 cover would get.
- Raw prices; a holding window whose day-to-day close ratio leaves 0.6-1.6 is
  dropped as a likely corporate action (A-119).
- H-0161: 2016-2024 (delivery from 2015, a year of warm-up). H-0162:
  2021-07 to 2024-11 (SAST was backfilled from 2021-07).
- Screen as research 170: both halves and 2x costs net positive.

## Results

Screen 2026-11-07 (`make daily-universe`), then the gate. No trial for the
screen; two ledger pairs for the gate (#118-#121).

| Card | Count | Net a trade | Net Sharpe | Halves | At 2x costs | Years positive | Verdict |
|---|---|---|---|---|---|---|---|
| H-0161 | 9,867 trades | +34.11 bps (46.37 gross) | 2.29 | 2.55 / 2.03 | 1.47 | 9 of 9 | **PROMOTE** |
| H-0162 | 274 positions | +394.57 bps | 1.74 | 0.97 / 2.53 | 1.62 | 4 of 4 | **PROMOTE** |

1. **The F&O-list bias was hiding these edges, not making them.** On today's
   F&O stocks (H-0160) the delivery fade made +44 bps net, on stocks in F&O
   at the time +8.6; on every liquid NSE stock it makes +34 bps over nine
   years. The effect lives in mid and small caps, which the F&O list mostly
   excludes.
2. **H-0161 is the strongest result this project has produced.** Under the
   strict bar it passes the deflated Sharpe (0.999), every stress (best five
   names removed keeps 95%) and fails only Romano-Wolf over Nifty (0.92
   against a critical 1.07). Simple mode: PROMOTE.
3. **What the backtest cannot see.** Many small speculative stocks sit in
   NSE's ASM or trade-to-trade lists, where intraday trading and shorting are
   not allowed; this project holds no history of those lists (A-120). The
   official open and close are auction prices standing in for 09:20 and 15:10
   fills. Ten ₹1 lakh shorts a day in stocks among the 500 most traded is
   small against their turnover, but slippage was not measured.
4. H-0162 (promoter buys, 20 days) is long only in a rising market; it is
   also +395 bps a position, far above holding the Nifty for 20 days.

## Every earlier stock survivor, on stocks that were in F&O at the time

Operator, 2026-11-07: "test everything we have researched till now". Each
passing stock rule of research 168-172 re-scored on only the trades in stocks
that were in F&O on the trade date (`stock_fo_daily.jsonl`). Information
only, no trial; the trades are the original book's, not a re-run book.
`data/derived/survivorship_check.json`.

| Card | Verdict | All: trades, net bps, Sharpe, 2x | In F&O then: trades, net bps, Sharpe, halves, 2x |
|---|---|---|---|
| H-0132 tug of war, 5x | PROMOTE | 7,280, +8.9, 1.44, 0.07 | 3,446, +0.6, 0.10, 0.32 / -0.22, -1.28 |
| H-0146 tug of war, gap agrees, 1x | PROMOTE | 4,802, +15.3, 1.57, 0.31 | 2,084, +3.2, 0.33, 0.92 / -0.61, -0.91 |
| H-0118 noon pullback, 5x | PAPER | 2,370, +8.8, 0.84, 0.03 | 1,125, +6.0, 0.57, 0.53 / 0.70, -0.24 |
| H-0121 pullback at 13:30, 5x | PAPER | 2,829, +6.9, 0.84, -0.19 | 1,451, +2.0, 0.25, 0.68 / -0.26, -0.84 |
| H-0115 gap fade, 5x | PAPER | 4,385, +4.8, 0.84, -0.63 | 1,765, -3.2, -0.44, -0.90 / 0.18, -1.62 |
| H-0124 tight-range break, 5x | PAPER | 1,043, +3.3, 0.61, -0.95 | 781, +1.1, 0.19, -0.36 / 0.94, -1.25 |
| H-0160 low-delivery fade | PROMOTE | 416, +44.1, 1.43, 1.03 | 183, +8.6, 0.28, 1.13 / -0.78, -0.10 |
| H-0153 promoter buys, 20 days | PROMOTE | 181, +331.0, 1.57, 1.45 | 90, +152.6, 0.66, 0.51 / 0.81, 0.56 |

**Every minute-bar survivor's edge sits mostly in stocks that joined F&O
later.** On F&O stocks of the day, only H-0118 keeps a positive Sharpe in both
halves (0.57), and none survives 2x costs. Two readings, which this check
cannot separate: hindsight (stocks that later grew into F&O), or a real
small-stock effect that the F&O list hides. Research 173's daily-bar test on
every liquid NSE stock found the second for H-0160 and H-0153. For the
minute-bar rules no such test exists here: Kite minute bars are landed only
for today's F&O stocks. Until one exists, treat H-0132, H-0146 and the four
PAPER scalps as unproven.
