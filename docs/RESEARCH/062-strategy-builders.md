# 062 — How do other platforms let you build a strategy?

**Question.** The operator found the builder vague and asked for a new one,
researched properly. What do established builders ask for, and in what shape?

**Sources, fetched 2026-10-06.**

- QuantConnect, Algorithm Framework overview,
  `https://www.quantconnect.com/docs/v2/writing-algorithms/algorithm-framework/overview` —
  five modules in sequence: universe selection → alpha (insights) → portfolio
  construction (targets) → risk management (adjusted targets) → execution.
  Modules must not depend on one another's state.
- Zerodha Streak, `https://zerodha.com/z-connect/streak/introducing-streak-v4`
  and search summaries of Streak's help (its help pages returned no content and
  `blog.streak.ninja` did not resolve) — instrument, candle interval, up to five
  entry conditions built from indicator / comparator / value-or-indicator,
  optional exit conditions, percentage stop loss and target tracked on LTP,
  then backtest and deploy.
- Composer, `https://www.composer.trade/learn/how-composer-symphonies-work` and
  `https://help.composer.trade/article/18-symphony-editor-assign-weights` —
  blocks: asset, weight (equal, specified, inverse volatility, market cap),
  if/else with ANY/ALL conditions, filter (sort and keep top/bottom N), group.
- OpenAlgo, `github.com/marketcalls/openalgo` `docs/prd/flow.md` — Flow is a
  React Flow canvas of 53 nodes (triggers, conditions, order actions, data,
  streaming) that executes live orders on a schedule or webhook. It does not
  backtest.

## Findings

Every builder separates **what may be traded** from **when to act** from
**how much** from **when to stop**. Rule rows (`RSI(14) crosses below 30`)
are the common unit for "when"; Composer's filter is the common unit for
"which of many". A canvas is the most expressive and the hardest to read back.

## Decision

ADR-058: QuantConnect's split as five steps, Streak's rule rows and stops,
Composer's "rank and keep top N", stored as a declared spec. Not a canvas.

## Confidence

High on QuantConnect, Composer and OpenAlgo (pages and source read). Medium on
Streak's exact field list: its help pages did not render, so it rests on
Zerodha's announcement post and secondary summaries.

## Not found

Streak's comparator list and indicator count from a primary page. Whether
Composer evaluates conditions on close or intraday.
