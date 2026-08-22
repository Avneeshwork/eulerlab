# TASKS — the ledger

Every task, its status, and the command that proves it. Statuses:
**TODO** · **DOING** · **DONE** · **BLOCKED** · **KILLED**

Sprints 0–14 are seeded from `docs/AI_BUILD_PLAN.md` §6 and
`docs/sprint_01_kickoff.md`. Sprints 15+ are planned three ahead, per the build
plan — they are listed here as scope only, not as tasks.

---

## Tweezer Bottom — intraday candlestick strategy (2026-08-20)

Operator-supplied rules. Verify: `uv run pytest tests/test_intraday_tweezer.py`

| ID | Task | Status |
|---|---|---|
| T-3201 | Indicators written by hand, not `pandas_ta` | DONE — no new dependency; every primitive tested against a hand-computed value |
| T-3202 | Wilder smoothing kept distinct from an EMA | DONE — 1/n not 2/(n+1); a test pins it |
| T-3203 | Pattern detector, Steps 1-8 exactly | DONE — `intraday/tweezer.py` |
| T-3204 | Bracket executor, Steps 9-10 | DONE — stop-entry, TP1/TP2, breakeven, trailing, session close |
| T-3205 | Ambiguous bars resolved against us | DONE — a bar holding both stop and target takes the STOP |
| T-3206 | Rejections name the rule and the value | DONE — "no trade" and "ADX was 51" are different facts |
| T-3207 | Panel carries OHLC | DONE — optional, falls back to a flat bar (S-024) |
| T-3208 | ~~Never run on real data~~ | DONE — reads B2 directly; `make tweezer` |
| T-3211 | `restore_local` cannot see minute data | DONE — it walks the NSE manifest, which never covered `kite_minute`; `intraday/store.py` reads B2 directly |
| T-3212 | **The setup is extremely rare** | OPEN — 2 setups in 136,740 candles (3 symbols, 6 months). 0.15% low tolerance on minute bars is very tight. T-3214 makes scanning a wider universe possible; the wider run itself has not been executed, so this is still evidence-free |
| T-3213 | Tweezer in the workbench UI | DONE — its own surface, not a tab beside the daily engine |
| T-3209 | Not a `Strategy` subclass | OPEN by design — intraday, conditional entry, bracket exit and risk-based sizing cannot be target weights |
| T-3210 | Rebuild the panel with OHLC | OPEN — 2,869 B2 downloads. **The cap is not a blocker** — the operator confirmed B2 is effectively unmetered; just run it |
| T-3214 | Scan a whole universe, not 3 hand-picked symbols | DONE — `--universe nifty50\|nifty100\|nifty250` (ADR-008 liquidity ranking, not index membership) added to `intraday/scan.py`, `make tweezer`, and the workbench `/api/tweezer` route; `scan_many` threads the B2 reads since the work is I/O-bound, not CPU-bound. A symbol with no minute data is reported and skipped rather than failing the whole run. **Widening the universe still has not been run** — T-3212 stays OPEN until it has |

---

## Fleet scale-up — many strategies, many asset classes (2026-08-21)

Operator asked to scale to hundreds of strategies across asset classes, with
RM/TM attachment and a backtest → forward-test → live pipeline. Architecture in
ADR-035 (PROPOSED). Verify: `uv run pytest tests/test_validation_ledger.py`

| ID | Task | Status |
|---|---|---|
| T-3301 | σ_SR is assumed 1.0 and scales the entire noise bar | DONE (instrumented) — `ledger.sharpe_dispersion()` measures it and **refuses** while only 3 entries carry a Sharpe, all H-0001. A-021 |
| T-3302 | Dispersion across distinct subjects, never across entries | DONE — one hypothesis re-evaluated 8 times is one strategy; counting repeats shrinks σ and lowers the bar. Mutation-tested: naive row-counting fails 2 tests |
| T-3303 | Canonical `sharpe` key recorded going forward | DONE — `validation/run.py` writes it alongside the legacy key. Past entries are hash-chained and **must not** be rewritten, so both keys stay readable forever |
| T-3304 | The bar is marked "assumed" wherever it is shown | DONE — `/api/health` returns `noise_bar_sigma_measured`, the workbench marks it. A caveat that travels in the payload, not the page |
| T-3305 | **σ_SR still unmeasured** — needs 5 distinct validated hypotheses | OPEN — the project has 1. Until then the bar rests on an assumption, and at σ_SR ≤ 0.68 the best-ever 1.27 would clear it |
| T-3306 | ADR-035: count trials by family, control FDR not FWER | OPEN — **operator decision.** `mandate.yaml` and `gates.py` untouched. At 1,000 trials the flat counter demands Sharpe 3.26 |
| T-3307 | Effective-N estimator has no primary source | OPEN — A-020. Direction sourced (Harvey/Liu/Zhu §4); the specific method is not |
| T-3308 | `strategies/` package + registry | DONE — `src/eulerlab/strategies/`. Declarations only; it runs nothing. **Stage is derived from the ledger, never stored** — `forward_testing` and `live` are unreachable because no mechanism produces them, and a test asserts no strategy can reach them |
| T-3314 | Fleet console: list, instruments, run pricing | DONE — `/api/fleet`, `/api/capabilities`, `/api/instruments`, `/api/run/price`; `FleetTable`, `InstrumentPicker`, `RunComposer`. Fleet is now the default surface; authoring demoted to one action within it |
| T-3315 | Every Sharpe drawn against the bar, never bare | DONE — sorting by Sharpe stays possible and warns that it is the selection procedure PBO measures. Unmeasured sorts last, never as zero |
| T-3316 | Capability matrix: declared ≠ supported | DONE — `strategies/catalog.py` reads real paths. **Caught a bug in itself**: first version checked `panel.parquet` while the panel is `price_panel.jsonl`, so it reported "not built" for 540 MB on disk. Regression-tested |
| T-3317 | The batch runner behind the composer | DONE — `src/eulerlab/batch/`, content-addressed cache on (strategy, params, data_version, cost_model_version). Runs through the same `_engine_run` the single backtest uses |
| T-3319 | Batch runs are sequential | OPEN by design — a process pool means N copies of a 540 MB panel. Needs shared memory, which needs a panel format that supports it. Measure before parallelising |
| T-3320 | **The composer was claiming to spend trials, and it does not** | FIXED — only `gate_run.py` and `validation/run.py` write to the ledger. A batch of backtests spends nothing, so "Spend N trials and run" was false. It now reports where the bar *would* stand if the search were recorded, and the result counts `unrecorded` configurations |
| T-3321 | **Screening is unrecorded search** | OPEN — the real hole the above exposed. The UI lets you evaluate any number of configurations without the counter moving, which is the laundering ADR-036 named. Reporting it is not closing it |
| T-3322 | A run that never traded reported Sharpe 0.00 | FIXED — `rank_and_hold` on a 250-day window held nothing (263-period lookback) and returned zeros, which read as "no edge". Now raises and names the cause. Regression-tested |
| T-3318 | Result cache, so `cached` is measured not entered | OPEN — the composer's cached count is a what-if control and says so |
| T-3309 | RM/TM as seams between `target_weights()` and order planning | TODO — `Strategy` itself must not change |
| T-3310 | `EventStrategy` for intraday/bracket shapes (Tweezer is not a `Strategy`) | TODO — T-3209 is the same gap |
| T-3311 | Forward-test as an explicit per-strategy stage | TODO — `paper/runner.py` already is the mechanism; the stage is untracked |
| T-3312 | `server.py` has no test coverage | OPEN — no test imports it; the type gate was the only check, and it was red in CI for 5 merges |
| T-3340 | **sync-cloud enumerated the landing root once** | FIXED — a tree created *while the sync ran* was not in the startup listing, so it was never uploaded and the run still exited **0**. A gigabyte of crypto sat unmirrored while the command reported success. The root is now re-scanned after each pass, bounded at 5 sweeps. 4 tests |
| T-3313 | Schedule `make daily` so data actually updates | DONE — `tools/schedule_daily.py`, launchd not cron (cron does not fire if the laptop slept; launchd catches up on wake). Installed and **loaded**, 19:30 daily. `make schedule` to inspect |
| T-3323 | Mutual fund NAVs ingested | DONE — ADR-038. AMFI `NAVAll.txt` daily snapshot (14,288 schemes, 1,680 direct-growth) + full per-scheme history from mfapi.in. **Morningstar was a dead end — 6 rows.** In `make daily` as `--snapshot-only`; the history backfill is a one-off |
| T-3324 | The old AMFI URL fails silently | RECORDED — `www.amfiindia.com` now 302s to `portal.amfiindia.com`; the redirect page parses as *zero schemes*, not an error. `Trade`'s scraper is in that state now. Our parser raises on an empty result |
| T-3325 | mf history backfill | DONE — **14,288 schemes, 21,709,107 NAV rows, 216 MB, zero failures.** Resumable: a scheme already current is skipped without a request. Only the daily snapshot is in `make daily`; this backfill is a one-off |
| T-3335 | 8 schemes returned no history | RECORDED — S-026. Newly launched funds that AMFI lists and the mfapi.in mirror has not caught up on. Not a failure; the daily snapshot accumulates their history from today |
| T-3327 | Morningstar ratings ingested | DONE — ADR-039. `make morningstar`. **5,741 funds**, up from the 6 the old scraper managed: it read page 1 and stopped, and the page is ASP.NET `__doPostBack` paging that a GET loop cannot walk |
| T-3328 | The ratings are icons, not text | DONE — values live in a CSS class (`analyst-rating-icon-bronze`) and a `title` (`Star Rating 3`). Reading cell text returns empty, which is why the old scraper's few rows were useless anyway |
| T-3329 | Join Morningstar to AMFI on ISIN | DONE — the *listing* page has no ISIN, but each fund's own page does. Operator called it; checking rather than assuming proved it. **25/25 exact on the first page, zero ambiguous**, vs 18.3% fuzzy by name. Costs a second crawl of 5,741 fund pages, resumable |
| T-3332 | **The join was at the wrong grain** | FIXED — AMFI publishes **two ISINs per `scheme_code`** (payout and reinvestment); Morningstar treats them as two funds. Joining on scheme_code made two legitimate ratings collide and the one-to-one guard dropped both. They were two instruments in one scheme. The 18.3% ceiling was an artefact of the grain, not a fact about the data |
| T-3334 | Listing pagination is flaky | RECORDED — the same code walked all 29 pages once and stalled at page 4 the next (the "Next" link vanished mid-crawl). The stall guard stopped cleanly rather than looping, and the landed 5,741-row snapshot is intact. **The ISIN crawl no longer depends on it**: fund pages resolve on the id alone (the URL slug is decorative), so it runs off the landed file and is resumable |
| T-3337 | **ISIN join measured on the full dataset** | DONE — 4,696 ISINs crawled from 5,741 fund pages. **4,845 of 5,741 ratings matched (84.4%), 4,615 by exact ISIN** — against 18.3% by fuzzy name. 401 ambiguous, 495 unmatched. Enriched: 18,018 rows, 4,845 carrying a rating |
| T-3338 | Enrichment was at the wrong grain again | FIXED — `enrich` emitted one row per scheme keyed on `isin_growth`, so every rating matched to a scheme's **reinvestment** ISIN had nowhere to land: 1,727 of 4,845 matches silently dropped, invisible because the rows that did appear looked right. Now one row per (scheme, ISIN). Attachment 100%. Regression-tested |
| T-3333 | `rating_join` records how each row matched | DONE — `isin` / `name-fuzzy` / `none`, so an identifier match is never mistaken for an educated guess. AMFI stays the spine: every scheme appears once, rated or not |
| T-3330 | Pager was clicked by a fixed control id | FIXED — `ctl02$ctl01` is the literal "2" link, so the crawl re-served page 2 and stopped at 400/5,741 while reporting a clean stop. Now found by label. Regression-tested |
| T-3331 | Unrated funds were stored as zero stars | FIXED — Morningstar's scale is 1-5 and the page renders unrated as `Star Rating 0`; **405 funds** affected. Zero is not a point on the scale. **Third null-rendered-as-zero bug this session** — worth treating as a standing hazard |
| T-3326 | Workbench typography | DONE — IBM Plex superfamily (serif headings, sans text, mono numbers), real type scale, surface blocks became tabs. The palette was already good; the type was the weak part |

