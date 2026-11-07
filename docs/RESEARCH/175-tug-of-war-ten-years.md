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

(Added after the run.)
