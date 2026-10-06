# ADR-057: Every backtest run is kept, with the code that produced it

**Context.** A report was one file per configuration, replaced on every re-run, with no record of the commit behind it. Closed trades existed only in the browser.
**Options.** Keep as is; copy LEAN (one file per run id, closed trades, compile id); a database table per record type, as Nautilus suggests.
**Choice.** LEAN's shape in the existing JSON layout: `reports/<strategy>/runs/<configuration>/<run_id>.json`, written once; `<configuration>.json` stays as the latest copy; reports carry `trades`, `trade_summary`, `params`, `data_version` and `provenance` (`docs/RESEARCH/061`).
**Why.** It closes all three gaps with no new dependency, and every existing reader and old report keeps working.
**Cost if wrong.** Disk: each run is stored twice, about 0.6 MB for the largest report today; `make prune-runs` drops the history of configurations it drops.