---

## Multi-user platform (2026-08-21)

**Operator reversed the single-operator premise.** ADR-040. Verify:
`uv run pytest tests/test_workspace.py`

| ID | Task | Status |
|---|---|---|
| T-3601 | **ADR-040 records the reversal** | DONE — `CLAUDE.md` opens with "single operator, single-person capital... not scale", and every cost rule descends from it. That file is operator-owned; **it needs amending by them, not me** |
| T-3602 | Workspace model: shared data, isolated evidence | DONE — `workspace.py`. Landing zone and panels shared (duplicating 3.5 GB per tenant is absurd); ledger, strategies, credentials and kill switch per workspace |
| T-3603 | The id is the security boundary | DONE — one validation point, refuses rather than sanitises. A sanitiser turning `../../etc` into `etc` produces a *valid* id for an attack. NFKC first so a fullwidth solidus cannot smuggle a separator. 9 hostile inputs tested |
| T-3604 | Resolution is the only door | DONE — an unknown principal **raises**, never falls back to default. A typo in a tenant id must not hand back somebody else's evidence |
| T-3605 | The default workspace keeps the existing hash chain | DONE — that ledger holds 19 real trials and is hash-chained; moving it would break every link, which is the tampering the chain exists to expose |
| T-3606 | Global kill switch outranks per-workspace | DONE — a platform halt reported over a tenant's own reason, or they look in the wrong place |
| T-3607 | **Per-workspace ledgers weaken the bar** | OPEN by decision — sharing is statistically more correct but unsellable (one customer's failed search raises another's). Mitigation: within a workspace, count **everything**, including the screening that is currently free (T-3321) |
| T-3608 | Authentication is a seam, not an implementation | OPEN — `resolve()` takes a principal; what produces it (session, OIDC, local default) is undecided. No fake auth was written |
| T-3609 | Dashboard: primitives + library screen | DONE — `/terminal`, against the real `/api/fleet`. Verified in both themes with 12 real strategies |
| T-3620 | The first pass was a Bloomberg pastiche | FIXED — 10.5px monospace in a nine-column table. Dense is not the same as professional, and none of the density was carrying information a wider row could not. Rebuilt on the Robinhood reference (`docs/RESEARCH/018`): structural whitespace, one hero number, progressive disclosure |
| T-3621 | **Green means cleared the bar, never "performed well"** | DONE — ADR-041. The reference's own rule is that the portfolio turns green when it is up; that is the fastest-read signal in the interface and it would be arguing the opposite of everything else on the page. The accent is spent on evidence instead |
| T-3622 | The hero number is the bar, not a return | DONE — putting a strategy's Sharpe in the hero slot is the whole layout asserting that return is what matters. The bar is what actually decides anything, so it gets the 56px |
| T-3623 | The denominator travels with the figure at every breakpoint | DONE — `SharpeCell` prints "best of N" under the number, not only in the Runs column, which the narrow layout hides |
| T-3624 | Three meta columns could not survive the narrow breakpoint | FIXED — class, timeframe and evidence collapsed into one grid cell. As three cells they had to share one grid area on narrow and overlapped; as one cell the group drops to a second line intact, so the column the page is sorted by does not vanish at 1080px |
| T-3610 | **The default sort is evidence, not Sharpe** | DONE — ranking a library by return *is* the selection procedure the overfitting tests measure, performed by the interface before anyone has thought about it. Sorting by Sharpe stays available and warns |
| T-3611 | Command palette | DONE — Bloomberg's mnemonics without the keyboard. `⌘K`, `STRAT`/`FEAT`/`PAPER`/`RUN` prefixes, arrow keys, Escape. At a thousand strategies a menu is not viable |
| T-3612 | Tokens scoped to `.terminal`, not `:root` | DONE by design — the existing workbench uses the same variable names with a warm palette; global tokens would have repainted it silently. Both coexist until the terminal replaces it, then it becomes `:root` in one commit |
| T-3615 | Best backtest result saved as a strategy's result | DONE — `results.py`, per workspace, append-only. The library shows a real Sharpe instead of "not measured" |
| T-3616 | **Best-of-N is a biased estimator, so the N travels with it** | DONE — `Best` carries `runs` alongside the figure, enforced by the type rather than by discipline: a caller cannot take the number and leave the count. `is_a_maximum` is False for a single run, because one run is a measurement and there was nothing to select from |
| T-3617 | A re-run must not inflate the attempt count | DONE — runs are keyed by (strategy, tier, window, data version, params). Identical configs supersede; otherwise running one backtest ten times would report ten configurations and punish a re-run as a new idea |
| T-3618 | A run with zero fills is not a result | DONE — excluded from the maximum entirely. It never traded, usually a window shorter than the lookback; letting it win a max is absurd and letting it lose one is equally wrong |
| T-3619 | Cache hits were producing no stored result | FIXED — recording lived inside `compute`, which a cache hit never calls, so a cached strategy kept showing "not measured" for something that had demonstrably run. Now recorded from the outcomes |
| T-3625 | Equity curves persisted so the library can draw a run | DONE — `engine.equity` downsampled to 64 points, stored with the result. A curve is an output, so not part of the configuration hash |
| T-3626 | Deploy preflight answers "why not" instead of throwing | DONE — `/api/deploy/preflight`, seven real checks. Nothing passes the evidence check today and that is the check working: no mechanism promotes to `forward_testing` (T-3311), and a screened-only strategy has no business sending orders |
| T-3627 | `/api/data` counts what is on disk | DONE — panel coverage from the panel, landing figures from walking the directories. A missing source reports missing, never its intended size |
| T-3628 | **Results mirrored to the bucket, merged not overwritten** | DONE — ADR-042. Last-writer-wins on an append-only log deletes runs and deflates the `runs` denominator, making every result look better attested than it is. Union keyed by (configuration, at) |
| T-3629 | `configured()` disagreed with the thing it checked | FIXED — it read `os.environ` without loading `.env`, so it reported "cloud not configured" on a machine whose credentials were in `.env` the whole time. `S3ObjectStore` had always called `load_env()`; the check had not |
| T-3630 | Adding `get()` to `ObjectStore` broke every upload fake | FIXED — the upload paths genuinely never download, so `ReadableStore` extends the protocol rather than widening it |
| T-3631 | Clock skew could merge two genuine runs into one | OPEN — `at` is the writing machine's wall clock. Single-operator today; the fix is a per-machine id in the identity key rather than a timestamp (ADR-042) |
| T-3639 | **No way to see or choose which instruments a backtest ran on** | DONE — every run before this saw the whole panel and none recorded it, so a stored number was a number about nothing in particular. `universe` is now selectable, part of the configuration hash, and shown on the row |
| T-3640 | **The index cache would have served the wrong prices** | FIXED before it shipped — `_Panel.index` was keyed by the day-window alone, which was safe only while every run saw every symbol. A nifty50 run at 800 days would have handed its index to the next 800-day run over the full panel, which then has no adjusted prices for the symbols nifty50 never contained. Keyed by (window, universe). Test verified by degrading the key and watching it fail |
| T-3641 | The universe belongs in the cache key too | DONE — carried in `params`, so a nifty50 run and a whole-panel run of one strategy cannot share a cached answer |
| T-3642 | Runs record how many names actually traded | DONE — counted from the fills. Different from the universe size and more useful: `momentum_12_1` was offered 100 names on nifty100 and traded 96 |
| T-3643 | **low_volatility's 3.15 is a whole-panel number** | OPEN, and the reason the selector was worth building. Same strategy, same 1200-day window, same tier B: 3.15 across all 4,002 names, **1.28 across nifty100** — below the 1.878 bar. The panel includes rarely-traded names whose real costs the model understates, so the headline is coming from the least tradeable part of the universe. Needs deciding whether `all` should remain the default |
| T-3639 | Backtest asks what to run over, and for how long | DONE — clicking Backtest opens a dialog with instruments and period. Those are the two facts that most change a result and were the two the operator could not see when deciding |
| T-3640 | A period is shown as dates, not a day count | DONE — `/api/window`. 1200 days is 2021-10-06 to 2026-08-17, of which 253 are warmup, so 947 are traded. Calling the result "1200 days" described a period the strategy never traded in |
| T-3641 | Hand-picked instruments, not batches only | DONE — "does this work on these eleven banks" was unaskable. A custom list overrides the batch, records as `custom`, and puts the list in the configuration hash |
| T-3642 | The library shows the latest run, not the best | DONE — operator's call, and the better statistics: a maximum over N configurations is a biased estimate of any one of them, the latest is a measurement. The best is still reported beside it so a better run does not vanish |
| T-3643 | The (i) explains the strategy from its own numbers | DONE — `top_n`, `min_names`, rebalance and lookback read off the built strategy rather than written into the page, so the description cannot drift from what the code does |
| T-3644 | **Per-instrument attribution did not add up** | FIXED — off by ₹51,196 on low_volatility. Open positions were marked at raw `PanelRow.close` while the engine marked them adjusted; a second attempt rebuilt them from an index whose symbol set did not match. Both engines now return `final_marks`. Residual is 0.00 |
| T-3645 | **The "custom" label defeated the index cache guard** | FIXED — `_Panel.index` is keyed by universe precisely so a filtered run cannot hand its index to the next one. Every custom run sharing the name `custom` reintroduced exactly that: a 4-name run poisoned a 60-name run with `KeyError: 'ULTRACEMCO'`. Custom runs now key by the hash of their symbols |
| T-3646 | A 0-fill run blamed the window when the cause was min_names | FIXED — two causes, two different fixes. A universe at or below the strategy's `min_names` leaves it holding cash, which is why `momentum_12_1` on nifty50 held nothing for three years and still reported Sharpe 0.27 |
| T-3647 | Reports: attribution, order ledger, and the metrics that do not fit a row | DONE — `reports.py`, one file per run at `reports/{strategy}/{configuration}.json`, keyed by the same hash as the result row so the two cannot drift |
| T-3648 | A mostly-idle run is flagged | DONE — a Sharpe over a series that is flat three days in four is not comparable to one from a fully-invested run. `invested_fraction` and a named warning |
| T-3649 | **Duplicate configurations from a params-key change** | FIXED — the hash mixed named fields with the free-form `params` dict, which carried `days` and `universe` again. Adding a `universe` key to params therefore split every identical re-run in two, inflating the denominator the selection-bias correction rests on. Now built from named fields only, with `instruments` lifted out by name, and `distinct()` recomputes rather than trusting the stored value — so rows written under the old definition regroup correctly without rewriting an append-only log |
| T-3650 | **Instruments showed equities and nothing else** | FIXED — 20 landed crypto pairs and 14,280 fund schemes were on disk with no way to see or select them. An asset class with data and no way to reach it is the same defect as one offered without data, pointing the other way. `catalog.search` now covers all three, with an asset-class filter |
| T-3651 | `mutual_fund` is a real asset class | DONE — added to `AssetClass`. Without a name for them the picker could not offer schemes at all |
| T-3652 | A fund appeared once per ISIN, not once per scheme | FIXED — AMFI publishes a row per ISIN and a scheme has two (growth/payout and reinvestment), so every scheme code was listed twice. You backtest a scheme, not a variant |
| T-3653 | Funds and crypto carry a name and a detail line | DONE — `119551` tells nobody anything. Search matches name, AMC, ISIN and code |
| T-3654 | Run tab uses the same period and instrument logic as Backtest | DONE — same `/api/window` endpoint, so the two surfaces cannot describe one run differently |
| T-3655 | The standing yellow caveat blocks are gone | DONE — operator's call. The boilerplate ones are removed and their facts moved to tooltips (the bar's `assumed` tag carries `bar_note`; the sort control carries the selection warning). Run-specific findings — the report's idle-run flag, the cloud config status — stayed, as plain text rather than blocks |
| T-3656 | **Crypto and mutual funds are runnable** | DONE — `alt_panel` resamples both to daily `PanelRow`s and the batch path now loads the right panel per asset class. Verified: crypto 20 pairs, funds 212 schemes, equity 283 names, all three back to back |
| T-3657 | No cost model covers crypto or funds | OPEN — S-028. Those runs execute gross of costs and say so; `cost_mode` rides on the result and the report. Implementing them needs sourced Binance fee tiers and per-scheme exit loads, not invented numbers |
| T-3658 | **The index cache collided across asset classes** | FIXED — equity, crypto and fund panels all called their universe "all", so a crypto run built the entry and the next fund run was handed it: `KeyError: '139389'`, a scheme code looked up in an index of Binance pairs. Third thing `index_key` has had to learn, after the universe name and the custom-list contents |
| T-3659 | **A stale window response painted the wrong period** | FIXED — switching asset class fires a second request while the first is in flight, and equity answers in milliseconds while crypto resamples a minute archive. The older response landed last, so the dialog showed equity dates under a "Crypto" label. Both surfaces now guard with a live flag |
| T-3660 | A cash-like Sharpe is flagged | DONE — momentum on funds returned 4.9% a year at 0.73% volatility for a Sharpe of 6.49. That is arithmetic about a near-zero denominator, not evidence; the report says so and says not to compare it to an equity strategy |
| T-3661 | Data tab removed from the nav | DONE — operator's call. Mirroring still runs automatically after every backtest; what is gone is the manual pull-merge-push button and the on-disk counts |
| T-3662 | Capability matrix removed from the (i) and from Instruments | DONE — operator's call. Still reachable at `/api/capabilities`, and an unsupported (class, timeframe) still refuses at run time rather than returning an empty result |
| T-3663 | **A cached run left its report missing** | FIXED — the report is written inside `compute`, which a cache hit never calls, so "Full analysis" pointed at nothing for anything served from cache. It cannot be cached with the outcome (86 KB of fills against a few hundred bytes of numbers), so a missing report now forces a recompute of that item alone — self-healing, and it costs exactly what a cache miss would have |
| T-3664 | **A crypto result rendered under an "equity" tag** | FIXED — the row showed the class the strategy is *declared* for, not the one its latest run was *pointed at*. `buy_and_hold` is declared equity and its latest run was 20 crypto pairs. The row now shows the run's class, and flags `no costs` when no cost model covered it |
| T-3665 | A TASKS.md row was corrupted by an anchored replacement | FIXED — T-3613's old text was left appended to T-3638 as a fourth column |
| T-3666 | The (i) explains the rule with a worked example | DONE — five made-up names, their scores, and the cut line showing what gets bought. Built server-side from the strategy's own `top_n` and rebalance cadence so the prose cannot drift from the code, and labelled an illustration wherever it renders: a diagram of a rule is not evidence and must never be read as one |
| T-3667 | The (i) shows what the strategy actually held | DONE — best and worst contributors from the stored report of a real run, beside the illustration and explicitly distinguished from it. `momentum_12_1`: CUPID +₹1,83,072, TVVISION −₹1,15,599 |
| T-3668 | The (i) explains what the Sharpe means against the bar | DONE — in plain terms, with this strategy's own numbers, including that the bar is not zero and rises as you search |
| T-3669 | Dialog text was reading at half width | FIXED — the 68ch measure is right for a page, where a paragraph sits in a column beside other things. In a 940px dialog it left half the panel empty and read as a layout bug rather than as typography, so it is lifted inside dialogs only |
| T-3670 | **Ten intraday signals coded from post-2023 papers** | DONE — `intraday/papers.py`, each carrying its citation and the paper's own verdict. Nine come from Mesfin (2026) arXiv:2605.04004, one from Zarattini, Barbon & Aziz (2024) SSRN 4729284. Specs at H-0003 and H-0004 |
| T-3671 | **The scanner was counting one move thirty times** | FIXED — it stepped forward two bars after a fill, so a condition that stays true (an opening-range breakout is "price is above the range high") re-fired all afternoon. 1,300 trades across 43 sessions on one symbol and a 150% two-month return. These are day-trade signals: one setup, one trade, flat at the close. The H-0003 red flag predicted exactly this class of bug |
| T-3672 | Ten papers were not reached; four were verified | OPEN — SSRN returns 403 to automated fetching and three of the four are SSRN working papers. Mesfin was retrieved in full; Zarattini's ORB rules came from two independent secondary sources that agree; *Beat the Market* was **not coded** because its noise-boundary formula was never obtained, and a guessed formula attributed to a named paper is worse than an absent strategy |
| T-3673 | The exits are not the papers' exits | OPEN — Mesfin measures a fixed-horizon return; this engine is a bracket with a stop and a forced session close. Different strategies over the same signal, so nothing here may be read as a replication of his tables |
| T-3674 | Long-only, so every short variant is mirrored or absent | OPEN — `bracket.run` opens BUY and closes SELL. Mesfin's ORB short is -3.45 against long +2.82, so the long-only view is a different picture rather than half of one |
| T-3675 | No LOB paper is implementable | OPEN — the 2024-26 intraday literature is dominated by deep learning on order-book data and this platform has minute OHLCV. The operator has offered to fetch missing data; this is the one case that is a vendor purchase rather than a download |
| T-3676 | **All ten paper signals are on the UI and runnable** | DONE — declared in `REGISTRY` (derived from `papers.SIGNALS`, so the list cannot drift), and the batch runner routes them to the minute-bar scanner instead of refusing. Verified end to end: `orb_breakout` on nifty50 returned Sharpe -2.88 |
| T-3677 | `is_strategy_subclass` was doing two jobs | FIXED — the UI used it as "can this run", which greyed out eleven coded strategies. It means "can this be expressed as target weights" (ADR-037), which is a different question. The fleet now carries `runnable` and `engine` separately |
| T-3678 | **Mesfin's friction ceiling transfers to Indian equities, harder** | FOUND — `orb_breakout` over 12 nifty50 names paid Rs 1,42,356 in costs on Rs 10,00,000 across 351 round trips in 120 days. That is 14% of capital in friction alone, against a strategy whose published gross edge could not clear 2 points on MNQ |
| T-3679 | **Ten signals refetched the same bars ten times** | FIXED — each signal called `store.fetch` independently, so a batch of all ten read identical candles ten times and blew the 900s job timeout. Bars for one symbol and window are the same object whichever signal asks; now read once per process |
| T-3680 | Minute bars and crypto are in the daily job | DONE — `make daily` runs `daily-minute` behind a token-freshness gate and the Binance archive, which needs no auth and so is the one intraday source that updates truly unattended |
| T-3681 | The Kite token cannot renew itself | OPEN — it expires at 6 AM and reminting needs an interactive login, so an unattended job cannot. `make kite-fresh` turns "the ingest silently did nothing" into a named failure in `daily.log`. Nobody is watching that log; a Telegram token already exists in `.env` and would close the loop |
| T-3682 | Yahoo Finance verified as a fallback, deliberately not wired | OPEN — measured today: 1m for 5 days, 5m for 1 month, 1d for 1 year on NSE symbols, no auth. Useful for continuity, useless for backfill, and a second ingest path costs a second symbol mapping, adjustment convention and quality suite. Recorded in `docs/RESEARCH/020` so the option is known |
| T-3683 | An intraday batch of all ten exceeds the job timeout | OPEN — even with shared bars, ten signals over twelve symbols and ninety days is minutes of work. The daily engine reads a prebuilt panel; this fetches and replays. A prebuilt minute panel would fix it |
| T-3684 | Papers folder, with the absences named | DONE — `docs/RESEARCH/papers/` holds Mesfin's PDF and a README listing what is **not** there and why. The three SSRN papers are unretrievable; anyone with access can drop them in and the gap closes |
| T-3685 | The (i) shows the paper and its published result | DONE — a strategy coded from a paper opens with where it came from and what that paper scored, so a result here can never be read without the prior it argues against |
| T-3686 | **FX minute bars: Dukascopy, verified and running** | DONE — direct GET, no auth, no token, back to 2016 on the first try. Ticks decode to real prices (GBPUSD 1.32443 to 1.30642 on the 2019 Brexit vote day) and resample to 1,439 minute bars with a 1.13-pip mean spread |
| T-3687 | HistData is not scriptable | FOUND — the download is a form POST to `get.php` and it returns HTTP 200 with **zero bytes**, with or without a session cookie. Not a permissions problem to work around; it needs a browser. Dukascopy needs none |
| T-3688 | **The Dukascopy throttle is per-connection, not per-IP** | FOUND, and it decides feasibility — one connection serves ~10s per request with zero 503s, sixteen concurrent returned in 4.7s total (0.29s effective). Ten pairs over ten years is 624,000 requests: 72 days serially, ~6 days at twelve concurrent. A pair-day went from ~5 minutes to 17 seconds |
| T-3689 | **The Dukascopy backfill was 40x slower than benchmarked** | FOUND — a warm test on a handful of requests said 22s per pair-day; the sustained rate over a real multi-hour run was **810s**, with SSL timeouts appearing that were absent at the start. 245 days for the full job. The per-hour URL shape was the problem, not the throttle |
| T-3692 | **FX in bulk from FXCM, one week per file** | DONE — `make fx-bulk`. All ten pairs, 2015-2026, 6,360 requests instead of 624,000. Bid and ask OHLC are published separately, so the mid and the spread are stated rather than derived from ticks |
| T-3693 | **The two FX sources agree to 0.05 pips** | VERIFIED — EURUSD 2016-06-15 landed from both and compared across 1,438 shared minutes: median close gap 0.05 pips, p95 0.25, max 1.65. Spreads differ (0.25 vs 0.37 pips) and should — different brokers quoting their own books, which is why spread is stored per bar rather than assumed |
| T-3691 | **Twelve concurrent lookups broke DNS, not HTTP** | FIXED — a steady stream of `nodename nor servname provided` from overloading the local resolver. Those days were skipped rather than landed, so the extra concurrency was buying nothing and costing coverage. Six workers, and URLError now backs off longer than an HTTP error because a resolver needs time rather than a retry. Both previously-failing days now land |
| T-3690 | FX has no cost model | DONE — superseded by T-3701. The spread is consumed: `PanelRow.spread` carries the day's median and FX is in `COSTED_CLASSES`, so it runs costed where crypto and funds still do not (S-028) |
| T-3694 | **A timed-out batch threw away everything it had computed** | FIXED — results were recorded only after `runner.run` returned, so a batch abandoned at the 900s job timeout lost every completed strategy. Ten intraday signals take longer than 900s together; seven finished, none were kept, and the library showed "not measured" for work that had demonstrably run. Each result is now durable the moment it completes, so a timeout costs only the strategy in flight |
| T-3695 | **FX backfill complete** | DONE — 34,749 pair-days, **41,352,263 minute bars**, 601 MB across all ten pairs, 2015-2026. 519 weeks absent (ISO weeks outside the trading year), 1 already held. From 245 days on the per-hour path to under an hour on the weekly one |
| T-3696 | FX bars are landed but unreachable | DONE — superseded by T-3700. `alt_panel.fx_daily` resamples them and FX is selectable and runnable end to end |
| T-3697 | **The stored FX spread could not be a spread** | FIXED — averaged (Ask-Bid) across open, high, low and close, but the highest ask and highest bid occur at different instants, so three of the four terms compared unrelated moments. Surfaced as negative spreads on real data, up to -0.375 pips: small enough to survive a casual look, impossible for a real quote. Only open and close are contemporaneous |
| T-3698 | FX stored derivations and threw away the inputs | FIXED — `Bar` now holds bid and ask OHLC as the source gives them, with mid and spread as properties. A mistake in a derivation used to cost a ten-year re-fetch; the same rule the landing zone already follows, applied where it had quietly not been |
| T-3699 | My own audit reported a 1000-pip spread that did not exist | FIXED — the check multiplied JPY pairs by 1e4 where a JPY pip is 1e-2. The data was sound; the diagnostic was wrong, and it nearly sent me hunting a corruption that was not there |
| T-3700 | **FX is a first-class asset class** | DONE — `alt_panel.fx_daily` resamples the minute bars to `PanelRow`, and FX appears in the capability matrix, the instrument picker and the run path. 3,481 EURUSD daily rows, 2015-01-04 to 2026-08-14 |
| T-3701 | **FX runs costed, unlike crypto and funds** | DONE — its cost *is* the bid-ask spread, which is measured in the landed data and carried per `PanelRow`. Charging what was observed is a different act from inventing a fee schedule, so FX is in `COSTED_CLASSES` where crypto and funds are not (S-028) |
| T-3702 | Turnover is zero for FX and funds, and that is a fact | OPEN — spot FX has no consolidated volume and a mutual fund has no traded volume at all. Any strategy screening on liquidity selects nothing there. The 0-fill diagnosis now names it, after checking `min_names` first because that cause is specific and this one is broad enough to shadow it |
| T-3703 | **2.8% of FXCM minutes are crossed at source** | RECORDED — S-029. Ask below bid at open or close, by up to a pip, spread evenly across trading hours rather than clustered at rollover, so not a session artefact. This is how aggregated broker OHLC behaves. The landed data is left exactly as served because raw data is immutable; the daily panel takes the median (positive for every pair, 0.20 to 1.05 pips) and floors it at zero, because a negative cost would pay a strategy to trade |
| T-3704 | **The disk filled during the FX ingest** | FIXED — 228 GB at 98%, 343 MB free, which broke the tool's own output writes. `make prune-local` freed 1.38 GB by deleting 16,761 files verified present in B2 at matching byte size. Anything unuploaded or size-mismatched is kept, so this is safe by construction rather than by care |
| T-3705 | FX upload to B2 in progress | OPEN — 34,773 objects, 818 MB, running at ~50 minutes after T-3709 |
| T-3709 | **The tree sync uploaded one file at a time** | FIXED — 58 objects/min, eight hours for the FX tree. A tree of many small files is bound by round trips, not bandwidth, and the throttle is per-connection exactly as the Dukascopy backfill found. Twelve concurrent uploads: **573 objects/min**, a tenfold gain and ~50 minutes |
| T-3710 | FX is stored one file per pair-day | OPEN — 34,773 objects where crypto holds 1.06 GB in 1,200 monthly files. Good for reading a single day, bad for every bulk transfer that will ever follow. Monthly files would be 1,440 objects; worth changing while the format is days old rather than after it entrenches |
| T-3706 | **The (i) shows the implementation, step by step** | DONE — the coded rule as a numbered sequence, written beside the function in `papers.py` rather than in the UI, so the two cannot drift silently |
| T-3707 | **The (i) names what the paper actually tested** | DONE — nine of the ten signals were published against MNQ *futures* and one against US equities; all ten run here on NSE equity minute bars. Where the paper's class differs from the run's, the dialog says so and says a result here is evidence about our market rather than a replication |
| T-3708 | **Capability read directory existence, not data** | FIXED — `make prune-local` empties a landing tree and leaves the directory, so existence stopped being evidence the moment pruning became a supported workflow. The matrix and the instrument picker now both require actual files, so they cannot disagree about what can run |
| T-3613 | Terminal covers only the library | DONE — Build, Run, Instruments, Live and Data are built and read real endpoints. The old workbench at `/` is still there but no longer the only way to do anything |
| T-3632 | Evidence / Runs / Trials out of the table | DONE — operator's call. None of it was deleted: it moved into the row detail and the line under the number, which already carried "best of N" at every breakpoint. Real cost: the trial count is now a click away rather than in the default view |
| T-3633 | Graph column shows the real equity path | DONE — `engine.equity` downsampled server-side. A strategy that has never run draws nothing, because a flat line is a picture of a run that did not happen |
| T-3634 | Backtest and Deploy buttons on every row | DONE — Backtest runs the same engine `make backtest` uses and refreshes the row. Deploy opens the preflight gate |
| T-3635 | **A tie on Sharpe was broken arbitrarily** | FIXED — tier A and tier B runs of `momentum_12_1` both scored 0.3324 and `max()` took whichever the dict yielded first. The winner was the older run, which predated stored curves, so the library drew no graph for a strategy that had one. Ties now break by recency |
| T-3636 | **A new outcome field could never reach a cached run** | FIXED — the cache key covered what could change the answer, not what the answer contains. Every strategy with a cached entry kept being served the older, curve-less outcome, and re-running looked like it did nothing because a cache hit is indistinguishable from a fast run. `OUTCOME_SCHEMA` now participates in the key |
| T-3637 | Headline Sharpe and graph can come from different runs | DONE — the headline prefers the ledger's validated figure; the curve can only come from the result store. When they disagree the graph's tooltip says so by name. `momentum_12_1` is exactly this case: ledger 1.27, backtest 1.80 |
| T-3638 | `/api/data` is slow on a cold panel | OPEN — the first call loads 540 MB before it can count rows. No longer user-visible now that the Data tab is out of the nav, but `/api/cloud/status` and any future caller still wait on it. A cached coverage summary would fix it |
| T-3614 | Virtualisation not yet needed | OPEN — 12 rows today. At a thousand it needs windowing, and windowed *select-all* must never include unrendered rows, because here that spends trials nobody chose |

