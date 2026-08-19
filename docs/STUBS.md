# STUBS — everything currently fake

Logged the moment it is created, not at review time. If it is stubbed, mocked,
hardcoded or otherwise not what it appears to be, it is in this table.

Empty rows are good news. A long table is not a problem in itself — an
*unlisted* stub is.

---

| ID | What | Where | Why it is fake | Real in |
|---|---|---|---|---|
| S-001 | `Order` model — four fields and `algo_id`, nothing else | `src/eulerlab/schemas.py` | Reserves the `algo_id` field before the OMS exists. Adding the field now is 5 minutes; adding it after the OMS, reconciler, event log and attribution all read the schema is a week of migrations. **This is not the order schema — do not build on it.** | Sprint 19 |
| S-002 | `max_orders_per_second: 5` — a number nothing reads | `config/execution.yaml` | The OPS governor is a config key with no enforcement, because there is no EMS. Present so the compliance sprint is a config change rather than a redesign. | Sprint 19 (enforcement), Sprint 29 (tuned + confirmed) |
| S-003 | `static_ip: null` | `config/deploy.yaml` | Placeholder. The real value is a fixed IP registered with the broker, which cannot be chosen until a VPS and a broker account exist. | Sprint 29 |
| S-004 | `region: ap-south-1` in the deploy config | `config/deploy.yaml` | Written down as the intended region. No cloud account exists, nothing is provisioned there, nothing validates the string. | Sprint 2 (VPS) |

| S-005 | The minute universe covers 240 of 250 symbols | `config/universe_top250.txt` vs `data/landing/kite_minute/unresolved.jsonl` | 10 symbols do not resolve against Kite's current instrument list. Most are renames (ZOMATO→ETERNAL), but at least two are **demergers** (PEL, TATAMOTORS) which a one-to-one alias cannot express. Left unresolved deliberately rather than mapped by guesswork | Sprint 3 (security master) |
| S-006 | ~~The minute universe is ranked as of 2024-09-17~~ | — | **Resolved 2026-08-18.** Replaced by `config/universe_top250_union.txt`: the union of the top 250 sampled at each year-end 2021–2026, which is 444 symbols. A single snapshot would have been survivorship-biased whichever date it used — only 168 of 250 names overlap between Sept 2024 and today | done |

| S-007 | 3 minute-bar chunks are empty mid-history | `BCG` 2025-01-30→05-29, `FORCEMOT` 2023-12-07→2024-02-04 | **Not a fetch failure.** Re-queried Kite directly for the exact windows: 0 bars returned, while a control window for the same symbol returned 6,855. The data is absent at source. Both symbols traded on NSE around those dates per bhavcopy, so this is a Kite coverage gap, not a delisting | needs a second intraday source |
| S-009 | 2021-03-30 has cash bhavcopy but no F&O | `data/landing/nse/fo/2021/03/` | NSE returns 404 for the F&O file on that date while cash exists. Re-attempted 2026-08-19 and confirmed absent at source, not a fetch failure. The cash file for 2020-12-03 had the mirror-image gap and **was** recoverable, so this is a genuine one-off source absence rather than a systematic problem | not fixable from this source |
| S-008 | 1,055 minute chunks contain 0 bars | `data/landing/kite_minute/` | Overwhelmingly legitimate: 70 symbols listed after 2021, so their early chunks predate the listing (VAML's first data is 2026-05-25). Only the 3 in S-007 are gaps after data starts | not a defect |
| S-010 | ~~Total-return factor store not run against the full history~~ | — | **Code resolved 2026-08-19.** `make build-factors` is implemented, cached and resumable, and one full 2,121-file run completed successfully (3m30s). See S-012 — that run must be repeated because it used the defective join fixed the same day | superseded by S-012 |
| S-011 | ~~Rights-issue price effect parsed but not adjusted~~ | — | **Resolved 2026-08-19.** Implemented as `P/TERP` per NSE's methodology, cross-checked algebraically against the standard theoretical ex-rights price (research note 010) and validated against Reliance's 2020 issue. 11 tests. The formula source is a broker's summary rather than the NSE circular itself, recorded as A-015 | done |
| S-012 | ~~Adjustment factors not rebuilt since the ISIN-join fix~~ | — | **Resolved 2026-08-19.** Rebuilt: coverage went **78.1% → 98.1%**, recovering 3,073 dividend factors that the raw-ISIN join had silently dropped. `make check-adjust` is now 7/7 green including the previously-skipped series check, which validates **40 of 40 real 1:1 bonuses showing the expected ~2x raw price drop** | done |
| S-013 | The corporate-actions feed covers equities only, so ETF and fund-unit actions are invisible | `src/eulerlab/corp_actions/feed.py` — the endpoint is queried with `index=equities` | Found by the quality engine on first contact with real data: GROWWGOLD, BANKNIFTY1 and CONS all fell ~90.1% on 2026-02-27 (a 1:10 unit split) and **none of them appear in the feed at all**. Any backtest holding an ETF across such an event sees a phantom -90% crash. The equity history is unaffected | needs a second feed or an `index=` variant for funds |
| S-014 | A single unexplained signal-139 exit from `quality-options`, **not reproducible** | `src/eulerlab/options/run.py` | Observed once. Investigated: memory is not the cause (106 MB per F&O day, so 5 days in flight is ~530 MB), and 3 subsequent runs at DAYS=5 all exited cleanly. Left recorded rather than closed, because a segfault that happens once can happen again, and rather than invent a fix for a cause I could not demonstrate | if it recurs |

---

## Not stubs, but worth stating plainly

These are not fake — they simply do not exist yet, and no code pretends
otherwise: market data, any downloader, any database, the security master, both
backtesters, any strategy, any broker connection. See `STATE.md`.
