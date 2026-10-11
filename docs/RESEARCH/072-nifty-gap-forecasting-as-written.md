# 072 — "Price Action Meets Volatility", coded as the paper wrote it

**Question.** Operator, 2026-10-11: "write code of this paper we have: Price
Action Meets Volatility: A Dual-Factor Strategy for Nifty Gap Forecasting". The
library held it as a calculation inside `make session-studies` (research 064),
written from a summary. What does the paper itself do, and does it hold?

## Source, fetched 2026-10-11

| Source | URL | Read |
|---|---|---|
| Mukherjee, T. & Mandal, S. (2025), "Price Action Meets Volatility: A Dual-Factor Strategy for Nifty Gap Forecasting", *International Journal for Multidisciplinary Research* 7(4), IJFMR250453859 | https://www.ijfmr.com/papers/2025/4/53859.pdf | **In full**, 12 pages |

## What the paper does

Nifty 50 daily open and close and India VIX, 3,802 days, 2010 to June 2025
(NSE, checked against Yahoo; VIX from a Kaggle dataset), in Excel.

- Candle: GREEN if close > open, RED if close < open.
- Change in VIX: **close minus open, the same day**.
- Gap: next day's open against today's close.
- Model 1, VIX only: VIX up → gap down, VIX down → gap up.
- Model 2, candle only: GREEN → gap up, RED → gap down.
- Model 3, both: GREEN and VIX down → gap up; RED and VIX up → gap down;
  everything else is "inconclusive" and left out.

It reports accuracy only: 53.1%, 52.8% and 54.4%, each called "better than
random accuracy of 50%". No trade, no costs, no test.

## What was already here, and how it differed

`session_studies.calm_rise` took the VIX change as close against the
**previous close**, covered only the joint model, and traded only its long
side. The two VIX definitions agree on 2,868 of 2,874 days here, because NSE's
VIX open is nearly always the previous close (mean difference 0.05%). So
research 064's figures stand; the definition was different from the paper's
and nobody had checked.

## Code

`research/gap_forecast.py` (`predict`, `tables`, `trade`), `make gap-forecast`,
`tests/test_gap_forecast.py`. Nifty 50 and India VIX from `index_history.jsonl`,
2015-01-01 to 2026-10-09 (2,895 days; the paper's first five years are not
held). The trade uses the near-month Nifty future, close to next open, with
the platform's futures costs on every night held.

## Results

**The paper's tables reproduce.** To June 2025, 2,578 days:

| Signal | Days | Right | Rate | Paper | Any day | Lift | z |
|---|---|---|---|---|---|---|---|
| VIX up → gap down | 1,215 | 408 | 33.6% | 36.5% | 31.3% | +2.2 | 2.31 |
| VIX down → gap up | 1,361 | 962 | 70.7% | 68.7% | 68.7% | +2.0 | 2.34 |
| GREEN → gap up | 1,206 | 872 | 72.3% | 70.2% | 68.7% | +3.6 | 3.74 |
| RED → gap down | 1,371 | 473 | 34.5% | 37.4% | 31.3% | +3.2 | 3.68 |
| GREEN & VIX down → gap up | 794 | 581 | 73.2% | 69.6% | 68.7% | +4.5 | 3.30 |
| RED & VIX up → gap down | 804 | 287 | 35.7% | 39.8% | 31.3% | +4.3 | 3.21 |

Model accuracy: 53.2%, 52.2%, 54.3% (paper: 53.1%, 52.8%, 54.4%).
"Any day" is how often the gap went that way on every day in the sample; z is
signal days against all other days.

**Traded on the future, all days to 2026-10-09:**

| Rule | Nights | Future gapped as predicted | Gross | Net | Net Sharpe | Max drawdown | Net Sharpe before / from 2024 |
|---|---|---|---|---|---|---|---|
| Long every night (yardstick) | 2,894 | 56.7% | +87.9% | −11.9% | −0.06 | −40.1% | 0.18 / −1.05 |
| VIX, long and short | 2,890 | 51.6% | +73.9% | −18.4% | −0.13 | −43.0% | 0.08 / −1.01 |
| Candle, long and short | 2,893 | 53.7% | +152.2% | +18.2% | 0.20 | −27.4% | 0.10 / 0.59 |
| Joint, long and short | 1,786 | 54.3% | +113.0% | +33.4% | 0.36 | −16.2% | 0.38 / 0.28 |
| Candle, long only | 1,353 | 61.3% | +123.9% | +57.1% | 0.59 | −21.2% | 0.62 / 0.49 |
| **Joint, long only** | 892 | 61.0% | +86.2% | +47.3% | 0.64 | −11.4% | 0.79 / 0.01 |
| Joint, short only | 894 | 47.6% | +14.4% | −9.4% | −0.13 | −24.4% | −0.26 / 0.38 |

## Findings

1. **The paper's counts are right and its benchmark is wrong.** The Nifty gaps
   up on 68.7% of all days. Predicting "up" every day is right 68.7% of the
   time; the paper's best model is right 54.3%. Its models are worse than no
   model, because each spends half its predictions on gap downs, which happen
   on one day in three.
2. **The signals do carry information.** Each lifts its own direction two to
   five points over the base rate, z between 2.3 and 3.7. Six tests were run,
   so the weakest two (VIX alone) should not be leaned on.
3. **The bearish side is not tradable.** After a RED day with VIX up the future
   gapped down 47.6% of the time. Short every such night: −9.4% net.
4. **The bullish side is where the overnight drift is.** Long only on GREEN
   and VIX-down nights is in the market 31% of nights and earns +86.2% gross,
   against +87.9% for being long every night. Costs then decide it: +47.3% net
   against −11.9%.
5. **It stopped working in 2024.** Joint, long only: +47.6% net to the end of
   2023, −0.2% from 2024 to October 2026 (Sharpe 0.79, then 0.01). The whole
   overnight drift in the future has been negative since 2024 (−21% net for the
   yardstick).
6. Net Sharpe 0.64 is a third of this project's noise bar of 1.88. Nothing here
   is a candidate for the gate.

## Decision

The paper is coded as written and kept as `backtested`, not promoted. The
study in `session_studies` stays (research 064 reads it); `gap_forecast` is the
fuller one and the library now points to it.

## Confidence

High on the accuracy tables: counts on an index, reproduced within three
points of the paper on a different sample. Medium on the trade: the future's
close and next open are real prices, but the order has to go in before the
close on values that are almost final (A-046), and one contract's cost is
assumed for the whole position.

## Open questions

- 2010 to 2014 is not held, so the paper's exact counts cannot be matched.
- Why the future's overnight drift turned negative in 2024 is not explained
  here. The cost schedule raises STT on a futures sale from 0.0125% to 0.02%
  in October 2024 and to 0.05% in April 2026 (`costs/schedule.py`), which
  explains part of the net figure but would not change gross returns.
- The index's gaps lean upward by construction (research 064): 66.8% up on the
  index, 56.7% on the future. The paper measured the index.