---

## Ten published strategies (2026-08-21)

Operator asked for ten strategies from the literature. Sources in
`docs/RESEARCH/017`. Verify: `uv run pytest tests/test_strategies_registry.py`

| ID | Task | Status |
|---|---|---|
| T-3501 | Ten strategies, each citing a real paper | DONE — `backtest/published.py`. Jegadeesh & Titman, Baker/Bradley/Wurgler, George & Hwang, Amihud, Banz, Jegadeesh/Lehmann, plus three composites that cite no single paper and say so |
| T-3502 | Most are `RankAndHold` over an existing feature | DONE by design — the feature library was built from the same literature, so "implement the low-volatility anomaly" genuinely *is* "rank on `low_volatility`". Ten bespoke classes would be ten copies of one loop |
| T-3503 | The registry cannot list what it cannot run | DONE — a test asserts every declared strategy has a builder. The two are separate structures and nothing else would stop them drifting |
| T-3504 | **An IC trial does not make a strategy "backtested"** | FIXED — an `ic` entry evaluates a *feature*, not the strategy ranking on it. It had `short_term_reversal` reporting backtested because somebody once IC-screened `reversal_1m`. The trial still counts toward the bar; only the stage is withheld |
| T-3505 | `rank_and_hold` renamed to `momentum_12_1` | DONE — same strategy under its paper's name |
| T-3506 | **Screened, not validated** | OPEN — `low_volatility` screened at Sharpe 2.19 on Tier A over 800 days. That is one window, one configuration, on the screen not the engine, and it spent no trial so the ledger does not know it happened. It is **not** evidence |
| T-3508 | Crypto and funds usable as daily panels | DONE — `features/alt_panel.py`. Crypto: **36,520 rows, 20 coins, 1,826 days** (2021-08 to 2026-07), perfectly balanced. Funds: **1.36M rows, 400 direct-growth schemes, 6,988 days** (2006-2026). Every existing feature, both engines and the whole battery work unchanged |
| T-3509 | **Not the real ADR-037 fix, and says so** | OPEN — this resamples to DAILY. Anything reading a sub-daily bar still has nowhere to live: Tweezer is still not a `Strategy`, and a minute-level crypto strategy still needs the `MarketView` rewrite |
| T-3510 | Equity defaults meant "never trade" on crypto | FIXED — `min_names=50` is sized for a 250-name panel; the whole crypto universe is 20 coins, so every crypto strategy returned no positions and read as **Sharpe 0.00** rather than "never ran". Threaded through; at top 5 / min 10 they trade |
| T-3511 | `limit` sampled the alphabetical head | FIXED — AMFI issues scheme codes in order and direct plans only began in 2013, so every direct-growth scheme sits at the HIGH end. Taking the first 600 files then filtering returned **zero**, which looked like an empty dataset. Filter now precedes limit |
| T-3507 | Three strategies could not be built | OPEN — time-series momentum, crypto momentum and fund persistence need data the `MarketView` cannot express (ADR-037). Landed but unwired: 52.5M crypto candles, 21.7M NAV rows |

