# ADR-086: One data quality contract every dataset is graded against

- **Context:** The operator asked that whatever is ingested is held to one quality reference. Each feed had its own checks, and a backtest could run on a panel built from a corrupted day without saying so.
- **Options:** (a) more checks inside each ingest; (b) a register of every dataset and one grader with the same six checks for all; (c) a paid data-quality tool.
- **Choice:** (b). `config/data_sources.yaml` lists 18 datasets with publisher, address, licence status and knowledge time. `quality/contract.py` grades each A–D on registered, provenance, fingerprint, sense and quarantine, with freshness reported apart; a derived table takes the worst grade of what it is built from. `quality/quarantine.py` is an append-only list of held files: raw data is never moved or edited. The panel build skips held files and holds any file whose SHA-256 no longer matches its manifest. `make backtest` refuses a price panel below its minimum grade unless `ALLOW_LOW=1`.
- **Why:** One table answers "can I trust this?" for every source. Quarantine by list keeps `data/landing/` immutable.
- **Cost if wrong:** Grades are only as good as the checks. Licences are "unreviewed" for most sources, which caps them at B until someone reads the terms (S-044). Only the panel build skips quarantined files so far (S-043).
