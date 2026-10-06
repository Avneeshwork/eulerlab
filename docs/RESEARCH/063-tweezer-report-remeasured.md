# 063 — The operator's Tweezer Bottom report, re-measured here

**Question.** The operator supplied a backtest report for Tweezer Bottom on
Nifty stocks, June 2025 to June 2026 (Protective Collar AI, June 2026: 178
triggered trades, win rate 51.1%, profit factor 2.65, +0.947% per trade,
+168.5% summed, before costs). Does the same rule set produce that here?

**Source.** The report itself, supplied by the operator 2026-10-06; its rules
are copied into `research/papers/protective-collar-2026-tweezer-bottom.yaml`.
Our run: `make tweezer-report` (`src/eulerlab/intraday/tweezer_report.py`),
Kite minute bars from B2, 2026-10-06. Output in `data/derived/tweezer_report.json`.

## Method

Same rules as the report's section 8, on the 50 most-traded NSE names by our
own turnover ranking (ADR-008; the report used 49 index constituents, so the
lists overlap but are not identical). Candles of 15, 30 and 60 minutes rolled
up from minute bars; indicators over the last 100 candles across sessions;
entry on the breakout of C1's high including the candle straight after C2.
Per-trade return = P&L / money put in at entry, summed, as the report does.
"Net" charges this platform's Indian intraday equity cost model.

The report does not say how long a trade may be held. Its exit table has 7
time exits in 178 trades, so most of its trades ran to a stop or target, not to
the close. Three holding limits were run: flat at the close, up to 5 sessions,
up to 20.

## Findings

| | Report | 15m, close | 30m, close | 60m, close | 15m, 5 days | 15m, 20 days |
|---|---|---|---|---|---|---|
| Triggered trades | 178 (all sizes) | 206 | 141 | 31 | 221 | 227 |
| Win rate | 51.1% | 51.0% / 50.0% | 46.8% / 45.4% | 67.7% / 64.5% | 46.2% / 46.2% | 46.7% / 46.7% |
| Profit factor | 2.65 | 1.45 / 1.31 | 0.93 / 0.83 | 1.70 / 1.43 | 1.23 / 1.16 | 1.24 / 1.17 |
| Average win | +2.97% | +1.00% / +0.98% | +0.74% / +0.72% | +0.44% / +0.42% | +1.78% / +1.74% | +1.79% / +1.74% |
| Average loss | −1.17% | −0.72% / −0.74% | −0.70% / −0.72% | −0.54% / −0.53% | −1.24% / −1.28% | −1.26% / −1.30% |
| Per trade | +0.947% | +0.157% / +0.116% | −0.027% / −0.068% | +0.122% / +0.080% | +0.154% / +0.113% | +0.162% / +0.121% |
| Sum | +168.5% | +32.3% / +23.9% | −3.9% / −9.6% | +3.8% / +2.5% | +34.0% / +24.9% | +36.9% / +27.5% |
| Max drawdown (summed) | −11.8% | −17.4% / −20.2% | −15.1% / −17.4% | −1.5% / −2.1% | −21.6% / −24.8% | −22.1% / −25.6% |

Each cell is gross / net. 30 and 60-minute with 5 and 20-day holds are worse
than flat-at-close (30m sums to −42% gross held 5 days).

1. **The report's result is not reproduced.** The best variant here, 15-minute
   candles, earns about a sixth of the report's per-trade figure before costs,
   and a profit factor of 1.2–1.5 rather than 2.65. 30-minute loses money on
   every holding limit. Summed across all three sizes, flat at the close, it
   is +16.7% net against the report's +168.5% gross.
2. **The gap is in the winners, not the hit rate.** Win rates are close to the
   report's (46–51%); average wins are a third to two-thirds of its +2.97%.
   The report has 57 of 178 trades (32%) reaching the 3R target. Here 2 to 8
   do, out of 170–227. The 0.5% trail after +1.5R exits most winners well
   before 3R when risk is 1.0–1.5% of price, and the report's T2 count is hard
   to reconcile with that rule as written.
3. **60-minute candles produce few signals.** 39 against the report's 61:
   with the 15:00 cutoff, the 14:15 and 15:15 candles cannot signal, which
   removes two of seven candles a day.
4. **Costs take about a quarter of the 15-minute edge** (₹73,000 on the
   15-minute, close-flat run at ₹10 lakh and 1% risk per trade).

## Possible causes of the gap, none confirmed

- The report counts 140 of its 178 trades as PENDING: detected with C2 as the
  latest candle and entry *estimated* at C1's high. If its backtest filled
  these at that estimate without checking the next candle traded there, or
  scored outcomes from candles already in the database at scan time, that is
  lookahead. The report does not show the fill logic.
- A different trail (on closes of a larger candle, or only after T1) would let
  more winners reach 3R.
- Universe differences (49 index names vs our 50 most-traded).

## Decision

Keep the rules exactly as the report states them and record this gap. Do not
tune toward the report's numbers: that would be fitting parameters to a target.
The next useful step is the report's own trade list, to compare trade by trade.

## Confidence

High that this code follows the report's written rules (each is a named field
in `tweezer.Rules`). Medium on the comparison: the universe differs and the
report's holding limit and fill logic are unstated.

## Open questions

- The report's trade list, or its fill rule for PENDING signals.
- Its holding limit and how its trailing stop is evaluated.