---

## Crypto — minute bars, top 20 by volume (2026-08-21)

Operator asked for 5 years of minute data for up to 20 coins. Verify: `make crypto VERIFY=1`

| ID | Task | Status |
|---|---|---|
| T-3400 | **Crypto backfill complete** | DONE — **20 symbols x 60 months = 1,200 symbol-months, 52,534,759 minute candles, 1.0 GB.** 1,199 downloaded, 20 absent (pre-listing months). Verified: 0 OHLC/ordering/positivity violations, 0 truncated files, 0 bad prints |
| T-3401 | Bulk archive, not ccxt | DONE — 5y of 1m bars for 20 coins is ~52,000 paginated REST calls; `data.binance.vision` is ~1,200 monthly ZIPs. ccxt is installed and remains right for the recent gap, not for the backfill |
| T-3402 | Universe measured, not listed | DONE — ranked by Binance USDT quote volume, then **filtered to coins that actually have history 5 years back**, probed against the archive. Ranking by today's volume alone returned XPL/PUMP/ACE (listed last year) and RLUSD (a stablecoin) |
| T-3403 | Stablecoins and leveraged tokens excluded | DONE — a stablecoin's USDT pair is an exchange rate between two claims on the same dollar, not a coin; `UP`/`DOWN`/`BULL`/`BEAR` are derivatives of a coin |
| T-3404 | `knowledge_time` is the bar's close | DONE — no publication lag in crypto, but a strategy at 10:00 is still *inside* the 10:00 bar. open + 1 minute |
| T-3405 | Completeness is exactly checkable | DONE — no holidays and no close means 1,440 bars a day exactly, so a missing minute is unambiguously missing. `verify_month` |
| T-3406 | Header rows and microsecond timestamps | DONE — Binance ships a header on newer months only, and switched open_time from ms to microseconds in 2025. Both detected rather than assumed; a wrong unit puts the month in 1970 |
| T-3407 | **The universe is survivorship-biased** | OPEN — these are the coins that survived to today *with volume today*; the 2021 top 20 included names now delisted. `config/universe_crypto.txt` says so in its header. Fixable once enough archive is landed to rank as-of a date (the ADR-008 approach) |
| T-3408 | The current month is not in the archive | OPEN — the monthly dump lags, so "up to today" is really "up to last month-end". `recent_gap()` names the window; filling it is what ccxt is for |
| T-3410 | **Is Binance a good source? Verified.** | DONE — `make check-crypto`. Median close difference vs Coinbase on the same minutes: **BTC 0.048%, ETH 0.048%, XRP 0.087%** — tighter than this project's own equity vendor comparison (0.181%, T-608). Zero OHLC/ordering/positivity violations across 360 symbol-months |
| T-3411 | Kraken silently ignores `since` | RECORDED — asked for 2024-01-01 it returns **2026** bars with no error. A cross-check that trusted it would report a ~70% "disagreement" that is a timestamp bug in the reference, read as "Binance is wrong". Every comparison now verifies timestamps before comparing prices, and such a venue is reported **unusable**, not disagreeing |
| T-3413 | Stale-feed detection | DONE — runs of >=30 identical closes. A frozen feed passes every OHLC bound: each bar is internally consistent, the count is right, the price just stopped. Only repetition shows it. **905 runs found** across 840 symbol-months |
| T-3414 | **Extreme-move check was miscalibrated 743x** | FIXED — first version used 15x MAD and produced **37,140 findings**, flagging ordinary 1.2% minute moves. Measured the real distribution instead: across **2,437,704 minute returns**, p50 is 0.045%, p99.9 is 0.93%, and the largest move in the whole archive is 9.16%. Threshold now an absolute 12%. **50 findings.** Identical error to T-609 on the equity side — citing that lesson in a comment did not prevent repeating it; measuring did |
| T-3415 | Large moves classified by volume corroboration | DONE — a real move brings volume and trades; a bad print does not. Verified against NEARUSDT 2021-12-15 04:00, a +73% minute: volume went 500 -> 4,097,436, trades 22 -> 40,691, price held ten minutes. **All 55 large moves are corroborated. Zero isolated** — no bad prints in the archive |
| T-3416 | **Truncated files were indistinguishable from landed ones** | FIXED — `land_month` wrote straight to the final path, so an interrupted download left a truncated file exactly where a complete one belongs, and `if path.exists()` skipped it forever. Now writes to `.partial` and renames atomically. `is_readable()` and `repair()` added; a full scan found 0 truncated |
| T-3412 | BNB has no independent reference | OPEN — Coinbase does not list BNB, so it cannot be cross-checked. Reported as unusable rather than silently skipped. Same will apply to any Binance-only listing |
| T-3409 | Crypto costs are unverified | OPEN — A-006: 30% VDA tax, 1% TDS, no loss set-off, all from a secondary source. **This decides whether high-turnover crypto is viable at all**, so it is a cost input, not paperwork |

