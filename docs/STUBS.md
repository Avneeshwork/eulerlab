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
| S-010 | Total-return factor store built and unit-tested, but not run against the full 2015-2026 close-price history | `src/eulerlab/corp_actions/adjust.py::build_total_return_factor_store`, `prices.py::build_close_index` | Correctness is verified with injected close-price lookups (16 tests). Running it for real needs `build_close_index` to stream all 2,869 cash bhavcopy files from B2 (~2.2 GB), which was not run this session — a cost/time tradeoff, not a correctness gap. The price-adjustment (bonus/split) store, which needs no price lookup, **was** run against the full real 2015-2026 feed | when the operator runs the close-index build |
| S-011 | Rights-issue price effect is parsed (ratio + premium) but not folded into either adjustment factor | `src/eulerlab/corp_actions/adjust.py` | The correct formula needs the issue price and the market price at ex-date, not just the ratio — a bonus-style ratio-only formula would be wrong. 276 of 25,713 actions (1.1%) are rights issues | not scheduled |

---

## Not stubs, but worth stating plainly

These are not fake — they simply do not exist yet, and no code pretends
otherwise: market data, any downloader, any database, the security master, both
backtesters, any strategy, any broker connection. See `STATE.md`.
