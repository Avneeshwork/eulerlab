# Loss filters for the three new intraday strategies

**Screen date:** 2026-10-15
**Filter development:** 2024-01-01 through 2024-11-30 (224 sessions)
**Frozen test:** 2025-01-01 through 2026-10-14 (440 sessions)

This follows the source-based screen in [084](084-gold-and-indian-stock-intraday-screen.md).
The filters were chosen on the 2024 development period using net returns. The later test
period was not used to select settings. Results are screening evidence, not live results.

## Frozen filters and test results

| New strategy | Filter selected on 2024 | Later test, gross | Later test, after costs | Activity reduction | Test drawdown / Sharpe |
|---|---|---:|---:|---:|---:|
| Gold ETF moving-average rules | SMA(50); do not open or reverse unless close is at least 20 bp from the average | +49.60% | **+1.58%** | 1,290 fills vs 4,160 (−68.99%) | −13.91% / 0.135 |
| Extreme-minute reversal | Keep only the most extreme 0.025% of one-minute declines, with cutoff learned on 2022–2023 | +0.01% | −4.38% | 228 trades vs 884 (−74.21%) | −4.46% / −2.713 |
| NSE decision tree | Require predicted class probability ≥0.80; take at most the most confident trade per stock per session | −0.03% | −0.95% | 47 trades vs 354,730 events (−99.99%) | −0.95% / −5.290 |

The Gold ETF rule is the only filtered candidate above zero after costs in the later test.
Its +1.58% is cumulative across 440 sessions, with a weak Sharpe and a 13.91% drawdown.
GOLDBEES buy-and-hold returned +86.49% gross over the same dates (first tradable open to
last close), so the filtered rule materially underperformed its simple benchmark. It is a
GOLDBEES proxy result, not a result on MCX Gold futures. Fees use the NSE equity router and
assume 1 bp slippage per side.

The reversal and tree filters cut activity but do not produce a positive after-cost result.
The tree's original +70.09% gross result did not survive even after restricting it to 47
high-confidence events in the later sample. It should not be described as profitable.
Stock tests use five fixed NSE names, equal ₹200,000 notional per name, NSE intraday fees,
and 2 bp slippage per side. The sample is not a point-in-time universe.

## Filter definitions

- **Gold ETF:** The 2024 grid tested SMA, EMA and WMA horizons 50/100/150/200, with close
  confirmation of 1/2/3/5 bars and average-distance bands of 0/5/10/20/40 bp. The selected
  rule uses one completed close and a 20 bp dead band. While inside the band, an open
  position is held; a reverse signal must cross the other edge. This suppresses trades in
  the noisy area around the average. The selected setting is one of 240 development
  configurations, so the 2024 score is selected and biased upward.
- **Extreme reversal:** The original 0.1% training-tail trigger was tightened to the
  0.025% tail. The threshold is still learned from 2022–2023 and held fixed. The 2024
  development search chose among three stricter thresholds.
- **Decision tree:** The classifier remains trained on 2022–2023. Development tested
  probability cutoffs 0.50–0.80 and daily caps of 1/2/3/5 trades per stock. The selected
  filter requires confidence of 0.80 and keeps only the most confident event in each
  stock-session.

## Reproduction and library

Run `make gold-stock-intraday-optimize`. It writes the full parameter grid and frozen
test result to `data/derived/new_strategy_optimization.json`, which is generated output.
The three `optimization-oos` runs are also stored on the new Strategy Library cards; their
source papers remain linked in the Research Library:

- [Gold technical analysis paper](../../research/papers/batten-2018-intraday-technical-analysis-gold.yaml)
- [Extreme-minute reversal paper](../../research/papers/rif-utz-2021-extreme-minute-reversal.yaml)
- [Intraday decision-tree paper](../../research/papers/naga-2024-decision-tree-intraday.yaml)