---

## Integrated from TradeMaster (2026-08-20)

Source: `~/Documents/TradeMaster_Avneesh` (2CentsCapital). Verify: `make montecarlo`.

| ID | Task | Status |
|---|---|---|
| T-3101 | Monte Carlo resampling added to the battery | DONE — ADR-034; the battery had no path-risk test |
| T-3102 | Resample returns, not prices | DONE — holds decisions fixed; costs no backtest |
| T-3103 | Shuffle and bootstrap reported separately | DONE — shuffling cannot move the Sharpe; a test asserts it |
| T-3104 | Unit bug: drawdowns stored as percentages | DONE — printed -2258.9% and inverted the verdict; now stored as fractions |
| T-3105 | Costs no trial | DONE — resampling an existing result evaluates nothing new |
| T-3106 | momentum_12_1 bootstrap 5th percentile is -0.96 | OPEN — over 700 days the data cannot rule out zero edge |
| T-3107 | Kelly position sizing from TradeMaster's risk_management | OPEN — EulerLab is equal-weight only; next candidate to port |
| T-3108 | Walk-forward optimiser (`playground/wfo.py`) | OPEN — CPCV covers most of this; evaluate overlap before porting |
| T-3109 | TradeMaster broker adapters | OPEN — relevant to Sprint 29; patterns only, not code (it wraps backtesting.py) |

---

## The workbench — UI, AI authoring, documentation (COMPLETE 2026-08-20)

Not a numbered sprint in the build plan; requested by the operator. Verify:
`make verify` (7 of 7) · `make workbench` then author a strategy three ways.

| ID | Task | Status |
|---|---|---|
| T-3001 | Sandbox: pasted code runs without discarding the lookahead firewall | DONE — ADR-032; allowlisted AST + attributes + builtins |
| T-3002 | Every classic escape closed and individually tested | DONE — 35 adversarial tests, deny-by-default |
| T-3003 | Unavailable names refused at submit, not as a NameError mid-run | DONE — name resolution in `check()` |
| T-3004 | Provider-agnostic model client; default local and free | DONE — ADR-033; Ollama, no key, no quota |
| T-3005 | Model output validated before it can run | DONE — hallucinated features refused by name |
| T-3006 | FastAPI service reusing the engine unchanged | DONE — optional `web` extra, not a core dependency |
| T-3007 | The API cannot spend a trial or reach the gate | DONE — no ledger-writing route exists |
| T-3008 | Caveats travel in the payload, not the page | DONE — a result without its warnings is the worst artefact here |
| T-3009 | Next.js workbench: describe / compose / code | DONE — `make workbench` |
| T-3010 | `docs/ARCHITECTURE.md` — components and mathematics for a newcomer | DONE — 949 lines, every formula matched to the implementation |
| T-3011 | Sandbox has no CPU limit | OPEN by design — S-021; external timeout is the real protection |
| T-3012 | Ollama not installed on this machine | OPEN — Describe tab reports it; Compose and Code work regardless (S-022) |
| T-3013 | Web UI has no authentication | OPEN — binds to localhost only; revisit before it leaves this machine |

---

## Sprints 19-28 — the order path (COMPLETE 2026-08-20)

Verify: `make verify` (7 of 7) · `make chaos` (11 of 11) ·
`make attribution FRICTIONLESS=1 DAYS=800` (gap must be exactly 0.00)

