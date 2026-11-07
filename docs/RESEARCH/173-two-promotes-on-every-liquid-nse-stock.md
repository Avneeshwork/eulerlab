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

(Added after the runs.)
