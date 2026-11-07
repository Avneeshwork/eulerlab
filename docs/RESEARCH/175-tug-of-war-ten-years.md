# 175 — The tug of war (H-0132) over nine years on daily bars

**Question.** Operator, 2026-11-07: "can we backtest this for 10 years H-0132
· Tug of war at MIS size".

**Status.** H-0163 pre-registered and committed before any run. Results
follow under "Results".

## Why daily bars

Kite minute bars start 2021-08-20, so H-0132 itself cannot run before then.
On daily bars the rule needs only each stock's official open and close:
overnight = open over the previous close, held from open to close. The price
panel covers every NSE stock from 2015, so the universe is the 100 most
traded stocks of each day, not today's F&O list (HISTORY #82).

Ten years would run to 2026. Data from 2024-12-01 is the holdout; reading it
for a new card is the operator's decision (ADR-143), so this run stops at
2024-11-29: 2016-2024, nine years.

## Results

Screen 2026-11-07 (`make daily-universe ARGS=--tug-of-war`, writes
`data/derived/tug_of_war_daily_all_nse.json`). No trial spent.

| Size | Trades | Gross | Net a trade | Net Sharpe | Halves | At 2x costs | Years positive |
|---|---|---|---|---|---|---|---|
| ₹5 lakh (5x MIS, as H-0132) | 22,000 | 16.40 bps | +7.93 | 1.20 | 0.94 / 1.52 | -0.08 | 7 of 9 (2016, 2017 lost) |
| ₹1 lakh (1x) | 22,000 | 16.40 bps | +4.13 | 0.63 | 0.40 / 0.90 | -1.23 | 7 of 9 |

1. **Over nine years on every liquid NSE stock, the tug of war is real but
   thin.** 16.4 bps gross a trade, nearly all from the short leg (+33.8; the
   long leg -1.0): stocks with high recent overnight gains fall in the day.
2. **It fails the screen at both sizes**: negative at twice the costs. At 5x
   the net Sharpe is 1.20, at 1x 0.63. Not gated.
3. **H-0132's 2021-2024 result was the good stretch, not the norm**: 2016
   and 2017 lost. The F&O-list check (research 173) and this agree that the
   minute-bar PROMOTE overstated it.
4. Returns on ₹10 lakh of margin at 5x compound to large yearly figures
   (2018: +557%) that are not realistic at size; they are in the JSON for
   completeness.