| ID | Task | Status |
|---|---|---|
| T-1901 | Order state machine as a table, not `if` statements | DONE — ADR-028 |
| T-1902 | `UNKNOWN` is a real state; only a query leaves it | DONE — asserted over the whole table, not over examples |
| T-1903 | `UNSENT` distinct from `REJECTED` | DONE — one the exchange never saw, one it refused |
| T-1904 | A broker can reject synchronously inside the send | DONE — `INTENT -> REJECTED`; **found by a failing test, the table was missing it** |
| T-2001 | Write-ahead journal: intent fsynced before the network call | DONE — ADR-029 |
| T-2002 | Torn final line dropped, mid-file corruption raises | DONE — a damaged journal must never read as an empty one |
| T-2003 | Sequence numbers detect a deleted event | DONE — chose this over a hash chain; see the module docstring |
| T-2004 | Idempotent submit on the deterministic client order id | DONE — two-deep: our records, then the broker's duplicate rejection |
| T-2005 | Recovery makes every non-terminal order `UNKNOWN`, then asks | DONE — including `ACKNOWLEDGED`, which is a stale cache after a crash |
| T-2006 | A broker denying an order we have fills for is a BREAK, not a resolution | DONE — refuses both readings, escalates to a human |
| T-2101 | Rate governor: a sliding window, not a token bucket | DONE — a bucket permits 10 inside 200ms across a boundary |
| T-2102 | `max_orders_per_second` read from config, not a literal | DONE — a test asserts it comes from `config/execution.yaml` |
| T-2103 | Injected clock so the limit is testable without sleeping | DONE — 37 sends checked against every one-second window |
| T-2201 | Reconciler: four break kinds, worst first | DONE — `broker_only` is the dangerous one |
| T-2202 | Reconciliation places no orders, ever | DONE — ADR-030; there is no flag to enable it |
| T-2203 | Local positions derived from the journal, not from memory | DONE — the comparison must be against post-restart state |
| T-2301 | Kill switch: anything may trip, almost nothing may clear | DONE |
| T-2302 | No importable reset function; clearing needs `KILLSWITCH_TOKEN` | DONE — test asserts no other module in `src/` names the variable |
| T-2303 | Automatic limits: loss, order count, rejections, position, unresolved | DONE — `config/killswitch.yaml` |
| T-2304 | The first trip reason survives later trips | DONE — later ones are consequences of having stopped |
| T-2305 | An unreadable trip file still reads as tripped | DONE — failing to parse must never mean "clear" |
| T-2401 | `BrokerAdapter` protocol; three send outcomes, three exception types | DONE — `BrokerUnreachable` is the honest default |
| T-2402 | `PaperBroker` with its own durable state file | DONE — a dict inside the OMS would make every reconciliation test circular |
| T-2403 | Fault injection: recorded-then-raised vs raised-without-recording | DONE — identical at the call site, opposite truths |
| T-2404 | Chaos suite, two scenarios `SIGKILL` a real subprocess | DONE — `make chaos`, 11 of 11, and in `make verify` |
| T-2501 | `plan_orders` extracted so backtest and paper share one implementation | DONE — golden file unchanged, so the refactor moved no behaviour |
| T-2502 | Fill step is a pluggable `Executor` | DONE — ADR-031; paper is the same loop with one component swapped |
| T-2503 | A frictionless paper run reproduces the backtest **exactly** | DONE — `gap == 0.00`, asserted as equality not tolerance |
| T-2504 | An ambiguous send is resolved mid-run, not at next start-up | DONE — **found by a failing test**; a timeout now costs nothing |
| T-2601 | Reality-gap decomposition into five named causes | DONE — `make attribution` |
| T-2602 | The decomposition closes to the paisa | DONE — checked against 0.01 rupees, not 10% |
| T-2603 | State plainly that the residual is an identity, not a measurement | DONE — S-018; both books are ours |
| T-2604 | Live reality-gap residual under 10% | **NOT DONE — impossible before Sprint 29.** Needs a real counterparty. The machinery exists and is verified against a case where the true answer is known |
| T-2605 | Live Kite order adapter | DONE (unexercised) — `broker/kite.py`, ported from `~/Documents/Trade`'s working Kite code. Satisfies `BrokerAdapter`, asserted as a typed binding so mypy checks it. 21 tests, all against fakes. **Never run against the live API** |
| T-3336 | Kite adapter has never met the real API | OPEN — the tests prove contract conformance, not that Kite accepts these calls. Needs a market session and credentials. The riskiest untested part is the rejected/unreachable split: it keys off substrings in Kite's error text |
| T-2606 | `ACKNOWLEDGED` / `PARTIALLY_FILLED` exercised by a real venue | OPEN — modelled and unit-tested, never produced by the paper broker (S-016) |
| T-2607 | Kill-switch limits set from an observed distribution | OPEN — A-018; needs ~4 weeks of paper history |
| T-2608 | Decide whether `config/killswitch.yaml` becomes operator-owned | OPEN — operator decision, question 1 in the review |
| T-2609 | **A trial was spent by accident during end-to-end testing** | RECORDED — running `make gate H=H-0001` to check the command still works logged ledger entry #19, a second evaluation of an already-killed hypothesis. The count went 18 -> 19 and the noise bar went Sharpe 1.83 -> 1.88, for every future candidate. There is no un-spend function and there should not be. `make acceptance` therefore excludes every command that writes to the ledger, and says so in its docstring |
| T-2610 | `make acceptance` — every sprint's capability on the real data | DONE — distinct from `make verify`, which only proves the repository is healthy |

---

## Sprints 16-18 — the research agent loop (COMPLETE 2026-08-19)

| ID | Task | Status |
|---|---|---|
| T-1601 | Codegen composes vetted primitives, never writes Python | DONE — ADR-027; `exec` would discard Sprint 4's firewall |
| T-1602 | An unknown primitive raises rather than being skipped | DONE — else a card is judged on a different set than it registered |
| T-1603 | Critic reviews before a trial is spent, reading no price data | DONE — outcome-peeking is how a trial gets laundered |
| T-1604 | Critic is advisory and cannot kill | DONE — heuristics must not hold a veto |
| T-1605 | Orchestrator weekly report: tested, passed, killed, and **why** | DONE — `make research` |
| T-1606 | Gate verdicts read from the ledger, not tracked separately | DONE — the report cannot drift from the evidence |
| T-1607 | New strategy shapes need hand-written primitives | OPEN by design — the brake is intentional |
| T-1608 | Critic raised no blocker on H-0001, which the gate killed | OPEN — one data point, wrong direction; revisit after more reach the gate |
| T-1609 | Run the loop end to end on a registered hypothesis | OPEN — needs T-1317 first; the critic objects to H-0002 |

## Sprint 15 — paper scout and hypothesis cards (COMPLETE 2026-08-19)

| ID | Task | Status |
|---|---|---|
| T-1501 | `make scout` prices a search before running it | DONE — ADR-026; 20 more hypotheses moves the bar 1.83 -> 2.16 |
| T-1502 | Hypothesis cards as specs with mandatory red flags | DONE — hedges rejected by the validator |
| T-1503 | Cards refuse to overwrite; ids never recycled | DONE — a pre-registration is not rewritten |
| T-1504 | A card without a real source is refused | DONE — CLAUDE.md forbids inventing one |
| T-1505 | H-0002 drafted from real NSE literature | DONE — research note 014; **draft, not registered** |
| T-1506 | Decide how many hypotheses the loop should generate | OPEN — operator; 20 makes the bar 2.16 vs our best 1.27 |
| T-1507 | Register H-0002, or wait for T-1317 | OPEN — operator; its own red flags argue for waiting |

## Sprint 14 — promotion gate (COMPLETE 2026-08-19)

| ID | Task | Status |
|---|---|---|
| T-1401 | `mandate.yaml` — operator-owned thresholds, no logic | DONE — **hands off from here** |
| T-1402 | `gates.py` — logic only, no thresholds | DONE — ADR-025; a test asserts no literal thresholds |
| T-1403 | Acceptance: 3 overfit strategies, all killed | DONE — noise, regime, lookahead; all KILLED |
| T-1404 | The regime stress can be slipped past | OPEN — `RegimeFit` retained 76%; split is at the midpoint only |
| T-1405 | Holdout: one read, refused on KILL and when spent | DONE — no un-spend function exists |
| T-1406 | Gate decisions written to the trial ledger | DONE — a resubmission under a new id is visible |
| T-1407 | Exercise the PROMOTE path with a known-good synthetic candidate | OPEN — the gate has never promoted anything |
| T-1408 | Formally mark H-0001 killed | OPEN — operator decision; the gate has said KILL |

## Sprint 13 — overfitting battery (COMPLETE 2026-08-19)

| ID | Task | Status |
|---|---|---|
| T-1301 | CPCV with purge + embargo | DONE — 15 paths, leakage asserted per path |
| T-1302 | Deflated Sharpe, MinBTL, expected-max-Sharpe | DONE — all take the trial count as required |
| T-1303 | PBO | DONE — **53.3%, worse than a coin flip** |
| T-1304 | Tamper-evident trial ledger | DONE — ADR-023; battery refuses to report on a broken chain |
| T-1305 | Holdout reserved and structurally unreachable | DONE — 2025+ never read |
| T-1306 | `hypotheses/H-0001.yaml` with red flags declared in advance | DONE |
| T-1307 | `make validate` + hash-signed evidence pack | DONE — JSON not PDF |
| T-1308 | Fix the leakage check (condemned 14 of 15 correct paths) | DONE — measured the filtered timeline, not the real one |
| T-1309 | 14x engine speedup via strategy-declared lookback | DONE — 95s to 6.9s, byte-identical output |
| T-1310 | Investigate excess kurtosis of +101 and +161 | DONE — led to the raw-price marking bug below |
| T-1313 | Panel stores raw prices + instrument key; guard against silent no-op | DONE — panel rebuilt, 2,869 days |
| T-1314 | Point-in-time adjustment for signals, consistent series for marking | DONE — phantom P&L removed |
| T-1315 | Re-run the Sprint 13 battery on corrected prices | DONE — PBO 53.3% -> **60.0%**; verdict unchanged |
| T-1316 | Re-run Sprint 10/11 backtests on corrected prices | DONE — momentum +16.8% ann. vs buy-and-hold +4.6% |
| T-1317 | Re-run the Sprint 8 IC sweep on corrected prices | OPEN — IC figures still come from raw prices |
| T-1318 | Hoist the adjusted-price index out of `run()` | DONE — but only 1.6s of 16s; the loop dominates |
| T-1319 | Parallelise the CPCV sweep | OPEN — 150 independent backtests, ~40min serial |
| T-1311 | Stress tests | DONE — costs, staleness, concentration, regime. **Regime split: Sharpe 0.49 vs 1.48** |
| T-1312 | Decide H-0001's fate (CLAUDE.md: a failed strategy is dead) | OPEN — operator decision |

## Sprint 12 — backtester self-tests (COMPLETE 2026-08-19)

| ID | Task | Status |
|---|---|---|
| T-1201 | Accounting invariants checked per event | DONE |
| T-1202 | Zero alpha = exact cost drag | DONE — loses Rs 78,113.65, matching fees to the paisa |
| T-1203 | Known-alpha recovery | DONE — recovers 67.4% of a planted 67.8% |
| T-1204 | Determinism, both engines | DONE |
| T-1205 | Golden file on a synthetic world | DONE — stable as real data grows |
| T-1206 | Mutation suite: prove every check can fail | DONE — **found a hole in the gate** |
| T-1207 | Independent cost recomputation | DONE — added because doubling fees passed the cost-drag check |
| T-1208 | `make verify` runs the engine gate | DONE — now 6 of 6 |
| T-1209 | Fix Sprint 8's null anchor | DONE — was non-deterministic *and* not a true null (t=4.7) |
| T-1210 | Property-based testing (Hypothesis) | OPEN — the assigned reading; example-based tests only find imagined bugs |

## Sprint 11 — Tier B event-driven backtester (COMPLETE 2026-08-19)

| ID | Task | Status |
|---|---|---|
| T-1101 | Order/Fill/Rejection/Portfolio vocabulary | DONE — `backtest/events.py` |
| T-1102 | Event-driven engine, same `Strategy` unadapted | DONE — `backtest/event_driven.py` |
| T-1103 | Deterministic client order ids + `algo_id` from day one | DONE — retry cannot double-send |
| T-1104 | Reconciliation against Tier A | DONE — **8.05e-16 relative over 1,587 days** |
| T-1105 | `make backtest` | DONE — runs both and reconciles every time |
| T-1106 | Extend panel to 2015 | DONE — 1,841 days; **overturned Sprint 10's conclusion** |
| T-1107 | Re-run the Sprint 8 IC sweep on the 11-year panel | OPEN — all Sprint 8 conclusions used the 3-year window |
| T-1108 | Limit/stop orders, partial fills | OPEN — lifecycle supports them; nothing needs them yet |

