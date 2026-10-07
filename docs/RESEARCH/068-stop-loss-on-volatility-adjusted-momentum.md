# 068 — A 5% stop-loss on volatility-adjusted momentum

**Question.** Operator, 2026-10-07: "test with keeping stop loss of 5% ... till
rebalance period holding", then "keep best case we get and apply first on
that", then "don't buy anything, keep stoploss hit stock money as cash". Does a
5% stop inside each holding period improve the strategy?

No web sources: a measurement on the panel. `make stop-sharpe-momentum`
(`src/eulerlab/research/stop_sharpe_momentum.py`, `StopLossRankTop`).

## The rule

At each ranking a stock's stop is set 5% below its close on the first session
of the holding period. Each session it closes at or below that, it is sold at
the next session's price. Two variants of what happens to the money:

- **cash** (operator's choice): it waits in cash until the next ranking.
- **spread**: it is spread over the remaining holdings by value.

The engine decides every session. A control run with a stop that never triggers
is run first. It differs from the plain strategy only because deciding daily
retries a sale the exchange rejected (stock not traded on its fill day) the next
session: −0.73% of final equity over ten years on the best case, 0.00 on the
paper setting. The stop's effect is read against that control.

## Results, after costs, Tier B, ₹10 lakh

Best case of research 067 (12-month window, 10 names, every 10 sessions), cash:

| | Sharpe | Total | Max DD | 2016-23 Sharpe / CAGR | 2024-26 Sharpe / CAGR | Fills | Costs | Stops |
|---|---|---|---|---|---|---|---|---|
| Stop off | 1.23 | +2,157% | −39% | 1.26 / 35.0% | 1.16 / 33.3% | 3,199 | ₹10.1L | 0 |
| 5% stop, cash | 1.15 | +1,072% | −38% | 1.26 / 29.0% | 0.87 / 19.3% | 3,749 | ₹11.6L | 847 |

Paper setting (12-month, 30 names, every 21 sessions), spread:

| | Sharpe | Total | Max DD | 2016-23 Sharpe / CAGR | 2024-26 Sharpe / CAGR | Fills | Costs | Stops |
|---|---|---|---|---|---|---|---|---|
| Stop off | 1.03 | +814% | −44% | 1.12 / 25.5% | 0.80 / 17.8% | 4,601 | ₹3.4L | 0 |
| 5% stop, spread | 0.97 | +323% | −32% | 1.06 / 16.1% | 0.72 / 10.9% | 26,687 | ₹5.8L | 2,030 |

## Findings

1. **The 5% stop lowers return and Sharpe in both settings, in both periods.**
   On the best case it halves the ten-year return and cuts the 2024-26 Sharpe
   from 1.16 to 0.87.
2. **It barely reduces the worst fall on the best case** (−39% to −38%). The
   big drawdowns are market-wide falls, which hit through the stop on a gap.
3. **5% is inside a momentum stock's normal noise.** 847 stops in about 264
   two-week periods: roughly three of the ten holdings are stopped out in an
   average period, and their money sits in cash until the next ranking.

## Decision

No stop. Neither variant is adopted.

**Open:** wider stops (10-15%) were not tested; the operator asked for 5%.
