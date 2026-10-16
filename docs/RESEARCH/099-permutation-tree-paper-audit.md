# Permutation Decision Tree paper: source and code audit

**Screen date:** 2026-10-15
**Decision:** Reject the reported result as evidence for an intraday strategy.
**Research Library record:** `ramraj-2025-permutation-trees-india`

## Source

Ramraj, V., Nagaraj, N. and Harikrishnan, N. B. (2025), “Predicting Stock Prices
using Permutation Decision Trees and Strategic Trailing,” [arXiv:2504.12828v3](https://arxiv.org/html/2504.12828v3).
The authors link their implementation at [i-to-the-power-i/pdt-stocks](https://github.com/i-to-the-power-i/pdt-stocks), chiefly
[`pdtcode.py`](https://github.com/i-to-the-power-i/pdt-stocks/blob/main/pdtcode.py)
and [`pdttree.py`](https://github.com/i-to-the-power-i/pdt-stocks/blob/main/pdttree.py).

This is distinct from Naga et al.'s Gini tree card: the source uses the sequence
compression based Effort-To-Compress (ETC) impurity and a 50-bar forward-close
label. The paper says its NSE sample is Nifty 50 five-minute data from
2024-10-18 through 2025-01-14, approximately 4,426 rows per stock. It reports
average PDT growth of 1.1802% and buy-and-hold return of -2.29% for its short
test window. The source explicitly says it omits transaction costs and slippage.

## Reconstructed published rule

- Features: distance from close to the latest trailing three-bar swing high and
  low; a five-bar narrow-range/order-block flag using a 0.2% close threshold;
  prior-bar 20 and 50 moving averages; prior-bar RSI(14); and the difference of
  the moving averages.
- Label: `close[t + 50] > close[t]` on five-minute rows.
- Model: recursively split at the threshold maximizing size-weighted ETC gain;
  author code calls the builder with maximum depth 20 and no minimum leaf size.
- Long entry: prediction 1, using the current row's close. Exit when prediction
  turns 0 or a 0.5% trailing close stop is crossed. The code carries a position
  to the end of the test sample if neither exit occurs.

## Why the published return is not accepted

1. **The training labels are not purged.** In `pdtcode.py`, `X[:split_index]`
   and `y[:split_index]` are used for training, while only the first 50 rows of
   test are removed. The last 50 training labels still use closes from inside
   the test period. Removing test rows cannot undo that leakage.
2. **The execution fill is not causal.** Predictions use features that include
   the current bar's high/low and close-derived inputs, then the simulation
   buys or exits at that same bar's close. A signal known only after the bar
   closes cannot generally receive that already printed close.
3. **The target is not intraday.** Fifty five-minute observations may cross
   multiple sessions. Neither the paper's execution description nor released
   code squares positions off at the end of each session.
4. **It is gross of costs.** The authors themselves list costs and slippage as
   future work. A small gross return over roughly three months cannot establish
   net profitability.

The headline is therefore marked rejected in the Research Library. I did not
substitute a next-bar fill, purge, or EOD exit and call the result a replication:
those changes define a new adaptation. No strategy card or local backtest is
created from this paper. The local price-screen cutoff is 2024-11-30; the
paper's reported test extends beyond it, and data after that cutoff remains
unread under the current evaluation policy.

## Deduplication and next evidence needed

The paper is methodologically distinct from the existing Naga et al. Gini-tree
candidate, but the two belong to the same broad decision-tree signal family.
Reconsider only as a separately named adaptation with a purged chronological
split, next-bar execution, explicit per-session square-off, costs, and a
predeclared train/test schedule that does not inspect reserved dates. Such a
test would evaluate a new PDT adaptation, not validate the paper's reported
1.18% result.