## Sprint 10 — Tier A vectorised backtester (COMPLETE 2026-08-19)

| ID | Task | Status |
|---|---|---|
| T-1001 | One `Strategy` interface, engine never learns a strategy name | DONE — ADR-021 |
| T-1002 | Vectorised engine, next-bar fills, one cost path | DONE — `backtest/vector.py` |
| T-1003 | `cost_mode` realistic/replication | DONE — borrowed from the reference system |
| T-1004 | Buy-and-hold control | DONE — +10.1% ann., -20.0% DD; the engine's sanity anchor |
| T-1005 | `make backtest-fast` | DONE — ~25s |
| T-1006 | Fix silent zero-valuation of non-trading holdings | DONE — had manufactured a -50% drawdown |
| T-1007 | Liquidity screen on rank strategies | DONE — default off so the naive result stays visible |
| T-1008 | Market impact model | OPEN — deferred to Tier B where fills are explicit |
| T-1009 | Extend panel to 2015 before interpreting drawdowns | OPEN — now blocking interpretation (T-807) |

## Sprint 9 — cost model (PARTIAL 2026-08-19)

| ID | Task | Status |
|---|---|---|
| T-901 | Research Indian transaction costs from sources | DONE — research note 013, every rate sourced and dated |
| T-902 | Time-versioned rate schedule | DONE — ADR-020; futures STT 4x across the window |
| T-903 | Itemised per-leg cost model | DONE — sides modelled, GST on fees not turnover |
| T-904 | Resolve A-005 (STT on exercise) | DONE — **the playbook was wrong since 2019**; both rules implemented |
| T-905 | `make check-costs` acceptance gate | DONE — 4 green, 1 PARTIAL pending contract notes |
| T-906 | **Reconcile against 20 real contract notes** | BLOCKED — needs the operator; `config/contract_notes.example.json` is ready |
| T-907 | Slippage and square-root impact | OPEN — deferred to meet the backtester |
| T-908 | Verify pre-2024 F&O rates were contemporaneous | OPEN — A-016 |
| T-909 | Verify the rest of A-005 (cash settlement, physical delivery) | OPEN |

## Sprint 8 — feature library and IC harness (COMPLETE 2026-08-19)

| ID | Task | Status |
|---|---|---|
| T-801 | Adjusted price panel, cached and resumable | DONE — 892 days, 3,331 symbols, 2.0M rows; joins on InstrumentId |
| T-802 | Ten seed features, pure functions of their own history | DONE — signs normalised so higher is always better |
| T-803 | Rank-IC harness through the lookahead firewall | DONE — ADR-019 |
| T-804 | Harness calibrated at both ends | DONE — oracle feature scores exactly 1.0, noise ~0 |
| T-805 | Tear sheet with t-stat, hit rate, per-year breakdown | DONE — `make ic`, 75s |
| T-806 | Append-only trial counter | DONE — started now, not in Sprint 13, per ADR-019 |
| T-807 | Extend the panel to 2015 | OPEN — ~1,980 B2 downloads; 2023-2026 is almost all bull market |
| T-808 | Factor neutralisation (size, liquidity) | OPEN — the assigned reading covers it; harness does not do it yet |
| T-809 | Fundamental features | OPEN — screener.in data has no per-field knowledge_time |
| T-810 | Apply the overlap correction to the t-statistic | OPEN — described in the tear sheet, not applied; part of Sprint 13 |
| T-811 | Independence clustering of the IC sweep | DONE — 10 features are ~3 findings; printed automatically |

## Sprint 7 — options quality (PARTIAL 2026-08-19)

| ID | Task | Status |
|---|---|---|
| T-701 | Option chain model from F&O bhavcopy, both eras | DONE — reuses Sprint 3 contract identity |
| T-702 | Put-call parity against the same-expiry future | DONE — forward implied from the chain, no rate assumed |
| T-703 | Strike monotonicity, butterfly convexity, intrinsic bounds | DONE — hard inequalities, not thresholds |
| T-704 | Calendar inversion check | DONE — WARN only; European futures options do not guarantee the textbook inequality |
| T-705 | Own IV via Black-76, bisection | DONE — 25 tests, round-trip at every moneyness |
| T-706 | Theil-Sen fit so one bad quote cannot hide itself | DONE — ADR-018; OLS was silently returning no findings |
| T-707 | `make quality-options` | DONE — cap path verified end to end |
| T-708 | Run against real F&O chains | DONE — 2 days NIFTY; **forward fit validated to 2.5pts of the actual future on 24,400 (0.01%)**; 56 lower-bound ERRORs on deep-ITM stale marks |
| T-709 | Calibrate the options tolerances | DONE — note 012. Absolute Rs 1.00 flagged 45.95% of pairs; now 2% of forward. Findings 3,161 → 782 |
| T-710 | Diagnose the DAYS=5 segfault | DONE — not reproducible in 3 runs; memory ruled out (106 MB/day). S-014 kept open honestly |
| T-711 | Build a labelled set of known-bad rows so thresholds can be optimised, not just calibrated | OPEN — note 012 |

## Sprint 6 — data quality engine (PARTIAL 2026-08-19)

| ID | Task | Status |
|---|---|---|
| T-601 | MAD-based robust statistics | DONE — ADR-017, note 011, measured not asserted |
| T-602 | Manifest checks: coverage, gaps, staleness, duplicates | DONE — zero B2 cost, runs under the cap |
| T-603 | Row checks: OHLC invariants, turnover, extreme moves, spikes, stale runs | DONE (code+tests) — not yet run on real prices |
| T-604 | Cross-source reconciliation: bhavcopy vs Kite minute bars | DONE (code+tests) — not yet run on real data |
| T-605 | Suppression by STUBS id, never by threshold | DONE — pinned per date/symbol so a new defect still reports |
| T-606 | `make quality` report with counts by severity | DONE — 0 errors on the free checks |
| T-607 | Run `make quality ROWS=...` against real prices | DONE — 634,453 symbol-days; noise cut 6,892 → 740 findings |
| T-608 | Run the cross-source reconciliation against real data | DONE — `make reconcile`; **2 disagreements in 240 symbol-days**, median vendor difference 0.181% |
| T-609 | Calibrate the spike threshold | DONE — measured on 632,133 symbol-days: old 5.0 was the *99th percentile* of ordinary trading (1.04% flagged). Now 15.0 = p99.9 |
| T-611 | Add ETF/fund corporate actions | OPEN — S-013, found by the quality engine |

## Sprint 5 — corporate actions and adjustment engine (COMPLETE 2026-08-19)

