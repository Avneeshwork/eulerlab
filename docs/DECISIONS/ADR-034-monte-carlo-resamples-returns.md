# ADR-034 — Monte Carlo resamples returns, and runs two tests, not one

**Context.** The validation battery had CPCV, DSR, PBO, MinBTL and stress
tests, but nothing asking whether a result depended on the *order* returns
arrived in. 2CentsCapital's TradeMaster (`~/Documents/TradeMaster_Avneesh`) has
a `MonteCarloSimulation` module that shuffles price data and re-runs the
backtest; the idea is theirs and it fills a genuine gap here.

**Options.** (a) Port it as-is — shuffle prices, re-run. (b) Resample the
realised return series instead. (c) Skip it; the battery is already large.

**Choice.** (b), and split into two tests that are reported separately:
**shuffle** (reorder, same sample) and **bootstrap** (resample with
replacement).

**Why.** Re-running on shuffled prices changes *which trades the strategy
takes*, mixing path risk with a different strategy, and costs one backtest per
simulation. Resampling the returns holds the decisions fixed and costs nothing.

The split matters more. Shuffling leaves the mean and standard deviation
untouched, so **the Sharpe ratio is identical in every shuffled path** — any
tool reporting a "Monte Carlo Sharpe distribution" from shuffling alone is
reporting zero information. Shuffling can only answer *how bad could the
drawdown have been*. A confidence interval on the edge needs sampling with
replacement, which is a different operation. A test asserts the invariance so
this can never quietly regress.

**Cost if wrong.** Both tests assume returns are exchangeable, and real returns
cluster — shuffling breaks up exactly the clustering that produces the worst
drawdowns. The reported interval is therefore a **lower** bound on risk, and
the render says so on every run. Treating it as the full picture would
understate tail risk in the flattering direction. It spends no trial, because
resampling an existing result evaluates nothing new.
