# 061 — How do other platforms store backtest results?

**Question.** The operator asked how other platforms store backtest results,
and to store ours the same way. What does each keep, in what shape, and what
does EulerLab lack?

**Sources, fetched 2026-10-06.**

- QuantConnect LEAN CLI docs,
  `https://www.quantconnect.com/docs/v2/lean-cli/backtesting/deployment` —
  results go to `<projectName>/backtests/<timestamp>/` as JSON.
- LEAN source, `github.com/QuantConnect/Lean` (master):
  `Common/Packets/BacktestResultPacket.cs` (BacktestId, CompileId,
  PeriodStart/Finish, DateRequested/Finished),
  `Common/Result.cs` (Charts, Orders, OrderEvents, ProfitLoss, Statistics,
  RuntimeStatistics, AlgorithmConfiguration, TotalPerformance),
  `Common/Statistics/AlgorithmPerformance.cs` (TradeStatistics,
  PortfolioStatistics, ClosedTrades),
  `Common/Statistics/Trade.cs` (EntryTime/Price, ExitTime/Price, Direction,
  Quantity, ProfitLoss, TotalFees, MAE, MFE, EndTradeDrawdown, IsWin, OrderIds),
  `Engine/Results/BacktestingResultHandler.cs` and `BaseResultsHandler.cs` —
  writes `{id}.json`, `{id}-summary.json`, `{id}-order-events.json`,
  `{id}-log.txt`.
- NautilusTrader, `https://nautilustrader.io/docs/latest/concepts/reports/` —
  orders, order-fills, fills, positions and account reports as DataFrames;
  `engine.get_result()` gives `stats_pnls`, `stats_returns`, `stats_general`.
  Reports are built from memory; the docs recommend persisting them to a
  database yourself.
- vectorbt, `https://vectorbt.dev/api/portfolio/base/` — order, trade,
  position, drawdown and log records as structured arrays;
  `Portfolio.save()`/`load()` pickle the whole object.
- OpenAlgo, `https://docs.openalgo.in/` and `github.com/marketcalls/openalgo`
  (`frontend/src/stores/portfolioBacktestStore.ts`) — the last result is held
  in a zustand store and "not persisted"; the export is an HTML tearsheet.

## Findings

| Kept | LEAN | Nautilus | vectorbt | OpenAlgo | EulerLab before |
|---|---|---|---|---|---|
| A unique id per run | yes | no | no | no | **no** — keyed by configuration |
| Summary statistics | yes | yes | yes | in memory | yes |
| Equity curve | yes | yes | yes | in memory | yes |
| Orders / fills | yes | yes | yes | in memory | yes |
| Closed trades | yes, with MAE/MFE | positions | yes | in memory | **no** — rebuilt in browser |
| Code version | CompileId | no | no | no | **no** |
| Configuration | yes | no | no | request | yes (params on the result row) |

LEAN is the most complete and the only one with a durable per-run record, so
its model is the one copied.

## Decision

ADR-057. Every run is kept at `reports/<strategy>/runs/<configuration>/<run_id>.json`,
never overwritten; the per-configuration file stays as "latest". Each report
gains `trades` (FIFO round trips with MAE/MFE), `trade_summary`, `params`,
`data_version` and `provenance` (run id, time, git commit and dirty paths,
cost-model stamp).

## Confidence

High on what each platform stores — read from source, not snippets. The LEAN
docs page listing the file names returned 404; the names are from the source.

## Not found

No platform documents a retention policy. Nautilus has no built-in result
store at all. OpenAlgo's docs describe a portfolio backtester but no storage.