| ID | Task | Status |
|---|---|---|
| T-501 | Ingest the NSE corporate-actions feed, 2015-2026 | DONE — 12 years, 25,713 actions, real B2-synced |
| T-502 | Parse free-text `subject` into typed dividend/bonus/split/rights | DONE — 94.3% parse rate on real data, `parse.py` |
| T-503 | Price-adjustment factor engine (bonus + split) | DONE — run against full real dataset, `adjust.py` |
| T-504 | Total-return factor engine (+ dividends reinvested) | DONE, unit-tested — S-010: full historical run not executed this session |
| T-505 | Wire the adjustment engine through Sprint 4's bitemporal firewall | DONE — `factor_as_of` requires `as_of`, ADR-016 |
| T-506 | Rights-issue price effect | DONE — `P/TERP`, research note 010, A-015, 11 tests |
| T-507 | Source real corporate-action announcement dates (tighten knowledge_time past ex-date) | OPEN — ADR-016 |
| T-508 | `make build-factors` — cached, resumable full factor build | DONE — one full run completed in 3m30s |
| T-509 | Join corporate actions to bhavcopy on `InstrumentId`, not raw ISIN | DONE — was losing 21.9% of price lookups; regression-tested |
| T-510 | Re-run `make build-factors` after the ISIN-join fix | DONE — coverage 78.1% → **98.1%**, +3,073 dividend factors |
| T-511 | Read the NSE circular itself for the rights formula (currently a broker's summary) | OPEN — A-015 |
| T-512 | `make check-adjust` — the build plan's stated Sprint 5 acceptance gate | DONE — 6 checks green, 1 skipped pending S-012 |

## Sprint 4 — lookahead firewall (COMPLETE 2026-08-19)

| ID | Task | Status |
|---|---|---|
| T-401 | Bitemporal read API, `as_of` required and keyword-only | DONE — ADR-014 |
| T-402 | Adversarial test suite against the firewall | DONE — 36 tests, `make test-lookahead` |
| T-403 | Wire the store to real landing-zone manifests | DONE — found the download-time defect |
| T-404 | Separate knowledge time from receipt time | DONE — ADR-015, `make provenance` |
| T-405 | Point-in-time universe guard (survivorship) | DONE — `bitemporal/universe.py` |
| T-406 | Source the real NSE publication hour per segment | OPEN — A-014, before Sprint 9 or any intraday work |
| T-407 | Persist the store to Parquet when a dataset exceeds memory | OPEN — no measured need yet |

## Sprint 0 — Scaffolding · **COMPLETE**

Verify: `make verify`

| ID | Task | Status |
|---|---|---|
| T-001 | `pyproject.toml` + uv lockfile, ruff, mypy strict, pytest, pre-commit | DONE |
| T-002 | `Makefile`: `verify` `test` `lint` `fmt` `types` `docs-check` `state` | DONE |
| T-003 | `tools/verify.py` — prints the green/red table, non-zero exit on failure | DONE |
| T-004 | `tools/docs_check.py` — src/ change without docs fails | DONE |
| T-005 | `tools/state.py` — STATE.md is machine-readable | DONE |
| T-006 | `STATE.md`, `TASKS.md` seeded through sprint 14 | DONE |
| T-007 | `docs/` tree, every type present with a worked example | DONE |
| T-008 | `.github/workflows/ci.yml` — lint, types, tests, docs-check | DONE |
| T-009 | `docs/READING/index.md` — MUST list for sprints 1–4 | DONE |
| T-010 | Compliance stubs: `algo_id`, `max_orders_per_second`, `static_ip` | DONE |
| T-011 | `docs/SPRINT_00_REVIEW.md` | DONE |
| T-012 | `.gitignore` covers `data/`, `.env`, `__pycache__`, `.venv` | DONE |

**Acceptance criteria** (from the kickoff doc):

- [x] `make verify` runs and prints a green table
- [x] **CI passes on a pushed branch** — run 32088448395, all five gates green in 13s
- [x] A `src/` change with no doc change makes `docs-check` fail — tested
      deliberately, and permanently in `tests/test_docs_check.py`
- [x] `STATE.md` describes reality in under one page
- [x] `docs/READING/index.md` has the MUST list for sprints 1–4
- [x] `.gitignore` covers `data/`, `.env`, `__pycache__`, `.venv`

---

## Sprint 1 — NSE EOD ingest · **IN PROGRESS** (backfill running)

Verify: `make ingest-eod FROM=2015-01-01`, then run it again — second run must
download nothing.

**Decided 2026-08-18:** history starts at **2015-01-01** (~11 years). Cheap to
extend later — the downloader is idempotent, so widening the range re-fetches
only the new days.

| ID | Task | Status |
|---|---|---|
| T-101 | Research NSE archive URLs + schemas → `docs/RESEARCH/002-nse-eod-sources-and-schemas.md` | DONE |
| T-109 | Source the trading calendar (holiday vs failed download) — cannot be derived from file absence | TODO — blocks T-107 |
| T-110 | Handle both bhavcopy formats: legacy (2015→mid-2024) and UDiFF (2024-01→), probing rather than hardcoding the cutover | DONE |
| T-111 | Cross-validate the two schemas on the Jan–Jul 2024 overlap window where both formats exist | TODO |
| T-112 | Review NSE's terms on automated archive access before the first full backfill (A-010) | DONE — **terms prohibit it.** Backfill not run |
| T-113 | Decide a history source given NSE's terms | DONE — operator chose to proceed from the public archive anyway (ADR-006) |
| T-115 | Run the full 2015→2026 backfill | IN PROGRESS — ~5,800 requests, ~6–7 hours, resumable |
| T-116 | `make sync-cloud` — mirror the landing zone to Backblaze B2 (ADR-007) | DONE (code) — **unwired**, needs bucket + key |
| T-117 | Create the B2 bucket and an application key, fill `config/storage.yaml` and `.env` | TODO — operator action, blocks T-118 |
| T-118 | Run the first full cloud sync and verify every checksum | BLOCKED — needs T-117 |
| T-102 | Bhavcopy + F&O bhavcopy downloader into `data/landing/`, gzipped, one file per day | DONE |
| T-103 | Idempotency: re-run downloads zero files and says so | DONE — proven on real data, 20.6s then 1.3s |
| T-104 | Resumability: Ctrl-C mid-run, restart, resumes correctly | DONE — proven against SIGKILL, stronger than Ctrl-C |
| T-105 | Rate limiting + retry with backoff | DONE |
| T-106 | Summary output: date range, fetched, skipped, rows parsed, holidays | DONE |
| T-107 | Missing-day report distinguishing "market holiday" from "download failed" | DONE — three honest states, never guesses |
| T-108 | Landing zone is immutable — files never modified after write, enforced by test | DONE — `make check-landing` |

---

## Sprint 2 — Options chain recorder · **DEFERRED** (2026-08-18, operator decision)

**Deferred in favour of finishing the equities stack first.** The reasoning
against deferring is on the record and unchanged: NSE sells no cheap historical
option-chain data, so every day the recorder is not running is a day that cannot
be bought back at any price. Measured cost of doing it: full chains at 5s is
~300-550 MB/day; **near-expiry-only is ~35-65 MB/day**, roughly a tenth, and
still captures the irreplaceable part. Worth revisiting as a background job.

The blocking research is already done and does not expire — see
`docs/RESEARCH/003-kite-feasibility-for-the-options-recorder.md`: the recorder
must be WebSocket-based, because polling the full chains takes 9 seconds against
a 5-second target.

Verify: `make recorder-status`

| ID | Task | Status |
|---|---|---|
| T-201 | **Decide the live data source** | DONE — Zerodha Kite Connect only, ₹500/mo (ADR-004) |
| T-211 | **Verify Kite permits a 5s full-chain snapshot** against its documented rate limits — A-008 | TODO — **first task of Sprint 2, before any recorder code** |
| T-212 | Confirm Kite Connect account + API key issued | TODO — operator action, has lead time |
| T-202 | Provision a Mumbai-region VPS (~₹500–900/mo) | TODO — operator action. Decided 2026-08-18: VPS, not the laptop. A laptop that sleeps or drops wifi puts unrepairable holes in the history |
| T-203 | Snapshot Nifty (NSE) + Sensex (BSE) chains every 5s, 09:15–15:30 IST, trading days | TODO |
| T-204 | Parquet, partitioned by date, **both** exchange timestamp and receive timestamp per row | TODO |
| T-205 | systemd unit, auto-restart on crash | TODO |
| T-206 | Survives a network drop and resumes without gaps | TODO |
| T-207 | Disk usage projected and logged (estimate 50–200 MB/day; confirm with real numbers) | TODO |
| T-208 | `make recorder-status`: last snapshot, rows today, gaps today, disk free | TODO |
| T-209 | Daily Telegram heartbeat so a death is noticed within a day | TODO |
| T-210 | `docs/RUNBOOKS/recorder.md` | TODO |

---

## The equities path — next up

With options deferred, sprints 3-6 need **nothing from the operator**: no VPS,
no new spending, all local computation over data already landed.

| # | Build | Verify by | Status |
|---|---|---|---|
| 3 | Security master: instruments, time-versioned lot sizes, calendars | `make check-master` | **NEXT** |
| 4 | Bitemporal read API + lookahead firewall | `make test-lookahead` | TODO |
| 5 | Corporate actions + adjustment engine | `make check-adjust` | TODO |
| 6 | Data quality engine | `make quality` | TODO |

Sprint 7 (options quality) moves to wherever the recorder lands.

## Sprint 3 — security master · **COMPLETE**

Verify: `make verify` and `make check-master` (6 of 6)

| ID | Task | Status |
|---|---|---|
| T-301 | Internal instrument id, measured not assumed (ADR-012) | DONE |
| T-302 | Time-versioned registry, `at(as_of)` returns what was true then | DONE |
| T-303 | Build from bhavcopy, streaming from B2 | DONE |
| T-304 | Symbol-change map from ISIN continuity — 580 renames | DONE |
| T-305 | Succession model: rename / merger / demerger / cancellation (ADR-013) | DONE |
| T-306 | Fix the BE-series lookup bug (4 false delistings) | DONE |
| T-307 | Refetch minute bars for 24 recovered symbols | DONE — 420 symbols, 184M bars |
| T-308 | F&O composite key (symbol, expiry, strike, right) | DONE — 28,984 contracts in 2015 and 35,089 in 2026 parsed, zero failures, zero duplicate keys |
| T-309 | Trading calendar from evidence, not weekday rules | DONE — 2,869 trading days; flags 2021-03-30 SUSPECT rather than guessing |
| T-310 | `make check-master` | DONE — 6 checks, all green, each capable of failing |
| T-311 | Verify lot-size history against a known past value (A-002) | DONE — NIFTY 50/25/75/65 read from our own bhavcopy; A-002 resolved |
| T-312 | Resolve TATACOFFEE ratio | DONE — one scheme, two legs: 1/22 + 14/55 = 3/10 exactly. Sources never disagreed |
| T-313 | Research DHANI, JPASSOCIAT successions | DONE — DHANI→IBULLSLTD (terms_pending), JPASSOCIAT delisted in insolvency |

## Sprints 4–14 — seeded scope

| # | Build | Verify by | Status |
|---|---|---|---|
| 3 | Security master: instruments, time-versioned lot sizes, broker symbology, calendars | `make check-master` → zero unmapped symbols; lot size as of any past date | TODO |
| 4 | Bitemporal read API + lookahead firewall + adversarial test suite | `make test-lookahead` → ~15 attack tests, all blocked | TODO |
| 5 | Corporate actions + adjustment engine | `make check-adjust` reproduces a known adjusted series exactly | TODO |
| 6 | Data quality engine: gaps, OHLC sanity, MAD spikes, staleness, cross-source recon | `make quality` → counts by severity | TODO |
| 7 | Options quality: put-call parity, strike monotonicity, butterfly convexity, own IV | `make quality-options` | TODO |
| 8 | Feature library + IC harness, 10 seed features | `make ic FEATURE=momentum_12_1` → tear sheet <2 min | TODO |
| 9 | Cost model: brokerage, STT (incl. exercise), stamp duty, GST, fees, slippage, impact | `make check-costs` reproduces 20 real contract notes to the paisa | TODO |
| 10 | Tier A vectorised backtester (screening only) | `make backtest-fast STRAT=demo` | TODO |
| 11 | Tier B event-driven backtester, same `Strategy` interface as live | `make backtest` | TODO |
| 12 | **Backtester self-tests** — invariants, known-alpha recovery, zero-alpha = exact cost drag, determinism, golden files | `make test-engine` — *the most important gate in the project* | TODO |
| 13 | Overfitting battery: CPCV purge+embargo, DSR, PBO, MinBTL, tamper-evident trial counter | `make validate H=H-0001` → signed evidence pack | TODO |
| 14 | Promotion gate as code + pre-registration; locked holdout, single enforced read | Feed it 3 deliberately overfit strategies; all must be killed | TODO |

**Scope only, not yet planned:** 15–18 research agent loop · 19–24 OMS/EMS,
kill switches, first broker adapter · 25–28 paper trading + reality-gap
attribution · 29–30 compliance sprint · 31 first micro-live capital (1–2%).

---

## Discovered during Sprint 0

| ID | Item | Status |
|---|---|---|
| T-013 | Push to a private GitHub repo so CI actually runs | DONE — `Avneeshwork/eulerlab`, private |
| T-017 | Bump `actions/checkout` v4→v7 and `astral-sh/setup-uv` v5→v10 (Node 20 deprecation warning on first run) | DONE |
| T-014 | Verify the ~10 OPS SEBI threshold against the primary circular (A-001) | TODO — Sprint 29, or sooner if convenient |
| T-018 | Add Dhan as a second free feed for cross-reconciliation | DEFERRED — revisit when the quality engine (Sprint 6–7) flags anomalies a single source cannot adjudicate (ADR-004) |
| T-015 | Verify current Nifty/Sensex lot sizes and expiry days against NSE/BSE circulars (A-002, A-003) | TODO — blocking for Sprint 3 |
| T-016 | `mandate.yaml` + `gates.py` — operator-owned, written **with** the operator | TODO — Sprint 14 |

| T-314 | Persist the master with a build stamp | DONE — JSONL, deterministic, `make build-master` |
| T-315 | Broker symbology map (internal id ↔ Kite token) | DONE — 71.9% of mappable equities; residual is SME listings absent from the main board |
| T-316 | Ingest SME-platform listings so the broker map reaches 100% | **SKIPPED** — operator decision 2026-08-19. SME names are illiquid and outside the tradable universe; 71.9% coverage of main-board equities is the intended scope, not a shortfall |
| T-317 | Run `make build-master --cadence daily` once, to catch renames that reverse inside a month | TODO |
