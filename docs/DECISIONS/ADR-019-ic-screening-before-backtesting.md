# ADR-019 — IC screening, with the trial counter started now

**Date:** 2026-08-19 · **Sprint:** 8 · **Status:** accepted

**Context.** Sprint 8 is the first sprint that evaluates whether anything
*predicts* rather than whether anything is *correct*. Two decisions had to be
made before any feature was written: what statistic to screen on, and when to
start counting attempts.

**Options (statistic).** (a) Run a small backtest per feature. (b) Pearson
correlation of feature against forward return. (c) Rank (Spearman) IC.

**Choice.** (c), at a 21-day horizon, sampled every 5th trading day.

**Why.** (a) is roughly fifty times the work and answers a question that only
matters *after* a feature shows any signal at all, so it is the wrong first
filter. (b) fails on this project's own measured data: Sprint 6 established
that returns here are strongly fat-tailed, and a Pearson correlation on
fat-tailed inputs is dominated by a handful of extreme points. Spearman asks
only about ordering, so one wild value moves it by one rank.

That is the third time this sprint sequence has reached the same conclusion —
MAD over standard deviation (ADR-017), Theil-Sen over least squares (ADR-018),
and now rank over Pearson. The pattern is worth naming: **every estimator in
this codebase that touches market data must have a non-zero breakdown point**,
because the data reliably contains points that would otherwise dominate it.

**Options (trial counter).** (a) Start it in Sprint 13, where the
multiple-testing correction actually consumes it. (b) Start it now.

**Choice.** (b), `data/derived/trials.jsonl`, append-only.

**Why.** The quantity it protects is *how many things were ever tried*. A
count that begins late is worse than no count at all: it looks authoritative
while understating the denominator, and it understates it in the flattering
direction. Every `make ic` invocation appends a row, including re-runs of the
same feature — deduplicating would defeat the purpose.

**Cost if wrong.** The IC horizon and sampling step are parameters, not
assumptions, and re-running is free now the panel is cached. The real
limitation is stated in the tear sheet rather than hidden: cross-sections
overlap at a 21-day horizon, so the t-statistic is optimistic by roughly the
square root of the overlap. IC is a screen, not a test, and nothing here is
evidence of tradeable edge until it has survived a cost model (Sprint 9) and
the overfitting battery (Sprint 13).
