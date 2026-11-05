# TASKS — the ledger

Every task, its status, and the command that proves it. Statuses:
**TODO** · **DOING** · **DONE** · **BLOCKED** · **KILLED**

## Nightly upload never finishing (2026-11-02, HISTORY #68)

Operator: the automatic data upload stalls and never finishes.

| ID | Task | Status |
|---|---|---|
| T-4414 | `make daily` re-fetched US bars and actions from 2016 every night, rewriting ~37,500 files and re-uploading most of them, so the run took 7 hours and its upload did not finish | DONE — nightly window from the first of last month (`Makefile`), pruned months restored from B2 before merging, unchanged bars keep their first `knowledge_time` (`ingest/alpaca.py`, `tests/test_alpaca_landing.py`) |
| T-4415 | After the next `make daily` on the Mac, the `us:` upload line reports hundreds of files, not tens of thousands, and `[feed] finished` appears | TODO. Check `data/logs/daily.log` on the Mac |
| T-4416 | Operator: B2's current US bar objects carry re-stamped `knowledge_time`s (HISTORY #68a). Restore the originals from B2's older versions, or accept the stricter stamps | TODO. Operator decision; restoring is an upload |

## The agent company: departments, managers, goals, calendar (2026-11-02, ADR-123; 2026-11-03, ADR-124)

Operator: "implement paperclick agent organisation model, make each agent employee and above that assign manager which ask for work and i will be ceo who sees final work and approve"; "set goals for agents"; "add calendar of agents work in ui". Built natively, the operator's choice (research 141). On 2026-11-03: "work on organisation structure of agents, so that every agent plan their task properly and define everyday task properly and give option to add on ceo given task to different managers which allot to other agents ... keep ui organisation as family graph and on clicking them it shows their task and todays task. make everything transparent and check if all agents have capability to resolve their respective work issue"; "use both first ai then on fallback fixed"; "use groq api for ai".

| ID | Task | Status |
|---|---|---|
| T-4397 | Phase 1: `config/org.yaml`, `reports_to` on every agent, `config/company.yaml`, the Org chart and Calendar views on the AI tab | DONE — `agents/org.py`, `agents/calendar.py`; `tests/test_agent_org.py` |
| T-4398 | Phase 2: tickets with owner, parent, status and checkout in an append-only log; today's file hand-offs (data requests, doctor to engineering, lab feedback) become tickets; ticket due dates on the calendar | DONE as tasks (ADR-124): `agents/tasks.py`, `agents/work.py` (doctor code queue, doctor data refusals, research data requests); `tests/test_agent_tasks.py`. Not done: lab feedback stays a file the research agent reads; task due dates are on each agent's plan, not on the calendar grid |
| T-4399 | Phase 3: manager workers for the three heads (assign, check against a written checklist, send back at most twice, pass up); wake on assignment | DONE (ADR-124): `workers/manager.py`, Groq first and fixed rules on fallback (operator's choice, 2026-11-03); `make agents-work`. Also on 2026-11-03, at the operator's request: a blocked task gets AI help from its head (Groq), which fixes it or writes a diagnosis; Ask AI for help on the page (`unstick` in `workers/manager.py`). Not done: department budgets (each head has its own 12 requests a day) |
| T-4400 | Phases 4 and 5: the CEO desk (one packet per department per day, approve, reject, revise), weekly plans and goal reviews on the calendar, then hiring proposals and model-written summaries checked by grounding | TODO. Part done in ADR-124: your panel on the Org chart has what needs you, accept and close, send back, retry and cancel |
| T-4402 | The knowledge agent on Groq failed a live task twice on 2026-11-03 (429, then 400). Fixed by ADR-125: requests paced to 8,000 tokens a minute, 10 tools not 17, 4 rounds plus 2, a plain-text last round (research 143, HISTORY #65). Two live questions then answered in 4 requests and about 8,900 tokens each | DONE 2026-11-03 |
| T-4405 | The research agent drafted nothing for three days (HISTORY #66). Fixed by ADR-126: tolerant replies, one retry, topic-ranked reading, Crossref abstracts, every judged paper kept in the library, outcomes counted. Re-runs: momentum 2 drafted (was 0), intraday 1 (was 0) | DONE 2026-11-03 |
| T-4406 | Watch a week of research runs: how many papers are `off topic`, `nothing to read` and `not a trading idea`, and whether any skipped one was wanted (A-097). A free OpenAlex key would allow more searches a day | TODO |
| T-4407 | Research cards whose signal the library lacks were skipped by the lab every day. Engineering now codes them (ADR-127): Groq first, then Claude Opus; at most 2 a day; a pull request for you to merge; the lab then tests the card. Live: Groq coded a test card's signal green in 2 requests; refused liquidity_beta (needs market data) | DONE 2026-11-03 |
| T-4408 | Signals needing other stocks, the market or fundamentals (liquidity beta, herding) cannot be coded as one stock's own history. Decide whether features may read a dated market series (Nifty, market turnover) through the firewall | TODO. Operator decision |
| T-4409 | Order research → lab → engineering; lab tests only research ideas; agents' memory, drafts, papers and the trial ledger backed up to B2 daily (ADR-128). First backup 360 files; restore checked on the papers | DONE 2026-11-03 |
| T-4410 | Check the B2 bucket's lifecycle keeps earlier file versions (A-098), so an overwritten memory file can be got back | TODO |
| T-4411 | Operator: review research's topic list in `config/agents/research.yaml` (chosen by hand on 2026-11-03) | TODO. Operator |
| T-4412 | More paper sources and no duplicates (ADR-129): SSRN through OpenAlex, NBER through Crossref, beside arXiv and OpenAlex; one paper known by DOI, arXiv, SSRN, NBER number or near title. Live: all four returned papers; 5 drafted, 2 from SSRN, 1 from NBER; the library had no duplicates | DONE 2026-11-03 |
| T-4413 | More sources need a free key: OpenAlex (more searches a day), CORE, Semantic Scholar. Operator: create any you want and put them in .env | DONE 2026-11-03: all three keys added; OpenAlex key now read under its `.env` name; CORE and Semantic Scholar searched (ADR-131) |
| T-4417 | The data agent only graded data; uploads refused 12,107 files every night unseen; two news months held 1,552 rows B2 lacked (HISTORY #70). Fixed by ADR-132: a fixed routine every two hours 06–20 IST (re-run, upload, delete what B2 holds, merge what differs), one Groq diagnosis, `make data-merge-back` in `make daily` | DONE 2026-11-04 |
| T-4418 | Watchdog agent: failed, stuck and missed runs, requests and tokens over budget, blocked or returned tasks; token log per request (ADR-132) | DONE 2026-11-04 |
| T-4419 | Operator: five paper books are halted because their history changed (operations agent, 2026-11-03: nse_github_minervini_template, nse_github_stocks_on_the_move, india_illiquid_winners, nifty_calm_rise_overnight, india_sharpe_momentum_opt). Re-arming a book is yours (CLAUDE.md money safety); the watchdog leaves them | DONE 2026-11-04. Operator: "delete all old paper trading stopped strategies". The five halted books and the stopped Nifty calm-rise book (4e8d74) were archived to B2 (`nse/archive/deployments/retired-2026-11-04.tar.gz`, 15 KB) and deleted; the operator will start the calm-rise overnight book again later |
| T-4420 | arXiv returned nothing for "short-term reversal Indian equities" and "52-week high momentum India" (research 146): its query ANDs every word within q-fin. Try fewer required words | TODO |
| T-4421 | Crypto, FX and mutual fund NAVs grade D every run: "no landed files recorded", because their ingests write no per-file `manifest.jsonl` (the grader's fingerprint check), though B2 holds them with a SHA-256 in each object's metadata. Have those ingests write a manifest with SHA-256 and knowledge time, as the NSE ingest does; not loosened in the grader, since the grade gates backtests | TODO |
| T-4422 | Research drafted "ADR premium predicts next-day underlying stock return" from a paper on stablecoin pricing (2026-11-04): the card does not follow from its paper. It was incomplete and never tested; watch for more such drafts in the watchdog's week and tighten the drafting prompt if they recur | TODO |
| T-4403 | Operator: watch the first week of tasks split by rules (`planned_by: rules`) and say whether the fallback words route well (A-093) | TODO. Operator |
| T-4404 | Not checked: whether earlier engineering runs spent paid requests on a model failure the doctor had queued as a code error (HISTORY #64) | DONE 2026-11-03: no. Engineering ran twice (11-01, 11-02) with 0 model requests; the doctor's log holds one entry (a stalled lab run, closed) and no code queue was ever written |
| T-4401 | Operator: approve, rewrite or delete the proposed goals in `config/company.yaml` (S-058) | TODO. Operator |
## Declared sizing (2026-11-02, ADR-122, research 140)

Operator: "use equal sizing with maximum limit as deafault can be according to strategy if explicitily defined else rom models we develop."

| ID | Task | Status |
|---|---|---|
| T-4391 | `Strategy.sizing`: equal (default), strategy, inverse_vol, hrp, min_variance, applied by one `decide` in Tier A, Tier B and the paper/live runner; own-weight strategies declare `strategy` | DONE — `deploy/sizing_models.py`; `tests/test_sizing_models.py`; all 68 builders gave identical books on five dates of real data |
| T-4392 | Time-series momentum and betting-against-beta pick over 100 names with no ranking, so at small capital the fit keeps them in listed order. Give each a ranking, or block them below a capital | TODO. Operator decision |
| T-4393 | Log the 60 sizing-study runs (research 140) in the trial ledger, or record that sizing variants are not trials | TODO. Operator decision |
| T-4394 | Illiquid winners with `min_variance`: submit to the gate as its own candidate (research 140, finding 4) | TODO. Operator decision |
| T-4395 | The Nifty volatility target (two names, up to 85% in one) is capped at 84% by the capital fit in paper. Exempt index-and-cash strategies from the caps, or accept it | TODO. Operator decision |

## Capital fit and diversification caps (2026-11-02, ADR-120, HISTORY #60)

Operator: "in top 10 no stock can be more than 25%, similarly in 20 stocks no stocks more than 15% weight, in 5 stocks no stocks more than 35% ... ranking and weight allocation both should be respected while taking trade".

| ID | Task | Status |
|---|---|---|
| T-4385 | The Clenow paper book (₹50,000) held one BOSCHLTD share: the capital fit ranked by weight and cut every name below an unaffordable one. Skip that name instead, rank Clenow by its score, cap weights by book size | DONE — `deploy/sizing.py`; `tests/test_deploy_sizing.py` |
| T-4386 | After the next `make paper-daily`, the Clenow book's `intended.affordable` is above 15 and no holding is over 8% | TODO. Check on the Mac |
| T-4387 | Operator: should backtests apply the same caps? Today they run with `fit_capital=False`, so the caps change paper and live only | TODO. Operator decision |
| T-4396 | The version lock hashed memory addresses, so 40 strategies read "code changed" on every run (HISTORY #63) | DONE — `version_lock._stable`; `tests/test_desk_and_version_lock.py`. Operator: `make relock` each running paper book of those strategies once |

## Platform audit (2026-11-01, HISTORY #50 to #52)

Operator: "audit test and complete what ever we have done till now ... look over codes if they make sense if not remove them or fix them".

| ID | Task | Status |
|---|---|---|
| T-4340 | Every screen draws Sharpes against the gate's family bar, not the ledger-count bar | DONE — `search_bar.shown_bar`; `tests/test_search_bar.py` |
| T-4341 | Deflated Sharpe kurtosis term is `(excess + 2)/4` as in the paper | DONE — `tests/test_validation_statistics.py` |
| T-4342 | No test writes to `data/` or downloads NSE's company list | DONE — `tests/conftest.py` fixtures; full suite left `data/` untouched |
| T-4343 | `make install` installs the `web` extra so `make verify` passes on a fresh machine | DONE |
| T-4344 | STATE.md back to one page; README check and test counts | DONE |
| T-4345 | Check every workbench page against real data on the operator's Mac | DONE — all screens load, no console errors, every call 200; prices, FII/DII, chain and paper equity match the files; eight fixes (HISTORY #56). Not checked: raw cash/delivery/participant files (in B2 only), TradingView embeds, action buttons |
| T-4368 | Kite access token expired (`TokenException`): live quotes off and India minute bars stop at 29 Oct; FYERS not logged in | DONE 2026-11-03 for Kite: `make kite-readonly` passed (profile read, nothing sent) and `kite_minute` holds bars to 2026-11-02. FYERS is still not logged in; that stays with T-4285 |
| T-4369 | Crypto 1-minute bars two days behind; `/api/history` for BTCUSDT takes 8.8 s and AI → Data quality 2.4 s | DONE — the filler asked for no days on the 1st; day files beside month files were read twice (volume doubled, HISTORY #57); daily bars cached per file; quality graded once per 2 minutes. `tests/test_crypto_day_files.py`, `tests/test_quality_route_cache.py`. 30 and 31 Oct land on the next daily run (T-4376) |
| T-4376 | After the next `com.eulerlab.daily` run: BTCUSDT's newest bar is yesterday, and `/api/history` for BTCUSDT answers in under 2 s on its second load | DONE 2026-11-02 — 30 Oct, 31 Oct and 1 Nov landed; newest bar 1 Nov 23:59 UTC. `/api/history` for BTCUSDT: 12.8 s on the first load, 0.06 s on the second |
| T-4377 | Rerun any crypto backtest or intraday crypto paper whose window touches 1 Aug to 29 Sep 2026 and compare with the stored result (HISTORY #57) | DONE 2026-11-02, no rerun needed — the ten stored crypto reports (BTCUSDT intraday, window 1 Jun to 23 Aug) were written on 26 Aug, before the first August month file reached B2 on 9 Sep, so August came from day files only. No crypto paper deployments or scan files |
| T-4373 | The UI polls `/api/agents/activity` and `/inbox` every 2–3 s | DONE — polling was already fast only while an agent ran, but the idea lab runs 90 minutes (about 3,900 asks a run from one window, hidden tabs included). Now the AI tab asks every 5 s while busy and 30 s idle, the strip 15 s and 60 s, and neither asks while the browser tab is hidden (`web/lib/poll.ts`, `web/lib/poll.test.ts`) |
| T-4374 | Idea lab "NOW" card names a card started 57 minutes earlier, and the same card shows again 2 minutes ago | DONE — one step, read two ways: the card put the *run's* start ("started 57 min ago") beside the newest step and listed that step again below ("2 min ago"). The lab writes one `Testing <card>` step per card (`agents/workers/lab.py`). Now the step shows its own time, the run start is labelled as the run's, and the list holds only earlier steps (`web/lib/agentNow.ts`, `web/lib/agentNow.test.ts`). Not read: the Mac's `progress.jsonl` for that run (T-4378) |
| T-4378 | On the Mac, read the 2026-11-01 lab run's `progress.jsonl`: confirm each card has one `Testing` line. Two for one card would be a real repeat, not the label | DONE 2026-11-02 — the 1 Nov lab run's `progress.jsonl` has 36 `Testing` lines, each a different card; no other run repeats one. The repeat was the label (T-4374) |
| T-4390 | Info (i) popups hard to read, cut off under cards and off screen | DONE — solid background; popup portalled to `.terminal` and placed by `web/lib/placePopover.ts` (ADR-119, HISTORY #59, `web/lib/placePopover.test.ts`). Checked in a browser on every tab at 1280 and 390 px: all 16 popups reachable without data were fully on screen and on top. Not checked: popups that only appear with API data (the cloud check had no API) |
| T-4375 | Economic calendar had nothing past 31 Oct: the daily feed that fetches it was not scheduled (T-4356); it lands again on the next daily run | DONE 2026-11-02 — the daily run landed `calendar/2026-W44` (115 events, to 6 Nov). Same-minute releases in two countries (US and Canada jobs) shared a React key; the key now has the country |
| T-4346 | Review the order path, risk limits and backtester module by module | DONE — order path and loss limits (HISTORY #51); backtester (HISTORY #53, `tests/test_backtest_audit.py`) |
| T-4347 | Fake DXY rows (98.9, +0.15%) in the Mac's `data/landing/macro`, one per day `make verify` ran: decide whether readers should skip them | DONE — `macro._is_test_row`; the files stay, landing is immutable; `tests/test_macro_history.py` |
| T-4351 | OMS counted cumulative fill entries twice (HISTORY #51) | DONE — `tests/test_oms_reconcile.py` |
| T-4348 | Kite does not reject duplicate tags: make the second line of defence real (look up the tag before a retry) or remove the claim | DONE — `KiteBroker.place` checks the day's book first; `tests/test_broker_kite.py` |
| T-4349 | Recovery reads Kite's day-only order book: an order `UNKNOWN` across a day boundary must not resolve as never sent | DONE — stays `UNKNOWN` and is reported as a break; `tests/test_live_order_gaps.py` |
| T-4350 | One rate governor across processes (a lock file or one sender), so books together stay at 5 orders a second | DONE — `ems.live_governor()`, a locked shared window; the live OMS must use it when S-015 is wired; `tests/test_live_order_gaps.py` |
| T-4352 | One row, one run: the Strategies table's Sharpe and verdict come from the latest stored run (HISTORY #52) | DONE — `tests/test_strategies_table.py` |
| T-4353 | Check B2's `nse/macro/` day files for days that lost rows to a shrinking upload before 2026-11-01 | DONE — six days lost rows, all still in older B2 versions (HISTORY #54); restoring is T-4365 |
| T-4354 | Charts page: the seven TradingView macro mini-charts were blank on the Mac and the Advanced Chart refuses NSE:NIFTYBEES; draw them from our own history instead, or drop them | DONE — operator chose our own data (ADR-114) |
| T-4357 | Our chart: crosshair readout, ranges, log scale, horizontal/vertical/trend lines, indicators in panes | DONE — ADR-114; `web/lib/indicators.test.ts`; clicks checked in a browser |
| T-4358 | Save chart drawings on the server so they follow the operator between devices | TODO. If the operator wants it |
| T-4359 | Chart timeframes 1m, 5m, 15m, 30m, 1h, 4h, 1D, 1W, 1M; the embed's own interval buttons hidden for NSE, where they did nothing | DONE — ADR-114; `tests/test_history_intraday.py`, `web/lib/bars.test.ts` |
| T-4360 | Node on the Mac is 20.11; the chart-maths tests need 22.6 or newer, so `make verify` skips them there | TODO. Operator: `brew upgrade node` |
| T-4361 | Our chart drew raw daily prices: NIFTYBEES's monthly chart showed its 2019 1:10 unit split as a 90% crash. Now split-adjusted, as backtests read them (A-043); 1h/4h answers kept in memory for the day; candle buttons D/W/M so they no longer read like the 1D/1M ranges | DONE — `tests/test_history_intraday.py` |
| T-4362 | `npm install` reports 19 known vulnerabilities (1 critical) in `web/` dependencies; review `npm audit` and upgrade what is safe (Next 14.2.5 is the likely source) | DONE — Next 14.2.5 to 15.5.28 (ADR-118): 0 critical, 1 high left (from 1 critical, 8 high). Build, typecheck, lint, web tests and a browser check of both pages pass. The rest is T-4379 |
| T-4379 | The 20 advisories left in `web/`: 1 high in the PostCSS Next bundles to build our own CSS, 1 moderate in Next, 18 moderate in the ESLint 8 toolchain (dev only) | PARTIAL — PostCSS pinned to 8.5.32 under Next by an npm override (ADR-121): 0 high, 18 moderate left. The 18 are one minimatch advisory in the lint tooling, dev only, with no upstream fix (ESLint 9 and 10 and the Next lint plugins still need affected versions). Recheck when they move to minimatch >= 11.0.1 |
| T-4384 | `next dev` on the Mac listens on every interface (`*:3000`), so any device on the Wi-Fi can open the workbench and its API proxy. Bind it to 127.0.0.1, unless the operator uses it from a phone | DONE — operator: Mac only. `next dev`/`next start` use `-H 127.0.0.1`; `make api` names `--host 127.0.0.1` (already uvicorn's default). Checked: 200 on localhost, refused on the LAN address |
| T-4391 | Pruned crypto month files were downloaded again by every daily run and uploaded with a new `receipt_time`: B2 holds 15 versions of BTCUSDT's August 2026 | DONE — `land_month` skips a month already in the bucket (`tests/test_crypto_day_files.py`). The older versions stay in B2; the current objects differ only in `receipt_time` (not checked byte by byte) |
| T-4392 | `landing_reader.read("nse/...")` asked B2 for `{prefix}nse/cm/...`, but NSE files are uploaded to `{prefix}cm/...`, so every read of a pruned NSE file failed as "never uploaded" (`market_history` reads them this way) | DONE — `remote_key` makes the same `nse` special case as `prune_local` (`tests/test_prune_local.py`). Not checked: which `market_history` outputs missed days because of it |
| T-4363 | Shorts in the daily engines: both accept negative weights and hold a short overnight in cash equity, which Indian delivery does not allow, and Tier B's realised P&L books a short sale's proceeds as profit. Refuse negative weights for delivery equity, or model shorts properly (borrow, margin, P&L) | DONE — refused: both engines and the paper runner drop negative weights and count them as `refused_shorts` (`tests/test_backtest_audit.py`) |
| T-4364 | `KiteBroker.positions` reads only the `net` book. A CNC (delivery) buy moves to Kite's `holdings` the next day, so reconciling a delivery book against `net` would report every carried holding as `local_only` | DONE — each holding's `opening_quantity` plus `net`; raises when a holding's fields do not add up (RESEARCH/139, HISTORY #55, `tests/test_broker_kite.py`). Proving it on a live sale is T-4367 |
| T-4365 | Restore the six macro days B2 lost (24 Aug, 7, 14, 15, 18 and 29 Oct): write the union of each day's B2 versions, ordered by sweep time, as the current object | DONE 2026-11-01 — B2 holds the union of every version for all six days (401, 631, 157, 406, 612 and 227 rows; 29 Oct gained 17). The Mac's local copies stay short (70, 140, 105, 389, 35, 210 lines) and are read first, by the operator's choice |
| T-4366 | Reinstall the launchd jobs on the Mac: `make schedule ACTION=install JOB=...` for daily, fundamentals and the agent jobs, then `launchctl load -w` each plist (install only writes it) and confirm with `launchctl list` | DONE 2026-11-01 — loaded on the Mac (`launchctl list`) |
| T-4367 | Prove A-091 on a live account: a read-only `make kite-snapshot` of `holdings()` and `positions()`, taken before and after the operator sells 1 share of a holding, after the close and next morning; then fixtures from the record | TODO. Plan: Claude Doc "Settle how Kite shows a holding sold today"; the snapshot tool waits on the operator's go |
| T-4355 | 7–9 Oct cash and F&O bhavcopies landed 2–3 times with different checksums (price panel grade C) | DONE — cash and F&O were byte-identical; the index closes were revised by NSE; the mirror now uploads the latest and grades are per segment (HISTORY #54) |
| T-4356 | Fundamentals not fetched since 2026-10-18 | DONE — the launchd jobs were not installed; reinstalled 2026-11-01 (T-4366) |

## UI revamp (2026-10-28, ADR-102)

Operator: "now i want you to revamp all screen ui don't ask for permission and setup auto start if session credit used".
Rules for every screen (ADR-102): numbers and pictures on the page; every explanation, definition and caveat behind an `Info` (i) button, none inline; the chart type chosen for the question it answers; arrows beside red/green; the shared kit in `web/components/terminal/ui/`; fits a 390 px phone (no horizontal page scroll); a long screen split into tabs kept in the URL.
Work on branch `ui-revamp`; one screen per commit; do not push. Verify: `make verify`, then a desktop and a 390 px screenshot of the screen.
Auto-resume: `tools/ui_revamp_resume.sh` (launchd `com.eulerlab.uirevamp`, hourly) continues from the first TODO below when `data/cache/ui-revamp.active` exists and has not been touched for 90 minutes. Delete that file to stop it.

| ID | Screen | Status |
|---|---|---|
| T-4270 | Shared UI kit: `ui/` (Info, Heading, Stat, Seg, Tabs, Sparkline, Bar, Chip) used by every screen | DONE. `web/components/terminal/ui/` (Info, Heading, Stat/Stats, Chip, Seg, Empty, Move/signed, Sparkline, Bar) and `ui.css`; page subtitles and Tools card descriptions moved behind (i) |
| T-4271 | Strategies (Library) | DONE. Headline as stat tiles; Sharpe drawn as a bar against the noise bar; returns with arrows; verdict, class and column notes behind (i); drawer summary behind (i). Fits 390 px |
| T-4272 | Strategy report (BacktestReport, AdoptedReport) | DONE. Card subtitles, view introductions, reconciliation, factor-model method and paging notes behind (i): 29 paragraphs to 16 (the rest are data, warnings or actions). Fits 390 px |
| T-4273 | Live & Risk (LiveTab, RiskBook, RiskTab, PaperDeployments, deployment report) | DONE. 31 explanation lines behind (i); diversification sentence now a stat, overnight-gap warning and data notes now chips; names no longer squeezed to "…"; tab row scrolls inside itself, so the page fits 390 px (was 478) |
| T-4274 | Options (OptionsTab, OptionsTools, OptionsCharts, PayoffBuilder) | DONE. 14 explanation paragraphs behind (i); the no-arbitrage result is a chip. Fits 390 px |
| T-4275 | Charts (ChartTab, MacroBand) | DONE. ETF, TradingView, macro-source and uncharted notes are chips with (i). Fits 390 px |
| T-4284 | The Charts embed refuses NSE symbols ("only available on TradingView"), so the default NIFTYBEES chart is empty | TODO, not presentation: needs a data decision (own-panel chart as the default for NSE, or a licensed widget) |
| T-4276 | Tools hub, Strategy Builder | DONE. Tools cards with (i) (in T-4270); Builder warnings are chips (slow universe, warm-up, screening run), rule hints, slot size, stop and backtest notes behind (i); the rules read-back stays as the page's content. Fits 390 px |
| T-4277 | Research library | DONE. Paper text stays (it is the content); the single-backtest caveat is a chip, empty-state help behind (i). Fits 390 px. (An unattended run first tried it and was blocked by its PATH; fixed in `tools/ui_revamp_resume.sh`.) |
| T-4278 | Instruments, Data | DONE. Header, sync, coverage, Kite, panel, universe and cloud notes behind (i); busy and not-configured states are chips. Both fit 390 px |
| T-4279 | SIP backtester | DONE. Headline on kit Stat tiles with arrows; lump-sum comparison a chip; XIRR, day-of-month, step-up, chart key and the costs caveat behind (i) ("Upper bound" chip). 390 px screenshot not taken: the unattended run could not reach the dev server |
| T-4280 | Company page (`app/terminal/company/[symbol]`) | DONE. Main column split into Overview / Financials / Peers / News tabs kept in `?view=`; kit Stat tiles with arrows on moves and growth; the price-source, provisional-close, chart, bar, statement, peer, news, not-held and fair-value assumption notes behind (i); confidence and provisional close are chips; "Not held" is a chip list. 390 px screenshot not taken: the unattended run could not reach the dev server |
| T-4281 | Dialogs (Backtest, Deploy, Explain) | TODO |
| T-4282 | Dashboard: move its own Info/Sparkline/Dial onto the shared kit | TODO |
| T-4283 | Finish: merge `ui-revamp` into `main`, push, delete `data/cache/ui-revamp.active`, unload the launchd job | DONE 2026-10-31. PR #38 merged. The flag file and launchd job are switched off by the operator on the Mac (the agent session was not permitted to) |
| T-4305 | Agent cards on Strategies, Live & Risk and Research as compact tiles; the picked agent's card opens full width (ADR-110) | DONE 2026-11-01. `AgentStrip.tsx`, `glass.css`. Verify: open Strategies, click a tile, then click it again |

## Five Indian microstructure strategies (2026-10-28)

Operator: "code and backtest all" after the five paper-based NSE microstructure candidates and the free-data check.
Verify: `make microstructure-five`.

| ID | Task | Status |
|---|---|---|
| T-4285 | Code and evaluate repeated institutional flow, algo timing, signed order flow, five-level book pressure, and single-stock futures lead-cash | **IN PROGRESS (operator token needed)** — five fixed rule primitives and a resumable FYERS auth/fetch/normalize/backtest path are coded. The operator reports written permission for local storage/backtesting; the app ID and secret are present but today's access token is absent, so there has been no API request, futures download, or P&L result. Log in from Instruments -> FYERS (or run `make fyers-auth`), then `make microstructure-five-futures`. Strategies 1–4 still lack event/book data; micro-01 also lacks a stable institution ID in NSE's schema. The operator trades CM only and is an individual, so the NSE commercial-entity trial is unavailable. See research 123 and 125. |
## Agent faults of 2026-11-04 (HISTORY #77)

Operator: "check issue with 4 data not updating by data agent and issue faces by engineering agent now and in last 2 day no strategy passed why?"
Verify: `uv run pytest -q tests/test_agent_fixes_2026_11_04.py`; `make agent NAME=data` after a late NSE day shows "caught up after the re-run".

| ID | Task | Status |
|---|---|---|
| T-4453 | Data agent re-checks freshness after its re-runs; only what is still behind goes to the model | DONE 2026-11-04 |
| T-4454 | Nifty options also lists freshly landed local F&O files (`nse/fo/`) | DONE 2026-11-04 |
| T-4455 | Engineering agent: a check past its time limit is a failed check, not a crashed run; full suite 2,400 s | DONE 2026-11-04 |
| T-4456 | Data watch also at 22:00 IST: NSE sometimes publishes F&O after the 19:30 run | DONE 2026-11-04 (operator). `make schedule ACTION=install JOB=data-watch` reloads it |
| T-4457 | Engineering agent fits Groq's free limit: small context (rules digest, the failing function, its tests, the error) and exact edits; wider second try; then the next model | DONE 2026-11-05 (HISTORY #78). 8,600-12,600 tokens became 1,800-4,200 |
| T-4458 | The lab writes its own formula ideas again (`max_ideas: 30`, `model_ideas: 6`, the settings before 2026-11-03), beside research's cards | DONE 2026-11-04 (operator). Each idea spends trials as before |
| T-4459 | H-0041, selling the Nifty straddle at the open on expiry day, screened alive: 6.96 bps net of notional a week, net Sharpe 0.95 (both halves positive), worst day -307 bps (research 153). Decide: check fills on minute option prices, gate it (one trial), or leave it | OPEN (operator) |
| T-4460 | Backfill NSE's F&O ban list (`fo_secban`) for 2021-2024 so ban entry can be screened (research 153, idea 4); held only from 2025-10-30 today | OPEN (operator: backfill or not) |
| T-4461 | Minute-level scalping on NSE stocks and the Nifty (operator, 2026-11-05): move-vs-cost map and two pre-registered scalps | DONE 2026-11-05 — both dead: shock fade 7.69 bps gross, -4.57 net; round-number cross -2.26 gross. Index scalps cannot pay: NIFTYBEES moves 8.3 bps in 15 minutes (research 154) |
| T-4462 | Zerodha's charges page (operator, 2026-11-05) lists NSE equity transaction at 0.00307%; `costs/schedule.py` uses 0.00297% from 2024-10-01 (0.01 bps a side). Confirm with T-906's contract notes and add a dated schedule entry if NSE changed it | OPEN |
| T-4463 | Five minute-level cash rules for stocks and the Nifty at 1x, no derivatives (operator, 2026-11-05) | DONE 2026-11-05 — all five dead after costs: in-play ORB 6.32 bps gross, 52-week-high break -7.02, panic-day laggards -21.44, NIFTYBEES panic reversal -10.80, NIFTYBEES premium 4.55; a ₹1 lakh round trip is 12.24 bps (research 155) |
| T-4464 | Reduce the in-play ORB's trades to make it profitable (operator, 2026-11-05) | DONE 2026-11-05 — eight pre-registered filters (H-0050), all negative on 2021-2023; the best (top 10, volume >= 3x) lost 14.04 bps net a trade in 2024. Closed (research 155) |
| T-4465 | Five more minute-level cash rules (operator, 2026-11-05) | DONE 2026-11-05 — none passes: drift burst -13.02 bps gross; pre-holiday NIFTYBEES +8.54 net over 47 trades but negative in 2024; turn of month +0.29 net; results day -20.47 gross; Nifty burst 14 trades (research 156) |
| T-4466 | Five more cash rules on intraday persistence, volume and attention (operator, 2026-11-05) | DONE 2026-11-05 — all dead: persistence deciles 5.22 bps gross, quiet volume shock -7.71, attention at +5% 7.83, big day by volume -3.78, Nifty big day 64 trades (research 157) |
| T-4467 | Five more cash rules: Nifty expiry pinning and gamma momentum, put-call contrarian, same half-hour, overnight winners (operator, 2026-11-05) | DONE 2026-11-05 — none passes; overnight winners' daytime reversal (H-0065) made 13.86 bps gross, +1.59 net, positive before 2024 and negative in 2024 (research 158) |
| T-4468 | H-0065 is the only intraday rule whose gross edge beat the round trip. Test it as written on fresh data (holdout, read once, or forward paper), or leave it | OPEN (operator) |
| T-4469 | H-0070 (buy NIFTYBEES for the day after a month of frequent overnight-up, daytime-down Nifty days) passed the screen's both-halves rule: 100 trades, +4.08 bps net, 2023 Sharpe 0.07, 2024 1.07, t about 0.8 (research 159). Paper-trade it forward as written, or leave it | OPEN (operator) |

## Stock screener: long-term and swing models (2026-11-04)

Operator: "build a stock screener page where i can see which stocks we can buy for long term and swing trades. research on papers ... backtest it also"; "while developing models also check our top 5 models"; "weekly fundamental update is fine"; "swing trading as weekly rebalance and long term as monthly rebalance with history stores about past selection performance". ADR-136, research 150.
Verify: `uv run pytest -q tests/test_screener.py`; `make screener`; open Workbench → Screener.

| ID | Task | Status |
|---|---|---|
| T-4441 | Point-in-time annual fundamentals joined on ISIN, per-share values in each date's units; rebuilt after each weekly fetch | DONE 2026-11-04. `fundamentals/annual.py`, `make fundamentals-annual` |
| T-4442 | Six models from research 150 (H-0030 to H-0035): four long-term (monthly; Piotroski quarterly), two swing (weekly) | DONE 2026-11-04. `backtest/screener_models.py` |
| T-4443 | Screening backtests of the six, 2016-2026 (Tier B, after costs; NIFTYBEES +221%) | DONE 2026-11-04. Sharpe / return / drawdown: quality momentum 1.01 / +632% / -42%; tree ranker 0.88 / +528% / -56%; 52-week breakout 0.84 / +378% / -39%; value-momentum-quality 0.70 / +282% / -52%; Piotroski 0.61 / +232% / -70%; trend pullback 0.40 / +85% / -53%. Fundamental models carry survivorship bias. No trial spent |
| T-4444 | Screener page with the five best existing strategies, reasons per stock, and a forward history of every selection against Nifty | DONE 2026-11-04. `screener.py`, Workbench → Screener, in `make daily` |
| T-4445 | Operator: validate and gate any screener model worth it (`make validate`, `make gate`); none is promoted | TODO. Operator |
| T-4446 | Read Piotroski (2000), Asness et al. (2013) and George and Hwang (2004) in full, and SEBI's text of Regulation 33 | TODO |
| T-4447 | True publication dates for results (NSE filings) to replace the 90-day rule (A-107) | TODO |
| T-4448 | Long-term list as a fixed 70:30 blend of quality momentum and tree ranker; three pre-registered swing blends, chosen by the worse of two halves (research 151, ADR-137) | DONE 2026-11-04. Long blend Sharpe 0.98 (+575%); swing A (Sharpe momentum + Weinstein) chosen: 1.01 full, halves 0.73 / 1.18; C 0.91 (0.64 / 0.99); B 0.86 (0.55 / 0.97) |
| T-4450 | Long-term buy list = consensus of the top 5 long-term models, 3 of 5 (research 152, ADR-138); page shows one list per tab with Top 10 / 20 / All, models behind it, others folded | DONE 2026-11-04. Sharpe 0.89 (+626%, -56%); halves 0.48 / 1.33. Below each part; shown as asked |
| T-4451 | Every screener model, blend and the consensus linked to its paper in the Research Library; Strategies page lists them | DONE 2026-11-04 |
| T-4452 | Operator: the consensus's weaker half (0.48) is below the swing floor; choose whether to keep it as the long-term list | TODO. Operator |
| T-4449 | The "optimised" volatility-adjusted momentum (PBO 0.71) was left out of the blends for the paper's setting; the operator may ask for it instead | Note |

## News rules that learn, NewsData, and stock news tone (2026-11-04)

Operator: "oil one is one case there can be many case sentiment score can be wrong and if no ai tokens how it will be corrected ... knowledge base increases over time", "use different make function to uninstall", "added newsdata.io api use that if better", "show sentiment on each stock whichever possible"; "keep automatic". ADR-135, research 149.
Verify: `uv run pytest -q tests/test_news_rules.py`; `make market-news`; read "How the news scores are checked" and "Stock news" in the brief; open a company page's News tab.

| ID | Task | Status |
|---|---|---|
| T-4435 | Written news rules (13) that correct tone with no model request; rules read the stories when no judgement is made | DONE 2026-11-04. `config/news_rules.yaml`, `forecast/news_rules.py` |
| T-4436 | Learned rules from logged judgements, switched on at 3 agreeing and off at 2 against; contested seeds listed; agreement of each score reported | DONE 2026-11-04. Starts empty; grows with each brief |
| T-4437 | NewsData.io as a second source and a second score | DONE 2026-11-04. Key `News_Data_io` |
| T-4438 | News tone for each stock, in the brief and on the company page | DONE 2026-11-04. `forecast/stock_tone.py` |
| T-4439 | `make install` keeps the news model; `install-lite`, `install-news`, `remove-news` (HISTORY #75) | DONE 2026-11-04 |
| T-4440 | Review the first learned rules after two weeks of briefs | TODO. Operator, about 2026-11-18 |

## News sentiment and possible impact in the brief (2026-11-04)

Operator: "crashes will be difficult to predict and also we have not take news as input you may miss many important geopolitical and country wide news impact it need to be added in last show news sentiment and possible impact"; "IS CURRENT_NEWS_API NOT USEFUL"; "look over open source FinBert github repo". ADR-134, research 148.
Verify: `uv run pytest -q tests/test_market_news.py`; `uv sync --extra news`; `make market-news`; `make agent NAME=market_brief ARGS=force=1` and read the last two sections.

| ID | Task | Status |
|---|---|---|
| T-4430 | Market-wide and geopolitical news from Currents (Google News fallback), landed and kept in a derived table | DONE 2026-11-04. `ingest/market_news.py`, `config/market_news.yaml`, `make market-news`, in `make daily` |
| T-4431 | Tone for every relevant story from a local financial-news model (Apache-2.0, pinned); impact judged for up to 12 stories per brief, each line checked | DONE 2026-11-04. `forecast/news_tone.py`, `uv sync --extra news` |
| T-4432 | "News and possible impact" and "Crash risk" at the end of the brief, Telegram line, workbench view | DONE 2026-11-04 |
| T-4433 | Test whether news tone helps the forecast, with GDELT's tone history fetched politely or after 60 sessions of our own log; one test, rule fixed first | TODO |
| T-4434 | Optional: a NewsData.io key for a second sentiment score (48 hours, free) | TODO. Operator |

## Market brief: detailed reasons and a scored next-session forecast (2026-11-04)

Operator: "start working on how market brief can be made better and more detailed, add some forecasting element on next market session behaviour based on data we got, look over good paper which can help, and keep testing earlier day result with actual performance and keep updating model. i want detailed explanation about market and what can happen next"; "i want detailed reasons in brief instead of 1 liner only". ADR-133, research 147.
Verify: `uv run pytest -q tests/test_next_session.py tests/test_brief_content.py`; `make agent NAME=market_brief ARGS=force=1` and read "What happened in the last session" and "What can happen next session".

| ID | Task | Status |
|---|---|---|
| T-4423 | Next-session forecast: range, 80% close band, odds of a higher open and close with reasons, expected open; refitted every run; walk-forward check | DONE 2026-11-04. `forecast/next_session.py`, `config/next_session.yaml`, 12 tests. Check over 500 sessions: range error 0.32 against VIX's 0.52, band 78%, open odds skill +2.9%, close odds +0.1% (a coin flip, and the brief says so) |
| T-4424 | Every forecast logged before its session and scored after it; yesterday's forecast against the result in the brief; base rate shown when the model trails it | DONE 2026-11-04. `data/derived/forecasts/next_session.jsonl`. First live score after the 2026-11-05 close |
| T-4425 | Detailed brief: the last session in words, why each signal matters for the next session and what to watch, scenarios, a four-part analyst note; the workbench view draws them | DONE 2026-11-04 |
| T-4426 | The brief showed an expired option chain's straddle range and max pain (HISTORY #74) | DONE 2026-11-04 |
| T-4427 | Research agent searches two forecasting topics in its rotation | DONE 2026-11-04. Papers land in the library |
| T-4428 | Read research 147's sources C and D in full (fetch timed out, PDF unreadable); look for a free GIFT Nifty history for the open | TODO |
| T-4429 | After 60 live scores, re-read the forecast's card: band coverage, range against VIX, odds against the base rate (A-102) | TODO. About 2027-02 |

## Market brief: the Trader's read (2026-10-31)

Operator: "current market brief is joke and it doesn't make any sense and not helping a trade at all ... add one more component how to answer which give better clarity to trader". ADR-100.
Verify: `uv run pytest -q tests/test_trader_read.py`; `make agent NAME=market_brief ARGS=force=1` and read the top of the brief; ask the assistant "how is the market today".

| ID | Task | Status |
|---|---|---|
| T-4243 | Trader's read at the top of the brief: bottom line, scorecard with normal levels, today's map, what would change the read, books; detail cleaned; Telegram gets the read only; assistant `market_read` tool | DONE 2026-10-31. `agents/trader_read.py`, `config/trader_read.yaml`, 8 tests |
| T-4244 | Operator sets the read's thresholds (A-082) | TODO. Operator |
| T-4246 | An incomplete read says so in its first words, marks missing rows, and is held back from Telegram with one line (ADR-101) | DONE 2026-10-31. 4 tests in `tests/test_trader_read.py` |
| T-4247 | Research how a brief and agent notes should read (research 134): pre-open brief, after-close note, agent notes, Telegram, rendering | DONE 2026-10-31. Proposal only; the operator decides the four open questions before building |
| T-4245 | Show the read as its own card on the Dashboard strip and the AI tab, not only inside the brief text | TODO |

## Market brief as a morning note (2026-10-31)

Operator: "is this readable?", "not much information in market brief just data", then "start market brief work" with research 134's defaults. ADR-105, research 137.
Verify: `uv run pytest -q tests/test_brief_content.py tests/test_board_meetings.py tests/test_trader_read.py`; `make agent NAME=market_brief ARGS="force=1"`; open AI → Market brief.

| ID | Task | Status |
|---|---|---|
| T-4286 | Brief as data in reading order: what matters (ranked), levels and if-then, coming up, books needing you, underneath, after-close review; AI-tab view and agent card; Telegram in 8 lines | DONE 2026-10-31 |
| T-4287 | Results calendar from NSE board-meeting intimations (`make board-meetings`, in `make daily`) | DONE 2026-10-31. Built forward from 2026-10-31 |
| T-4288 | Closed days get a markets-closed note (last session, week in review, week ahead), once per break; `make holidays`; `brief-weekend` launchd job; after-close note moved into `make daily` | DONE 2026-10-31. HISTORY #43 |
| T-4289 | PR 2: what history says (base rates for today's conditions, with case counts) and each book's backtest in this kind of market | DONE 2026-10-31. ADR-109, `agents/history_says.py`, 5 tests; 2 metrics pages |
| T-4304 | Operator reviews the history conditions (A-087) | TODO. Operator |
| T-4290 | Operator reviews the brief's ranking weights (A-086) | TODO. Operator |

## Idea lab: many ideas daily, memory, handoff with research (2026-11-01)

Operator: "i want it to be most impactful agent which bring lot of trading ideas daily and coperate with research agent properly", "make it intelligent day by day"; approved the plan with "yes". ADR-111, HISTORY #47.
Verify: `uv run pytest -q tests/test_idea_lab.py tests/test_agent_trials.py`; then on the Mac `make agents-ideas` and open the Idea lab card.

| ID | Task | Status |
|---|---|---|
| T-4320 | Lab writes its own formula cards daily from 13 signal families (`config/idea_families.yaml`), planned by Thompson sampling, flips, combinations and window variants | DONE 2026-11-01. `research/idea_generator.py` |
| T-4321 | Lab memory of every card tested, lessons that cite it, feedback for research | DONE 2026-11-01. `research/idea_memory.py`, `data/agents/memory/lab_ideas.jsonl` |
| T-4322 | Lab reads every untested research draft, not only the latest run; research stops marking buildable drafts as waiting for data, takes its topic and lessons from the lab, and skips papers already judged not relevant | DONE 2026-11-01 |
| T-4323 | `make agents-ideas` every day 17:00 IST; install with `make schedule ACTION=install JOB=agents-ideas` and the `launchctl load -w` line it prints | DONE 2026-11-01 — loaded on the Mac (`launchctl list`) |
| T-4324 | Measure the lab's seconds per card on the full panel after the first `make agents-ideas`; set `max_ideas` and `max_minutes` from it | IN PROGRESS. First run 2026-11-01: about 3 minutes per own idea, 5 for a two-feature draft, so 90 minutes covers about 25 to 30 cards |
| T-4327 | One lab run at a time: a lock so overlapping runs cannot test, and pay for, the same idea twice | DONE 2026-11-01. RUNBOOKS/idea-lab-two-runs-at-once.md |
| T-4325 | Store the lab's backtest curves where the gate's family count and Romano-Wolf can see them (with T-4301) | TODO |
| T-4328 | Liquidity floor (Rs 1 crore) on generated cards and their IC screen; survival against Nifty; the first run's unfloored cards not learned from | DONE 2026-11-01. ADR-112, HISTORY #48 |
| T-4329 | Store which stocks each lab backtest held, so a high Sharpe can be traced to the names behind it | TODO |
| T-4326 | Families need inputs the formula language lacks (fundamentals, sector-relative ranks, calendar); each needs a tested input before a family can use it | TODO |
| T-4330 | Doctor after every agent run: close dead runs, flag too-good results, note model outages, route data refusals, queue crashes for engineering | DONE 2026-11-01. ADR-113, `agents/doctor.py` |
| T-4331 | Engineering agent fixes queued code problems on Claude Opus, one file and its test, on an `agent-fix/<id>` branch proven by lint, types, tests and the engine self-test | DONE 2026-11-01. ADR-113, `devtools/fixer.py`; merge with `make agent-fix-apply ID=<id>` |
| T-4332 | Daily code quality check (ruff, mypy, pytest) in `make agents-close`, findings queued for engineering | DONE 2026-11-01 |
| T-4333 | Measure a real fix: seconds and cost per attempt on the operator's machine, and how many come back green | TODO. After the first queued problem |
| T-4334 | Fixes that need two files (a caller and a callee) are reported, not fixed; decide after a month of the doctor log whether to allow a second file | TODO |
| T-4335 | A run that stopped (Mac asleep, app closed) shows as stopped with the last full run, not as failed | DONE 2026-11-01. `api/agent_routes._last_full_run` |
| T-4370 | Approving an idea lab survivor registers it, validates it and runs the gate, with the verdict in the Inbox | DONE 2026-11-01. ADR-116, `research/promote.py` |
| T-4371 | Watch the first gated lab survivors: time per validation on the full panel, and the PBO rule: with one configuration there is no in-card choice, so PBO reports 0 over 0 splits and passes; the search across lab cards is priced only by the family bar | TODO |

## Metrics library: how to answer (2026-10-31)

Operator: "gather all possible documents related to metrics we have train model that how to answer", "do for what all possible and before building brief". ADR-103, research 135.
Verify: read `docs/METRICS/README.md` and `docs/METRICS/HOW_TO_ANSWER.md`; open any page, for example `docs/METRICS/market/india-vix.md`.

| ID | Task | Status |
|---|---|---|
| T-4248 | `docs/METRICS/`: 116 pages in 14 families (platform metrics plus Indian and global economy, policy and regulators, institutions and flows, events, market structure), normal ranges from our data, answer rules | DONE 2026-10-31 |
| T-4254 | Hold the macro data the new pages say we lack: RBI policy rate and liquidity, CPI/WPI/IIP/GDP/PMI values, AMFI monthly flows, GIFT Nifty, forex reserves; find free official sources first (research) | TODO |
| T-4249 | Operator decides: subtract a risk-free rate in Sharpe (and so DSR and the noise bar), or keep raw returns and say so (A-083) | TODO. Operator. Touches the gate's inputs |
| T-4250 | Operator decides: enforce `min_t_statistic` in `gates.py`, or remove it from `mandate.yaml` (HISTORY #42) | TODO. Operator. Both files operator-owned |
| T-4251 | Decide whether Sortino's downside deviation should average over all days, as Sortino & Price define it (A-084) | TODO |
| T-4252 | Wire the library in: knowledge agent sources (`docs/METRICS`, `docs/GLOSSARY.md`), an `explain_metric` assistant tool; scored questions | DONE 2026-10-31. 10 cases added to `config/agent_eval/knowledge.yaml` (k-13 to k-22), not yet run live. The brief's analyst note waits for the brief rebuild |
| T-4255 | Knowledge keeper agent: daily normals and SEBI/RBI/NSE feed watch, weekly gaps and drafted page updates, `make metrics-accept` | DONE 2026-10-31. ADR-104, research 136, `tests/test_metrics_library.py` (18 tests). First run in a scratch copy recorded 94 feed items as baseline |
| T-4258 | Market Handbook: the library as one searchable page (`make handbook`, workbench `/handbook.html`), rebuilt by `make ui` and the daily agent batch | DONE 2026-10-31. `tools/render_metrics_handbook.py`, 2 tests |
| T-4256 | Watch MoSPI and AMFI: no RSS; find a readable official source (PIB RSS?) | TODO |
| T-4257 | Recheck the seven assumptions the keeper found overdue on its first weekly pass (A-000, A-002, A-004, A-005, A-008, A-010, A-019) | TODO. Operator |
| T-4253 | Review the Trader's read cash-flow thresholds: ±₹5,000 cr sits near this year's median FII 5-day net (−₹6,110 cr), so "weak" is the usual reading (A-082) | TODO. Operator |

## Researching many daily strategies (2026-10-31, ADR-106)

Operator: "make other thread of how we will research multiple daily strategy", then "start". Plan: Claude Doc "Researching many daily strategies at once" (https://claude.ai/artifact/8MDtW5qPpmb4VraqxXg1ez). Judge books, not single rules; screen many ideas for free, confirm few. Builds on the self-improving agent plan below.
Verify: `make strategy-map`; `uv run pytest -q tests/test_strategy_map.py`.

| ID | Task | Status |
|---|---|---|
| T-4291 | Phase 1: strategy map. Correlations raw and Nifty-hedged, families at 0.7, participation ratio, one fixed equal-weight book | DONE 2026-10-31. 68 strategies: 27 families, 2.78 independent bets; one family of 39 (HISTORY #44) |
| T-4292 | Operator decides the plan's seven questions: the book as the unit gated; T-4230; trial allowance split; lane D waits for 5 years; equal weight by family; 0.7 redundancy line; gate the hedged book | TODO. Operator |
| T-4293 | Phase 2: batch screen. Family and lane tags on H-cards, zero-trial filters, discovery screen and redundancy check in one run, `make research-batch` | TODO. Blocked by T-4230, T-4232 |
| T-4294 | Phase 4: book builder. Score blending, fixed weights, long-only and Nifty-hedged versions with futures costs, a book as one H-card | TODO. After T-4293 |
| T-4295 | Phase 3: delivery %, index P/E and P/B and Nifty futures as formula inputs | TODO |
| T-4296 | Phase 5: forward recorder for short-history signals (FII/DII, deals, short selling, insider), `make shadow-signals` | TODO |
| T-4297 | Phase 6: quarterly book rebuild, member drop rules, forward against backtest per member | TODO. After T-4294 |
| T-4298 | Strategy map on the workbench: families and the correlation heat map on the Strategies page | TODO |
| T-4299 | No weekly limit on agent trials (operator, 2026-10-31) | DONE. ADR-107; `uv run pytest -q tests/test_agent_trials.py` |
| T-4300 | The gate's Sharpe bar: N = families of everything tested with measured σ_SR, plus Romano-Wolf StepM over Nifty, instead of ledger rows and σ = 1.0 (research 138) | DONE 2026-10-31 by operator decision. ADR-108; `uv run pytest -q tests/test_search_bar.py tests/test_gates.py` |
| T-4303 | ONC clustering and minimum-variance family weights as in López de Prado and Lewis, compared with average linkage (S-057) | TODO |
| T-4301 | Store every configuration's daily returns, including optimiser and walk-forward sweeps, so the bar can see the whole search | TODO. Needed by T-4300 |
| T-4302 | `india_sharpe_momentum_opt` is the only strategy that passes StepM over Nifty, but its tuning runs are not in the test; re-test once T-4301 stores them | TODO |

## Self-improving research agent (proposed 2026-10-31)

Operator: "focus mostly on how we can make our research agent more intelligent, how it will improve itself ... come up with a plan." Research 131. Phase 1 built (ADR-097); the trial-counting decision (T-4230) is still open.
Verify: read `docs/RESEARCH/131-self-improving-research-agent.md`; `uv run pytest -q tests/test_features_formula.py`.

| ID | Task | Status |
|---|---|---|
| T-4230 | Operator decides: do discovery-window searches count against the gate's trial bar; window dates; paid model for proposals; trial allowance | TODO. Operator |
| T-4231 | Phase 1: formula language, the 10 features rewritten as the alpha zoo, originality score | DONE 2026-10-31. ADR-097; `uv run pytest -q tests/test_features_formula.py` |
| T-4237 | Phase 1b: more portfolio shapes (quantile long-only, sector-neutral) and a liquidity floor as cards can name them | TODO |
| T-4232 | Phase 2: discovery-only view, exploration log, pass-or-fail confirmation call | TODO. Blocked by T-4230 |
| T-4233 | Phase 3: hypothesis-first generator, originality/alignment/complexity checks, weakest-score refinement and bandit; measure cost | TODO |
| T-4234 | Phase 4: zero-trial test bench (planted signals, noise panels, known anomalies), `make agent-bench` | TODO |
| T-4235 | Phase 5: experience store, cited lessons list, graveyard | TODO |
| T-4236 | Phase 6: confirmation trials within the allowance, equal-weight composite, forward results back to memory | TODO |

## FII/DII cash flows (2026-10-29)

Operator: "make a scrapper to scrape all the data https://scanx.trade/insight/fii-dii-data which we don't have and include in dashboard". scanx could not be read and its terms are unread, so NSE's own figure is captured instead (research 128, ADR-098).
Verify: `uv run pytest -q tests/test_fii_dii_cash.py tests/test_fii_dii_history.py`; `make fii-dii` on a trading evening; `make fii-dii-history`; `make data-quality`; Dashboard → India → Big money.
Then, 2026-10-30: "get fii - dii historical data from other place then like money control or other website by scrappping them atleast last 1 year data" (ADR-099, research 127).

| ID | Task | Status |
|---|---|---|
| T-4163 | Capture NSE's FII/DII provisional cash flows daily; table with event and knowledge time; `/api/fii-dii`; panel on Big money | DONE. `ingest/fii_dii_cash.py`, `api/fii_dii_routes.py`, `FiiDiiFlows.tsx`. In `make daily`, `make india-live` and the coverage button. 18 tests. Not yet run against NSE (no network to it from the build session) |
| T-4238 | First live `make fii-dii` on the Mac; replace the hand-written test payload with the landed file | DONE (2026-10-30). 29 Oct landed; real response is `tests/fixtures/fii_dii/nse_fiidiiTradeReact_2026-10-29.json`. A-079 confirmed, S-054 resolved |
| T-4239 | Backfill FII/DII history | DONE (2026-10-30) from Trendlyne, not NSDL, by operator decision (ADR-099, research 127). `make fii-dii-history MONTHS=12`: 264 days, 2025-10-01 to 2026-10-28, plus NSE's 29 Oct. Cross-checked against NSE, Groww and stockezee: largest gap 0.05 crore. NSDL's official FPI series is still unread (T-4241) |
| T-4240 | Open scanx.trade's FII/DII page and its terms; list anything it shows that EulerLab does not hold | TODO. Not tried on 2026-10-30: the history came from Trendlyne instead. Still the only open question about scanx |
| T-4241 | Read NSDL's FPI daily report format and terms; compare its official FPI figure with the provisional one | TODO. Official, FPI only, a different figure (research 004, 065, 127) |
| T-4242 | Did NSE hold a session on Sunday 1 Feb 2026 (Budget day)? Trendlyne and stockezee show FII/DII flows for it; EulerLab has no bhavcopy for it | TODO. If it did, land that bhavcopy and re-run `make fii-dii-history`, which admits the day once the bhavcopy is in the manifest |
## Loss limits that act (2026-10-29)

Operator: "finally implement new thing which a trader need." Chosen from research 079's gaps that matter now: a reduce-only state and a drawdown rule that acts. ADR-092.
Verify: `uv run pytest -q tests/test_loss_limits.py`; Live & Risk → Deployment → a paper card's Loss limits row.

| ID | Task | Status |
|---|---|---|
| T-4201 | Reduce-only windows on a deployment; buys refused inside them on every replay | DONE. `deploy/loss_limits.py`, `ForwardExecutor` |
| T-4202 | Drawdown levels that act: reduce-only at one, halt at the other; defaults in `config/loss_limits.yaml` | DONE. A-071 |
| T-4203 | Reduce only / Resume buying and the levels on each paper card; Telegram line when a book goes reduce-only | DONE |
| T-4204 | Reduce-only on the overnight, intraday and study books | TODO (S-050) |
| T-4205 | Set the levels you would act on in `config/loss_limits.yaml` | TODO. Operator |

## Workbench redesign and live agent activity (2026-10-29)

Operator: "rewamp whole ui to make it simple easy to understand visually appealing with simple design … better solid 3-4 colours max and round corners … for ai agents shows what agent is actually doing." ADR-090, ADR-091.
Verify: `uv run pytest -q tests/test_agent_activity.py`; `make workbench` → every page; AI → Live while `make agent NAME=data` runs.

| ID | Task | Status |
|---|---|---|
| T-4195 | Four colours (blue, green, red, amber) and rounded corners across the terminal; every chart palette mapped onto them | DONE. ADR-090; `web/app/tokens.css`, `web/app/terminal/theme.css` |
| T-4196 | AI tab shows what each agent is doing now: step trail, live cards, activity feed, dot on the AI link | DONE. ADR-091; `/api/agents/activity` |
| T-4197 | `make agent` crashed for any agent that returned an item | DONE. HISTORY #34 |
| T-4198 | API failed to start on a clean install: numpy undeclared | DONE. HISTORY #35 |
| T-4199 | A place on Dashboard → Big money for the FII/DII cash flows panel | DONE by the flows work itself (PR #32 puts `FiiDiiFlows` there); its colours already read the four-colour tokens through `--mc-a`/`--mc-b` |
| T-4200 | Merge with the operator's unpushed `ui-revamp` branch | TODO. Not visible from here; may overlap `tokens.css` and `shell.css` |
| T-4206 | End-to-end walk-through of every page (synthetic panel): fix what broke | DONE. Coloured dashes for missing returns; "−0.0%"; the old orange accent on Dashboard tabs; the (i) button by "NSE" drawn as a segment; unreadable text in a selected chip; Deploy/Explain dialogs following you to other pages; a refused paper action's error vanishing; negative rupees shown as "₹-31161" |
| T-4207 | Company page shows only a notice when fundamentals are missing; first snapshot is slow when outside fetches time out; "Open Live & Risk" wraps in the deploy dialog | TODO. Seen in the walk-through, not fixed |
| T-4208 | Repeat the walk-through on the operator's real data | DONE 2026-10-30. Fixed: SIP ignored splits and bonuses (HISTORY #36); one unreachable asset class turned the whole instrument search into a 500; "The session −5.26%" was a 20-day average; deployment names in Performance showed as "…"; the live and backtest labels overlapped; gains drawn in blue; paper cards read "not measured yet" until the next run; a blocked ticket's data row read "grade D, ok"; the calendar showed a bare dash; the AI feed said no agent had run when two had |
| T-4213 | The assistant and Research Library model lists show Groq gpt-oss-120b and the Claude models only, as agreed on 2026-10-29; that work sat unpushed on a local branch, so main still showed the OpenRouter free list (operator, 2026-10-30) | DONE. ADR-095 (was numbered ADR-088 on the local branch, which clashed with the grounding check) |
| T-4212 | Agent cards say what each agent found and what to do, the skeptic picks a strategy or checks all, the idea lab says why it runs from the terminal, and the data grades are explained (operator, 2026-10-30) | DONE. ARCHITECTURE "Agents on the page they serve" |
| T-4211 | Each agent on the page it works for, with an animated icon, its last result and Run now; a guide to what each agent does (operator, 2026-10-30) | DONE. ADR-094; `AgentStrip.tsx` |
| T-4210 | Apple-style frosted glass look across the terminal (operator, 2026-10-30) | DONE. ADR-093; `web/app/terminal/glass.css` |
| T-4209 | Deployment titles on Live & Risk → Deployment show the strategy id until the strategy list loads | TODO. Seen on a cold start |

## Agent accuracy: the grounding check and agent-eval (2026-10-29)

Operator: "what will be done if model start hallucinating?" then "yes build". Research 126; ADR-088.
Verify: `uv run pytest -q tests/test_agent_grounding.py`; `make agent-eval ONLY=skeptic`; `make agent-eval` (uses the knowledge agent's budget).

| ID | Task | Status |
|---|---|---|
| T-4185 | Grounding check on knowledge answers and brief commentary; prompt fingerprints; `make agent-eval` with switch-off | DONE. 12 knowledge cases and 10 skeptic fakes. Knowledge cases not yet run live (S-047) |
| T-4186 | Grow the knowledge test set to 50 cases, 10 with no answer on disk | TODO |
| T-4187 | Record each model's training cutoff in `config/llm.yaml`; refuse to backtest a model-derived signal before it | TODO (research 126, finding 7) |
| T-4188 | Name-swap and scrambled-input cases in agent-eval | TODO |
| T-4189 | Verification questions on research drafts answered from the paper's text only | TODO |
| T-4190 | Research critic votes three times; a draft passes on 2 of 3 | TODO |
| T-4191 | Split the knowledge index into chunks with a context note each; measure recall before adding embeddings | TODO |
| T-4192 | Approve/dismiss counts per agent on the AI tab | TODO |
| T-4193 | Idea lab: test drafts within 5 trials a week (IC screen, then backtest), skeptic, inbox | DONE. ADR-089; `make agent NAME=lab`; `tests/test_agent_trials.py`. Runs Sundays after research |
| T-4194 | First real lab run on the operator's machine, after a live research run | DONE 2026-11-01: it tested 0 cards (HISTORY #47); fixed by T-4320 to T-4322 |
## Market microdata: NSE reports, Nifty minutes, order book (2026-10-30)

Operator: "look for all other data, scrap and store, look for orderbook data also if we can get historical data of last 1 year nifty 50 minute level, ensure uploading copy on b2 and delete from local"; then "I am asking for market order data"; then, on the ScanX comparison, "yes lets have all these data". Research 130, ADR-095.
Verify: `uv run pytest -q tests/test_market_microdata.py`; `make nse-reports`; after `make kite-login`, `make index-minute` and `make depth-day`.

| ID | Task | Status |
|---|---|---|
| T-4220 | Land NSE bulk/block deals, short selling, F&O ban, SLBM, MTF, insider (PIT), SAST daily and a year back; pledges, IPOs and the Nifty 50 list as daily snapshots | DONE. `make nse-reports`, in `make daily`; one-year backfill from 2025-10-30 (insider from 2026-05-01, the earliest NSE serves): 1,925 files, about 633,000 rows, in B2 under `nse_reports/` with SHA-256 checked; local copies deleted |
| T-4221 | NIFTY 50, NIFTY BANK, INDIA VIX 1-minute bars from Kite | DONE. Five years (2021-11-01 to 2026-10-30), 1,388,541 candles, in B2 under `kite_index_minute/` with SHA-256 checked; local copies deleted. In `make daily` |
| T-4222 | Record five-level depth for the Nifty 50, the index and the near future during market hours | DONE (S-052). One-minute live test on 2026-10-30 after the close: 52 instruments, five levels. First full session is the first trading day after it is loaded. `make schedule ACTION=install JOB=depth` loads the 09:10 job; needs a Kite login each morning |
| T-4223 | Price NSE's historical order and trade data (the only source of past order books) | TODO, operator. Email marketdata@nse.co.in |
| T-4224 | Mutual fund holdings by stock | TODO. Each fund house publishes its own monthly workbook; no consolidated free file found (research 130) |
| T-4225 | Readers for the new reports (deals, ban list, MTF, SLBM, insider) on the dashboard or as features | DONE for the dashboard: Dashboard → India → Deals & filings (ADR-096, `make market-reports`, `tests/test_market_reports.py`). Not yet used as features (S-053) |
| T-4228 | NSE's API answered a day it had not published with an empty file, which then locked in | DONE. Empty API answers within 3 days are retried, not landed; an early empty file is re-landed beside itself as `_recheck` (HISTORY #37) |
| T-4229 | NSE's bulk list repeats block trades over 0.5% | DONE. Counted once, as the block (`market_reports.drop_repeats`) |
| T-4227 | NSE served an empty MTF file for 2026-04-08 | OPEN. Refused as malformed, so the day is missing; `make nse-reports FROM=2026-04-08` retries it |
| T-4226 | Upload-and-delete only after B2's size and SHA-256 match | DONE. `make upload-verified TREES=...`; used by the three new jobs |

## The AI agent network (2026-10-29)

Operator: an AI agent network for research, building, backtesting, optimisation, risk, scenarios, a trade panel, code quality and latency; one data quality reference for every ingest; security; a way to instruct agents; a knowledge agent, a daily market brief and a data maintenance agent; Quantpedia as a source; an AI tab. "Build everything in one go." ADR-085, ADR-086, ADR-087; research 125.
Verify: `make verify`; `make agents`; `make data-quality`; `make agent NAME=market_brief`; open the workbench's AI tab.

| ID | Task | Status |
|---|---|---|
| T-4174 | Agent runtime: definitions, budgets, briefs, inbox, hash-chained log, import boundaries | DONE. `src/eulerlab/agents/`, `config/agents/`, `tests/test_agents_runtime.py` |
| T-4175 | Eight agents: data, knowledge, market brief, research, skeptic, engineering, portfolio, operations | DONE. `tests/test_agent_workers.py`. None run live with a model yet (needs `GROQ_API_KEY`) |
| T-4176 | Data quality contract, quarantine, panel SHA check, backtest guard, restore check | DONE. `make data-quality`; `tests/test_data_quality_contract.py` |
| T-4177 | Trade desk tickets and strategy version lock | DONE. Live & Risk → Trade desk and AI → Trade desk; `make relock`; `tests/test_desk_and_version_lock.py` |
| T-4178 | AI tab in the workbench, API routes, Telegram `agents`, `instruct`, `outlook`, `inbox` | DONE. `web/components/terminal/AgentsTab.tsx`, `api/agent_routes.py` |
| T-4179 | Load the three agent launchd jobs on the Mac | DONE 2026-11-01 — loaded on the Mac (`launchctl list`) |
| T-4180 | Every reader of `data/landing/` skips quarantined files, not only the panel build | TODO (S-043) |
| T-4181 | Read each registered source's licence and record it | TODO (S-044) |
| T-4182 | First `make quantpedia-sync` with the operator's key; record real responses as fixtures | TODO (S-045, A-069). Put `QUANTPEDIA_USERNAME` and `QUANTPEDIA_API_KEY` in `.env`, never in chat |
| T-4183 | VaR and futures lot checks on desk tickets | TODO (S-041, S-042) |
| T-4184 | Time the order path, signal to fill | TODO (S-046), after T-4022 |

## Paper-reading research agent (2026-10-29)

Operator: build a research agent that finds market papers, drafts strategy cards in the repo's format, and stops for approval before any backtest or trial-ledger entry. Then: "use better model for ai agent network which is free ... scrape all useless models". Research 123, 124; ADR-084.
Verify: `uv run pytest -q tests/test_paper_agent.py`; `make paper-agent TOPIC="overnight returns India" LIMIT=2`; read the drafts; `make paper-agent-approve DRAFT=<folder>`.

| ID | Task | Status |
|---|---|---|
| T-4170 | **Paper agent: search, read, draft, validate, stage; approval moves files only** | DONE. `research/paper_agent.py`, `paper_search.py`, `make paper-agent`, `paper-agent-approve`, `paper-agent-list`. 20 tests, none touch the network. Not yet run against the live services (S-040) |
| T-4171 | First live `make paper-agent` run on the operator's machine; record real arXiv and OpenAlex responses as test fixtures | TODO. Settles A-064 and A-065 and retires S-040. Needs `GROQ_API_KEY` and `EULERLAB_ASSISTANT_ZDR=1` in `.env`, or it runs on OpenRouter's 50 a day |
| T-4172 | Stronger free model; remove dead and weak ones | DONE. `research_agent: groq` with `openai/gpt-oss-120b` (1,000 requests a day). Removed `ollama-small`, `openrouter-free`, `openai`, and Groq's `llama-3.3-70b-versatile`, shut down on 2026-08-16 (HISTORY #33) |
| T-4173 | Show staged paper-agent drafts in Tools → Research Library | TODO. Today drafts are files to read; the library shows them only after approval |

## Quality and latency pass (2026-10-27)

Operator: "commit all changes and look to improve code quality and latency on all features and pages we have", then "B and approved" (fix the red checks before committing).
Verify: `make verify` (8 of 8).

| ID | Task | Status |
|---|---|---|
| T-4139 | Measure how much HISTORY #28 (delisted holdings, cash-limited buys) moved stored backtest results | DONE (partial). 9 strategies compared; 6 moved < 0.04 Sharpe; `fifty_two_week_high` 1.52 → 2.39, `illiquidity_premium` 1.04 → 1.24, `india_contrarian_36m` 0.13 → 0.09. See HISTORY #28 |
| T-4168 | Trend and Participation words used unsourced thresholds | DONE. Faber 10-month rule with drawdown badge; 200-day share + High-Low Index with 30/70 tag (research 122, ADR-083, HISTORY #32) |
| T-4169 | Source the Fear (VIX 30/70 percentile) and Big money (FII 25/75 percentile) thresholds | OPEN. Still ours (ADR-083) |
| T-4167 | No fixed templates on the Dashboard; every explanation behind an (i) button; charts chosen for visibility | DONE. Summary and card sentences removed; dials, year lines, range bars, rotation quadrant, options number line; tap-to-open `Info` (ADR-082) |
| T-4166 | India dashboard hard to read: one long page, a breadth chart, numbers without words (research 121) | DONE. Four tabs, Market pulse cards in place of the Breadth band, template summary, plain names and arrows (ADR-081). 32 tests |
| T-4161 | Dashboard lacks what trader platforms lead with: index trend and valuation, breadth depth, sector strength, F&O positioning (research 120) | DONE. `/api/market-context` and five India bands (ADR-080). 22 tests |
| T-4162 | `landing_reader` asks the bucket for `nse/nse/...` for the `nse` tree; NSE files are at `nse/...`. Only local NSE files are seen, and `market_history._read` fails for pruned files | OPEN. The dashboard lists `participant_oi` as its own tree instead. Fix `remote_key` and the listing for the `nse` tree, then check every `nse/` reader |
| T-4163 | Land FII/DII provisional cash flows | DONE (2026-10-29). `make fii-dii`, ADR-098; see the FII/DII section above |
| T-4164 | Land upcoming results dates (board meetings) | OPEN. `nse_earnings_announcements.jsonl` holds past filings and ends 2024-12-31 |
| T-4165 | The Dashboard page is wider than a phone screen: header, market toggle and ribbon run past 390 px | FIXED. The market toggle row did not wrap (scroll width 431 at 390); now every tab measures 390 |
| T-4157 | Tests slept through the 5-orders-a-second governor in real time (25 of `test_paper_attribution.py`'s 27 s) | DONE. Simulated clock in tests only. Suite 153 s → 119 s |
| T-4158 | First dashboard snapshot after a restart took 3.9 s: US panel parse 1.2 s, calendar waiting 1.3 s on B2 | DONE. 3.9 → 2.0 s (0.18 s without live quotes). The band reads the last two sessions from the file's end (12 ms); full US read 1.2 → 0.46 s; calendar uses the saved listing. Rows identical |
| T-4159 | `/api/data` walked every landing file with three `stat` calls on each request (0.3 s) | DONE. One `stat` per file, counts reused 30 s (identical counts) |
| T-4160 | `boto3` imported at the top of the panel's import chain (0.16 s on every import) | DONE. Panel import 0.22 → 0.015 s |
| T-4156 | `fifty_two_week_high` returns 41.9x over 3,000 days on the fixed engine (was 7.5x) | OPEN. Check turnover, fills and the top contributors before trusting it |
| T-4140 | Tier A without Tier B's cash and delisting rules (engines 4.5e-05 apart) | FIXED. Back to 1.4e-16. Golden file updated: −₹74.62, all from trimmed last buys |
| T-4141 | Paper attribution paired a buy in one book with a sell in the other | FIXED. Residual ₹2,875 → 2.5e-10 |
| T-4142 | 24 mypy errors, 7 ruff and 2 web lint findings in the uncommitted work | FIXED. No behaviour change |
| T-4143 | Two stale tests: `without_top_5` (−10% is right) and the rebalance-cost test, whose ranking never moved | FIXED |
| T-4145 | The panel took 2.8 GB with 5.3 GB already in swap; a full GC paused a request for 1.48 s; the reload watcher used a core all day | DONE. Slotted rows and shared strings (about 2.6 → 1.85 GB), rename step by binary search, `gc.freeze()` after load, `--reload-dir src`. Read 37.5 s → 27.4 s CPU, rows identical |
| T-4146 | Panel read 27-37 s CPU after every restart, blocking requests on the interpreter lock | DONE. Columnar copy in `data/cache/` (renamed rows, keyed to the JSONL's size and mtime): about 8 s, rows identical |
| T-4147 | After a restart, the first screen waited for a full B2 listing (7.5 s crypto) | DONE. Screens' listings saved under `data/cache/listings`, refreshed behind the answer; backtests list live |
| T-4148 | Dashboard snapshot 0.68 s warm: news re-parsed, census parsed 16×, adopted results read 143×, result logs re-parsed | DONE. 0.18 s; news output identical on real files |
| T-4149 | Options history 29 s after a restart (60 bhavcopies downloaded and parsed again) | DONE. Points kept in `data/cache/`, versioned; missing days four at a time |
| T-4150 | Company page 0.45 s per page scanning the panel file; first page 1.5 s listing factor files | DONE. In-memory per-symbol rows (2 ms); factor files cached by path, so a new release no longer needs a restart |
| T-4151 | `read_symbol_rows` returned a renamed stock's whole history instead of `days` | FIXED. Capped. The chart showed about 11 years where others showed 5; betas (capped at 1,260 observations) and 52-week figures were unaffected |
| T-4152 | Strategy table 0.22 s (mandate.yaml parsed 52×), coverage 0.16 s (`relative_to` 3,674×) | DONE. 0.07 s and 0.07 s |
| T-4153 | FX runs labelled "realistic" paid no spread (HISTORY #30) | FIXED. Half the recorded spread per unit in Tier A, Tier B and paper; engines agree; no stored FX result existed |
| T-4154 | Dead code: 15 functions referenced nowhere (source, tests, tools, Makefile, UI, docs) | DONE. About 200 lines removed; kept `OrderStatus`, `underlyings` and `underlying_lot_size_at` on purpose |
| T-4155 | The backtest panel and the company page disagree on tickers whose rows span more than one ISIN | CLOSED. Both are right for their job. Pages are keyed by screener.in tickers, which lag renames (HEG → HEGAM, ICICIPRULI → ICICILIFE), and the file scan follows the ISIN forward; the panel would show those pages nothing. 247 of 253 renamed tickers with a page read the same either way; the page keeps the file scan for all renamed tickers |
| T-4144 | Slow first calls: `/api/data` 26.6 s, `/api/instruments` 8.2 s, `/api/snapshot` 5.5 s, `/api/fleet` 3.0 s; `/api/capabilities` slower on a repeat call | TODO |

## Indian data from the close (2026-10-26)

Operator: "set timing to update just after market is over"; show data missing from 15:31 and use minute data in place of the daily file until it arrives, and the other way round. ADR-079; HISTORY #29.
Verify: `uv run pytest -q tests/test_india_live.py tests/test_data_pipeline.py tests/test_schedule.py`; `make coverage`; `make india-live ONCE=1`.

| ID | Task | Status |
|---|---|---|
| T-4136 | `make india-live` from 15:31 on weekdays, every 10 min until the bhavcopy and minute bars are in or 21:00; coverage reads **missing** from 15:31; minute-built provisional bars until the bhavcopy lands, then retired, not deleted; company page shows them; minute ingest lands today only once its 15:29 candle is in | DONE. On 2026-10-26: 413 provisional bars. Open, high and low match the bhavcopy exactly on 23 Oct; the close is 26 bps off at the median (non-F&O) |
| T-4137 | F&O stocks have no minute bars after 15:14 from 2026-08-03 (closing auction, HISTORY #29) | OPEN. Recheck the intraday studies that read an F&O stock's bars after 15:14 on dates from 2026-08-03 |
| T-4138 | Load the 15:31 job | WAITING ON OPERATOR. `make schedule ACTION=install JOB=india-live`, then the `launchctl load -w` line it prints. Also note that `com.eulerlab.daily` (19:30) is not loaded on this Mac |

## Code quality and read-route speed (2026-10-16)

Operator: "check all the changes, improve code quality and latency; commit all changes and make all branches clean", then "do all waiting on me and the not-done tasks". ADR-077; HISTORY #22, #23.
Verify: `make verify`; `uv run pytest -q tests/test_screen_common.py tests/test_api_panel.py tests/test_dashboard_speed.py tests/test_docs_check.py tests/test_request_caches.py`.

| ID | Task | Status |
|---|---|---|
| T-4125 | Commit the uncommitted work (about 190 files) as one snapshot | DONE — `68f3323`; the `task-cash-flows` worktree's separate WIP committed on its own branch (`a540d3f`), not merged |
| T-4126 | One shared module for the intraday screens' summary, fee, EMA and RSI | DONE — `intraday/screen_common.py`, −356 lines; every old copy checked equal (`==`) to the shared one, so no stored result moves |
| T-4127 | Read routes stop re-parsing unchanged files | DONE — `/api/window` 1.1 s → <1 ms, options history 3.2 s → 5 ms warm, Research Library 0.33 s → 43 ms, risk book 65 → 42 ms (ADR-077) |
| T-4128 | `test_docs_check` wrote into the real `.git` from a worktree hook | FIXED — HISTORY #22. `core.bare` restored |
| T-4129 | Remove the `Test <test@example.com>` identity the test left in `.git/config` | DONE — removed; commits use the global identity again |
| T-4130 | Delete the superseded `task-cash-flows` branch and the `EulerLab-flows` worktree | DONE — both removed at the operator's instruction. The commit was `a540d3f` (recoverable from the reflog for about 90 days) |
| T-4131 | The Angel env keys were spelled `Angle_API_KEY` / `ANGLE_*` | DONE — `ANGEL_API_KEY`, `ANGEL_CLIENT_CODE`, `ANGEL_PIN`, `ANGEL_TOTP_SECRET` in `.env`, `.env.example` and `angel_mcx_gold.py`; all four resolve from `.env` |
| T-4132 | Cache the B2 results listing without showing stale state after a mirror | DONE — 1.3-2.4 s → 3 ms; dropped on mirror; "List the bucket again" and the listing time on the Data tab (ADR-077) |
| T-4133 | Reuse a complete live answer for the dashboard map | DONE — 15 s; reopening the dashboard 3.7-4.8 s → about 1 s |
| T-4134 | Both snapshot deadlines waited out the broker they abandoned | FIXED — HISTORY #23; `server._bounded` |
| T-4135 | The movers' quote call (about 1 s) was asked on every live snapshot | DONE — the movers come from the map's own Kite answer; a mover Kite did not price (NATCO-RE, a rights entitlement) goes to Yahoo only, which is not asked for 10 min after a 429. Reopened dashboard 1.4 s → 0.35 s; same 23 of 24 movers priced |

## Dated paper deployment capital flows (2026-10-15)

Operator: allow adding or withdrawing money from an active paper deployment
without changing already-traded replay days. ADR-076.
Verify: `uv run pytest -q tests/test_deployment_flows.py tests/test_deploy_runner.py tests/test_overnight_book.py`; `make verify`.

| ID | Task | Status |
|---|---|---|
| T-4124 | Record dated paper flows, apply at next decision, report time-weighted returns and expose controls in Paper trading | DONE — dated paper flows, next-decision sizing, invested and pending state, TWR, Telegram gain and UI controls; focused replay and guard tests pass |

Sprints 0–14 are seeded from `docs/AI_BUILD_PLAN.md` §6 and
`docs/sprint_01_kickoff.md`. Sprints 15+ are planned three ahead, per the build
plan — they are listed here as scope only, not as tasks.

## MCX instrument snapshot from Kite (2026-10-15)

Operator: fetch the current MCX instruments from Zerodha and store them in their own B2 folder. ADR-075; research 081.
Verify: `uv run pytest -q tests/test_kite_mcx.py`; `make mcx-instruments` fetches today's raw snapshot and mirrors `data/landing/mcx/` to `nse/mcx/` in B2.

| ID | Task | Status |
|---|---|---|
| T-4122 | Fetch Kite MCX instruments and mirror the immutable daily snapshot to B2 | DONE — fetched 15,946 rows on 2026-10-15; raw CSV and manifest confirmed in the `nse/mcx/` B2 prefix |

## MCX iCOMDEX minute history (2026-10-15)

Operator: fetch the MCX indices shown in the supplied image, first, with Zerodha Kite; upload to B2 and expose refresh through Instruments. Research 082.
Verify: `pytest tests/test_kite_mcx_indices.py tests/test_data_pipeline.py tests/test_daily_feed_partial.py tests/test_kite_routes.py`; B2 checksum verification for `mcx_indices`.

| ID | Task | Status |
|---|---|---|
| T-4123 | Fetch and wire Kite MCX iCOMDEX index minute bars | DONE — queried the full five-year range; 1,811,889 candles across seven series; five unsupported series explicitly recorded; 257 B2 objects checksum verified |

## AI-assisted Research Library (2026-10-15)

Operator: add paper field drafts and sandboxed code/backtest actions to the Research Library, using the existing AI setup. ADR-073.
Verify after implementation: review the draft and source-handling flow in Tools → Research Library; inspect the sandboxed generated source before trusting its Tier B result.

| ID | Task | Status |
|---|---|---|
| T-4119 | Draft summary, trade idea, implementation, source results, markets and red flags from pasted source text; use assistant provider locks and do not persist source text | DONE — `/api/research/draft`; draft is reviewable before saving, model is selectable |
| T-4120 | Add paper-page AI code & backtest action through authoring sandbox and existing Tier B job | DONE — model is selectable; shows generated code and result; does not persist the generated strategy |
| T-4121 | Recover from stale OpenRouter free models without weakening ZDR | DONE — Research Library refreshes its picker from the live filtered catalog; assistant can read the offline runbook as a reference |

---

## Two Indian options strategies (2026-10-07)

Operator: "research on 2 Indian options strategy and implement based on data we have". Research 070.
Verify: `uv run pytest -q tests/test_options_strategies.py`; `make nifty-options`; `make options-strategies`.

| ID | Task | Status |
|---|---|---|
| T-4026 | **A Nifty options history** | DONE — `nifty_options.jsonl`, every Nifty option and future 2015-2026, one line per day, read once from B2. 2,891 of 2,903 days; 12 archives failed and are retried by re-running |
| T-4027 | **Monthly short strangle (Bangur 2020)** | DONE — three distances; only 6% OTM made money (+43% of margin over 11 years) and it lost 104% of margin in March 2020. Not deployable |
| T-4028 | **Covered call (Aggarwal 2011)** | DONE — the paper's daily rule loses 79% to costs; held monthly it is about flat against the future's +33%. Not reproduced |
| T-4029 | Options strategies are not on the Strategies page | OPEN — they run outside the daily engine (`options/strategies.py`), which trades weights of equities |

---

## What other platforms have, and a risk screen (2026-10-14)

Operator: "look over Nautilus Trader and other platforms and let me know what features are missing ... make a screen which shows risk on current trading strategies: current VaR, strategy distribution, maximum risk, allocation ... research on it first and then make a mockup". Research 079.
Verify: read `docs/RESEARCH/079-what-other-platforms-have-and-a-risk-screen.md`; open the mockup linked in it.

| ID | Task | Status |
|---|---|---|
| T-4106 | **Feature gaps against NautilusTrader, QuantConnect and OpenAlgo** | DONE — research 079. Seven gaps matter now, all about seeing and controlling risk while trading: no view across deployments, no risk number, no exposure or concentration, no headroom on limits, no reduce-only state, no loss limit that acts, no live-against-backtest chart. Documentation pages were read through summaries |
| T-4107 | **Mockup of the risk screens** | DONE — three screens with sample numbers: overview (VaR, where the risk is, allocation, limits), performance by deployment, stress and exposure. Not checked in a browser by me |
| T-4108 | **Portfolio roll-up across deployments** | DONE 2026-10-14 — ADR-071. `risk/book.py`, `risk/report.py`, `GET /api/risk/book`: equity, P&L, cash, exposure, names, overlap, sectors, drawdown, for every active deployment together. Verify: `uv run pytest -q tests/test_risk_book.py`; Live & Risk → Risk overview |
| T-4109 | **VaR from current positions** | DONE 2026-10-14 — ADR-071. Today's holdings run through 250 days; VaR and expected shortfall at 95% and 99% three ways; component VaR by deployment; beta; six stress scenarios; correlation between deployments; the live path inside its backtest band. No figure under 60 days of prices. On the real books: VaR ₹2,363, 0.11% of equity, because 95% of the money sits in the overnight deployment, which holds nothing at the close |
| T-4112 | **Three views under Live & Risk** | DONE 2026-10-14 — Risk overview, Performance, Stress & exposure (`RiskBook.tsx`). `#live/performance` links to a view. Seen in a headless browser on the real paper books, dark theme, 1400 px; light theme and a phone width were not looked at |
| T-4113 | **Gap risk for the overnight future** | DONE 2026-10-14 — ADR-072. The future is in the book's VaR as it is run (in position 78 of the last 250 nights), with its own figures for a night it holds. On the real books: book VaR ₹6,126 (was ₹2,363 without it); the future is 88% of it; on a night it holds, 1-in-20 loss ₹11,445, shortfall ₹18,036, worst night of the year −₹27,243, worst gap on record −10.0% (23 March 2020) = −₹1.48 lakh at today's one lot |
| T-4115 | **A 1-in-20 night in the future is more than the kill switch's daily loss limit** | NOTED — ₹11,445 against ₹10,000. The switch would trip after the open, with the loss taken. The limit, the size, or accepting it is the operator's call |
| T-4116 | **The 13 October order was rejected by a lookup bug** | FIXED — HISTORY #21. An exact-name read of a file pruned from this machine found nothing in the bucket, so "lot size not found". The signal night was missed and is not traded after the fact. Verify: `uv run pytest -q tests/test_risk_book.py -k exact_file` |
| T-4117 | **Adding and removing a deployment** | DONE 2026-10-14 — ADR-072. Any active deployment is in the figures on the next read; a stopped one leaves them and is listed with what it made. Colours follow creation order, so the rest keep theirs. Each row shows the book's VaR without it. The Deploy dialog shows the book's VaR before and after adding the strategy (`POST /api/risk/what-if`). Checked on the live API for a share strategy and for the future; the dialog line and the stopped list were not seen in a browser (nothing is stopped today) |
| T-4118 | The what-if sizes a new strategy in equal amounts | OPEN — A-060. The preview gives names, not sizes |
| T-4114 | The rounding bug in the first VaR | NOTED — `(1 - 0.95) * 100` is 5.000000000000004 in floating point, and its ceiling put a sixth day in a five-day tail. Caught by the hand-worked test before any figure was shown |
| T-4110 | **Limits with headroom** | DONE as warnings 2026-10-14 — the kill switch's daily loss (₹10,000, which already existed) and rupees-in-one-name limits are shown with how much is used. Four new levels in `config/risk_watch.yaml` (book VaR 2%, book drawdown 10%, deployment drawdown 8%, largest sector 35%) **warn and do nothing else**. Their values came from the mockup, not from the operator: change them. Orders-a-day and unresolved-order limits are not shown: the screen has no count of today's live orders |
| T-4111 | A reduce-only state for a deployment | DONE 2026-10-29 — ADR-092 (T-4201) |

---

## The nightly job uploads as it goes (2026-10-13)

Operator: "what is the data upload going on right now it is running all time ... stop that", then "data 1 download, uploaded it, deleted from local then data 2 ... and lets make fundamental data weekly or on demand update". ADR-070.
Verify: `uv run pytest -q tests/test_sync_only.py tests/test_schedule.py`; `make upload-tree TREES="mf calendar" DELETE=1 DRY=1`; `make -n daily-run | grep upload-tree`; `make schedule JOB=fundamentals`.

| ID | Task | Status |
|---|---|---|
| T-4097 | **The 13 October nightly run was stopped by hand** | DONE — `make daily` from launchd, 1 h 14 min in, on minute bars. It holds the `feed` lock, so "Update all data" was refused while it ran. Its only upload was the last step, behind fundamentals (over ten hours on 8 October), so nothing it fetched had been uploaded |
| T-4098 | **One dataset at a time: download, upload, delete** | DONE — `sync_cloud --only ... --then-delete`, `make upload-tree TREES="..." DELETE=1`. Lists only the named folders in the bucket, not all 142,000 objects; deletes only what a fresh listing shows there at the same size. Thirteen upload points in `daily-run`. NSE and US files are deleted after the builds that read them, a few steps after their upload. The full sweep and prune still run last. On the real bucket: 418 files from the stopped run uploaded in 75 s; `mf` and `calendar` uploaded and deleted. **No full `make daily` has run with it yet** |
| T-4103 | **Deleted files came back within a minute** | NOTED — the running workbench reads the calendar and fund files and fetched them back from B2. By design (`landing_reader`); the same after every `prune-local` |
| T-4104 | The next nightly run deletes 1.9 GB of local minute bars | NOTED — 12,636 files, all in B2. The intraday stock studies will download them again when next run (about 15 minutes) |
| T-4099 | NSE's files for 13 October failed to download | OPEN — bhavcopy, participant OI, indices and delivery all reported `failed` at 19:42. Not diagnosed. The panel and paper books are on 12 October until they land |
| T-4100 | **Fundamentals is weekly and on demand** | DONE — out of `daily-run`. `make fundamentals-update` (LIMIT=n for a few companies) fetches, uploads and deletes, under its own `fundamentals` lock, so it no longer blocks the nightly job or the button. `com.eulerlab.fundamentals` is installed and loaded: Sunday 10:00. Not yet run |
| T-4105 | No button for fundamentals on Instruments | OPEN — on demand means the make target today |
| T-4101 | "Update all data" on Instruments still uploads once at the end | OPEN — `daily_feed._mirror`. It has no fundamentals step, so the wait is short. Not changed |
| T-4102 | Derived tables are not part of the nightly upload | NOTED — `make sync-derived` is separate, and the 710 MB price panel still fails to upload (T-4015) |

---

## Archiving strategies (2026-10-13)

Operator: "add option in strategy library to archieve some strategies and undo if wanted". ADR-069.
Verify: `uv run pytest -q tests/test_strategy_archive.py`; `make workbench` → Strategies → open a strategy → Archive, then Undo; the "Archived N" filter → Restore.

| ID | Task | Status |
|---|---|---|
| T-4094 | **Archive and restore strategies** | DONE — `strategies/archive.py`, `POST /api/strategies/archive`, `archived` on `/api/fleet`. Strategies page: Archive / Restore in the side panel and for a selection, an "Archived N" filter, and Undo after each change. Hides only: results, trials and deployments are untouched. Checked on the live API (archive, list, restore) and the chip seen in a headless browser; the buttons were not clicked by hand |
| T-4095 | A strategy that cannot be run can now be ticked | NOTED — it had to be selectable to be archived. The Backtest button counts only the runnable part of a selection |
| T-4096 | Archived strategies still appear elsewhere | OPEN — the header count, the command palette, the Research Library's links and the Telegram `strategies` word list all 80. By decision for the count (ADR-069); the others were not changed |

---

## More intraday rules for Indian stocks (2026-10-13)

Operator: "research on more intraday stock strategies for indian stocks", then "add all paper to resarch library and start coding and backtesting". Research 077 (reading), 078 (the two rules run).
Verify: read `docs/RESEARCH/077-more-intraday-stock-rules-for-india.md`; `uv run pytest -q tests/test_research_library.py`; Tools → Research Library → "End-of-Day Reversal".

| ID | Task | Status |
|---|---|---|
| T-4087 | **What the literature has on intraday rules for Indian stocks** | DONE — eighteen searches. No reviewed paper tests an intraday rule on NSE stocks with costs beyond research 076. Five candidates from US evidence, each set against this project's measured costs |
| T-4088 | **Two rules specified as hypotheses** | DONE — H-0007 end-of-day reversal (Baltussen, Da & Soebhag 2025), H-0008 opening half-hour continuation (Heston, Korajczyk & Sadka 2010). Both in the research library. The prior for both was that they lose after costs |
| T-4089 | **Code and screen H-0007 and H-0008** | DONE — research 078, `intraday/stock_papers.py`, `make stock-intraday`. Neither effect exists in the 100 largest stocks before costs: reversal spread 0.3 bps a day (t 0.6), opening continuation -0.7 (t -0.5). Net -65% to -79%. Both rejected, no trial spent. Verify: `uv run pytest -q tests/test_stock_intraday_papers.py`; `make stock-intraday` |
| T-4091 | **The losers-only result looked like the paper's and was not** | NOTED — the day's losers gain 4 bps from 14:40 to 15:10 (t 6.2), but so does every large stock (3.8 bps, t 6.1) and so do the winners. A market-wide drift, not a reversal; below the ETF's costs and absent in 2026. Not a tested hypothesis |
| T-4092 | **Every paper of research 077 in the research library** | DONE — seven more added as ideas, each saying what was and was not read. 58 papers |
| T-4093 | The end-of-day reversal in smaller stocks | OPEN — the paper finds it strongest there. A new hypothesis; costs would be worse |
| T-4090 | Sources not read | OPEN — Agarwalla & Pandey on NSE block trades (fetch timed out), SEBI's own intraday study (press coverage only), Della Corte et al. and Zarattini & Aziz on VWAP (summaries only) |

---

## Five Indian intraday rules, and the papers in the research library (2026-10-12, 2026-10-13)

Operator: "work on 5 intraday strategy from recent paper/article ... on indian market purely", "get all papers in research and update in strategy library", then "backtest all recent strategies ... add in research library if not added and right pane of research library should be fixed to read and left strategy paper should scroll". Research 076.
Verify: `uv run pytest -q tests/test_india_intraday_papers.py tests/test_library_sync.py tests/test_research_library.py`; `make india-intraday INDEX_ONLY=1`; Tools → Research Library.

| ID | Task | Status |
|---|---|---|
| T-4078 | **Five intraday rules from Indian sources, coded and run** | DONE — `intraday/india_papers.py`, `make india-intraday`. NIFTYBEES and the 100 largest stocks, 2021-2026, 26 settings. 25 lose after costs; the open fade held 150 minutes made +4% and has lost since 2024. No trial spent |
| T-4079 | **Nine studies in the strategy library with their stored results** | DONE — `strategies/studies.py`, `make library-sync` (safe to re-run: second run stored 0). They show engine "study" and cannot be run from the page |
| T-4080 | **The ten recent strategies re-run on 2026-10-13** | DONE — `make options-strategies`, `intraday-papers`, `gap-forecast`, `india-intraday`. Research 076's 26 settings matched the stored run exactly. The others gained two to three sessions and no verdict moved |
| T-4081 | **Research 076 had code and results but no note** | FIXED — written 2026-10-13 from the coding session's records; the sources were not fetched again and the note says so |
| T-4082 | **Five papers missing from the research library** | DONE — Rao, Doraigari, Tripathi & Aggarwal, Bangur, Aggarwal added; Gao, Zarattini, Wang & Gangwar and the hedging-demand paper linked to their studies. 49 papers. A study link shows its result and no Backtest button. A test fails if a study has no paper |
| T-4083 | **The research library's paper scrolled away with the list** | FIXED — both columns are pinned under the bar; the list scrolls inside itself and the paper inside its own column (`research.css`). Seen in a headless browser at 1400 px; scrolling itself was not exercised by hand |
| T-4086 | **Research library: only the list of papers scrolls** | DONE 2026-10-13 — the library is as tall as the window, so the page does not scroll. Left: search, status filter with counts, and the scrolling list. Right: title, status, markets and four tabs (Overview, Rules, Red flags, Strategies) stay in place; a section longer than the window scrolls inside its box. Seen in a headless browser at 1400x900. The built UI (`make ui-fast`) must be rebuilt to show any web change: T-4083 was invisible until it was |
| T-4084 | The open fade and the late opening range on futures | OPEN — new hypotheses, like T-4039. Each needs minute bars for the instrument and its own trial |
| T-4085 | Aggarwal (2011) has no link and an unconfirmed title | OPEN — the rule is from a search snippet (research 070) |

---

## A registered gap strategy, and Telegram (2026-10-11)

Operator: "registry this strategy in strategy library Green day and VIX fell → long and setup telegram signals for paper /live trading strategies like name of strategy and strategy actions", then "also define terms i can use to interact with telegram". ADR-063.
Verify: `uv run pytest -q tests/test_telegram_signals.py`; Strategies → "Green day and VIX fell"; `make gap-signal DRY=1`; send `status` to the bot.

| ID | Task | Status |
|---|---|---|
| T-4043 | **"Green day and VIX fell: long the Nifty future overnight" in the strategy library** | DONE — `nifty_calm_rise_overnight`, runnable from Strategies (engine `overnight`), linked from its paper. It is a calculation, not a `Strategy`: neither engine can fill at the next open. A one-session window overflowed the annualised return; fixed |
| T-4044 | **Telegram message when a deployment acts** | DONE — `deploy/signals.py`: mode, strategy name, each new order, equity, cash, next rebalance; a halt or error once. Nothing when nothing was placed. Paper today; the same code serves live when it is allowed (T-4022) |
| T-4045 | **The gap strategy's decision on Telegram before the close** | DONE — `make gap-signal`: live Nifty and India VIX from Kite, "BUY at the close, SELL at the open" or "none tonight". It places no order |
| T-4046 | **Words the operator can send the bot** | DONE — status, positions, orders, next, signal, data, strategies, help. Read-only, answered only from the operator's chat. The API runs the listener; `make telegram-bot` runs it alone |
| T-4047 | `make gap-signal` is not scheduled | DONE 2026-10-12 — `make schedule ACTION=install JOB=gap-signal` wrote `com.eulerlab.gapsignal`, 15:20 Monday to Friday, and it is loaded. The scheduled run says nothing on a weekend, an NSE holiday, or outside 15:05 to 15:45 (a run launchd catches up after sleep). It still needs a Kite token made that day; without one the message says so |
| T-4048 | The gap strategy cannot be paper-deployed | DONE 2026-10-12 — `deploy/overnight.py`, ADR-066. Its own decision loop, the same OMS, journal, paper broker, kill switch and state file. Whole lots up to the book's equity, no borrowing; lot size read from the day's F&O file. One lot is about ₹14.7 lakh, so a smaller book never trades and says so |
| T-4077 | A broader Telegram bot | DONE 2026-10-12 — ADR-068. 22 words in five groups (was 8), short forms, "did you mean", deployments by name, long answers split, a tap keyboard, and plain questions passed to the assistant. Still read-only; `kite` never sends the login link. Verify: `uv run pytest -q tests/test_telegram_words.py`, then send the bot `help` |
| T-4076 | The dashboard opened on the last settled day, then went live | DONE 2026-10-12 — ADR-067. The first paint now shows the newest prices already seen (the last live quotes, saved to one file, and held minute bars when newer), labelled "last seen" with their time. First paint still about 0.45 s |
| T-4074 | Should an opening-range rule start at the second bar on an ETF? | OPEN — research 075. A change to a coded rule is a new hypothesis and a new trial, not a fix |
| T-4075 | The nightly job exited 2 on 2026-10-11 | NOTED — `prune-local` could not reach Backblaze (no network that evening; the same hour the assistant could not resolve a host). The feed steps before it ran. Watch tonight's run |
| T-4050 | A batch writes each result to the store two or three times | DONE 2026-10-12 — each item is recorded once per batch (`stored` in `_run_batch`). Checked on a real run of the gap study: one new line, same Sharpe. Lines already duplicated in the files are left; the library de-duplicates on read |
| T-4073 | Old repeated rows in the result files | DONE 2026-10-12 — `make results-dedupe APPLY=1`: 145 of 364 rows removed (rows identical but for the time written), here and in the bucket. Library summaries for all 69 strategies were byte-identical before and after. A copy from before is in the session scratchpad only |
| T-4049 | Words that act (run, stop) from Telegram | NOT BUILT — by decision, ADR-063. Reopen only with a confirmation step and a recorded decision |

---

## Dashboard speed (2026-10-12)

Operator: "make dashboard load fast optimize codebase, don't do lot of caching".
Verify: `uv run pytest -q tests/test_dashboard_speed.py`; `curl -s -o /dev/null -w '%{time_total}\n' 'localhost:8000/api/snapshot?live=false'`.

| ID | Task | Status |
|---|---|---|
| T-4063 | **First paint from held data, live prices after; panel slices; faster panel read; preload; built UI** | DONE — measured table in ARCHITECTURE. First paint 6-9 s → 0.4 s |
| T-4067 | **Second pass: every read route timed, the slow ones profiled and fixed** | DONE — options history 77 s → 8 s, chain 3.0 → 0.3 s, bucket listings no longer block a screen. Table in ARCHITECTURE |
| T-4068 | Options history: a light path | DONE — 8 s → 4.7 s. The history solves only the at-the-money row and each file is decompressed in one call. What is left is decompressing and parsing 30 files |
| T-4069 | Stricter lint for Python, and a linter for the web | DONE — `pyproject.toml` now also selects C4, PIE, FURB, PERF, PLE, PLW, RET; 150 findings fixed across 26 files; four rules exempted with reasons. The web had no linter: `web/.eslintrc.json` (Next core-web-vitals), four findings fixed, `make web-check` |
| T-4064 | Live prices on the dashboard | DONE — 3.8 s → 0.8 s. Kite's OHLC endpoint at 500 a call, research 074. Still five requests back to back against a documented one a second (A-055) |
| T-4070 | The web's types and lint are a `make verify` gate | DONE — `tools/verify.py` `check_web`. Eight gates now. Where the web's packages are not installed it prints SKIP and stays green, so a headless machine can still verify |
| T-4072 | Every batch waited 43 s on the results mirror | DONE — it downloaded all 70 result files each time. Now 2 s: a file whose **content hash** matches the bucket's is skipped (the listing's ETag is the MD5; checked on all 70 files). The first version compared sizes and could miss two different files of equal size; that hole is closed and tested. `make results-pull` downloads everything |
| T-4071 | The price panel reads in 13.5 s, was 19 | DONE — rows built in one step; only out-of-order days sorted. `trading_days` and `by_symbol` skip work that changes nothing. Paper-book update 20.8 s for two deployments, same equity to the paisa |
| T-4065 | The panel is 5.4 million Python objects in memory | NOTED — now a 13.5 s read (T-4071), of which 6 s is parsing JSON. Going lower needs a columnar panel, which changes every reader: 11 modules call `read_panel` and all take `list[PanelRow]`. Not done; needs a decision record first |
| T-4066 | `/api/fleet` takes 2.7 s on its first call after a restart | DONE — 1.3 s first call, 0.07 s after (measured 2026-10-27, after the columnar copy and FileMemo) |

---

## Company pages (2026-10-12)

Operator: "build pages for each stocks about their details from data we have from fundamental data". ADR-065.
Verify: `uv run pytest -q tests/test_company_page.py`; open `localhost:3000/terminal/company/RELIANCE`.

| ID | Task | Status |
|---|---|---|
| T-4058 | **A page per company: price, vitals, key metrics, bars, six statements, peers, news** | DONE — `features/company_page.py`, `api/company_routes.py`, `web/app/terminal/company/[symbol]/`. Checked on RELIANCE in a headless browser |
| T-4059 | Ways in to a company page | DONE 2026-10-12 — symbols link to their company page from the market map, the three movers tables, paper positions and orders, and equities on Instruments; the command palette finds companies by name or symbol |
| T-4060 | News tagging is loose | DONE 2026-10-12 at the reader — the company page keeps only headlines that pass `ingest.news.strong_match` (the ticker, or the first two distinctive words of the name). The archive still tags loosely on purpose. Many headlines that remain are price-page titles, not news: that is what the archive holds |
| T-4061 | Analyst ratings, targets, estimates, DCF, company description | NOT BUILT — no source held. Each needs a source decision first (ADR-065) |
| T-4062 | Give the assistant a `company` tool | DONE 2026-10-12 — `company` tool: header ratios, computed metrics, five periods of the main statement rows, industry median P/E; part of a name returns matching symbols. Twelve tools now |

---

## The assistant (2026-10-12)

Operator: "setup a free ai assistance ... ensure no data leak to ai, should have floating icon over screen". ADR-064, research 073.
Verify: `uv run pytest -q tests/test_assistant.py`; open any screen and click the round button, bottom right.

| ID | Task | Status |
|---|---|---|
| T-4051 | **Assistant: floating button, chat route, eleven read-only tools, three locks** | DONE in code — `assistant/`, `api/assistant_routes.py`, `web/components/Assistant.tsx`. Every tool was run on real data locally. Runs on OpenRouter's free `apodex/apodex-1.1-mini:free` with zero retention forced per request |
| T-4056 | Model list in the assistant panel | DONE — every provider in `config/llm.yaml`; unusable ones greyed out with the reason. Adding one: `docs/RUNBOOKS/assistant-is-offline.md` |
| T-4057 | Approve more hosts (OpenAI, xAI) for the assistant | OPEN — each needs its data terms read and recorded first. Keys for both are already in `.env` |
| T-4052 | Operator: a real Groq key (the one supplied was an xAI key) | OPTIONAL — only if Groq's larger models are wanted. Rotate the xAI key: it was sent to Groq twice as a login header |
| T-4053 | First real questions: does `llama-3.3-70b-versatile` call the tools correctly, and does the free quota last a session? | PARTLY — 2026-10-12 on the OpenRouter model: two of three questions answered correctly with the right tools, one hit the 20-a-minute limit. 50 requests a day is about 10 to 25 questions; not yet lived with |
| T-4054 | Free 5 GB of disk, then a local model becomes possible | NOTED — 1.4 GB free of 228 GB on 2026-10-11. Also a risk to the nightly job |
| T-4055 | Tools for fundamentals, options chain and news | NOT BUILT — add when a question needs one. Each new tool is a new thing that can leave the machine |

---

## Two pure intraday papers on NIFTYBEES (2026-10-11)

Operator: "lets fetch 2 pure intraday strategy paper, code it and backtest on indian market". Research 071, H-0005, H-0006.
Verify: `uv run pytest -q tests/test_session_papers.py`; `make intraday-papers`; Tools → Research Library.

| ID | Task | Status |
|---|---|---|
| T-4038 | **Gao et al. (last half-hour) and Zarattini et al. (noise area), read in full, coded and run** | DONE — `intraday/session_papers.py`, NIFTYBEES one-minute bars, 1,264 sessions 2021-2026. Gao: no predictability (t -0.54), gross 0.3 bps a trade, net -53%. Noise area with band + VWAP stop: gross Sharpe 1.58, stable before and after 2024, 3 bps a trade; NSE charges are 4 bps a round trip, net -31%. Both rejected for the cash ETF. No trial spent |
| T-4042 | **"Price Action Meets Volatility" (Mukherjee & Mandal 2025) coded as written** | DONE — research 072, `research/gap_forecast.py`, `make gap-forecast`. All three models and the paper's tables, with its VIX change (close minus open). The tables reproduce, but the paper compares with 50% and the Nifty gaps up on 68.7% of days: always saying "up" beats every model. Signals lift 2-5 points over the base rate. On the Nifty future after costs: joint long-only +47%, Sharpe 0.64, flat since 2024; short side loses. Not a gate candidate. Verify: `uv run pytest -q tests/test_gap_forecast.py`; `make gap-forecast` |
| T-4039 | Does the noise-area edge survive on a cheaper instrument? | OPEN — a new hypothesis, not a re-run. Needs minute bars for the Nifty future, which are not landed, and its own trial |
| T-4040 | Do the existing intraday signals read NIFTYBEES's 09:15 print as a price? | ANSWERED 2026-10-12 — yes, on ETFs. Research 075: the first bar sets the 15-minute range's edge on 99.6% of NIFTYBEES days and triples its width. Three stored NIFTYBEES results measured that print (HISTORY #20); all had already failed. Shares: the first bar widens the range about 40%. Nothing re-run |
| T-4041 | NIFTYBEES's last bar is not the close | NOTED — 4.7 bps above the official close on average. `session_papers` uses the bhavcopy close; the bracket engine closes at a bar price and is not affected by the label, but any study of "the last minutes" on an ETF is |

---

## Paper trading forward, with the operator's capital (2026-10-07)

Operator: "yes i should decide amount ... cut position in lowest ranked instruments ... build full paper trading infra mimicking live trading and deploy first, research other platform sandbox / paper trading and fallback system". ADR-060, research 069.
Verify: `uv run pytest -q tests/test_deploy_runner.py tests/test_deploy_sizing.py`; `make workbench` → Strategies → a strategy → Deploy → Paper; Live & Risk → Paper trading; `make paper-daily`.

| ID | Task | Status |
|---|---|---|
| T-4018 | **Fit to capital** | DONE — `deploy/sizing.py`: the largest top-ranked set whose every name the money can buy at least one share of, re-weighted; the rest are left out. The Deploy dialog shows "₹X buys the top k of N" before starting |
| T-4019 | **Forward paper deployments** | DONE — `deploy/runner.py`, `make paper-daily` (also the end of `make daily`): each deployment replays from its start through the engine and the OMS to the latest close. Catch-up after missed days, nothing sent twice, 5 bps slippage, Indian costs, 1% cash buffer |
| T-4020 | **Fallbacks** | DONE — kill switch tripped, unresolved orders, a revised past (an order for a traded day never placed), book ≠ broker: each halts that deployment and trips its own switch. Stale panel is reported, not halted |
| T-4021 | **Deploy and watch from the workbench** | DONE — Deploy → Paper takes a capital amount and starts a deployment (evidence checks shown as advisory for paper, still blocking for live). Live & Risk → Paper trading: equity, return, cash, costs, positions, fills, next rebalance, warnings, Run now, Stop |
| T-4022 | Live deployments | BLOCKED — on the operator: the broker (Kite assumed) and the live capital cap and confirmation rule. Then one supervised test order (T-3336) |
| T-4017 | Corporate actions on a paper book | OPEN — S-038 |
| T-4023 | The panel ended 2026-10-01 | DONE — 2-7 Oct landed, mirrored and built. Panel ends 2026-10-07. (`build-panel` no longer needs the mirror first: T-4030) |
| T-4025 | **A deployment made from a long-running workbench used the panel it loaded at startup** | FIXED — the API kept the price panel from when it started, so a ₹1 lakh deployment made on 7 Oct started on the 1 Oct close and showed "waiting". `api/panels.py` now re-reads the panel when the file changes. That deployment was caught up by `make paper-daily` |
| T-4030 | **The paper books stayed on 7 Oct after 8 Oct had landed** | FIXED — `make daily` built the panel and ran `paper-daily` as its last steps; the 03:50 run died at a failed B2 sync (network down, the only step without `-`) and the 19:30 run was still on fundamentals an hour later. The panel and paper books now run straight after the NSE files, the sync is non-fatal, and `build-panel` reads local landing before B2. Runbook `paper-books-behind.md`. Verify: `uv run pytest -q tests/test_panel_local_landing.py` |
| T-4032 | **One data pipeline from the Instruments button** | DONE — ADR-061. "Update all data" fetches only what is missing, rebuilds market history, the price panel, Nifty options, the paper books and the US panel, then uploads only what B2 lacks. It shares a `feed` lock with `make daily` (the second is refused and told who holds it); each appender locks and re-reads inside the lock, so a day cannot be written twice. Each step reports "downloaded N, already held M". A Data coverage table on Instruments (`make coverage`) shows every dataset's last day against the day it should reach. The US panel re-reads two months, not 24. Fundamentals moved to the end of `make daily` (it ran over ten hours on 8 Oct). Three buttons: Update all data, Mirror to cloud, Delete local copies (dry run first, then a confirmed delete of files B2 holds; `POST /api/data/prune`). Verify: `uv run pytest -q tests/test_data_pipeline.py`; `make coverage`; `make workbench` → Tools → Instruments |
| T-4036 | **Minute bars re-fetched the whole year every run** | FIXED — HISTORY #19. Chunks are planned from the days each symbol lacks; today only after 15:45 IST. The Kite token is judged by 06:00 IST, not by the UTC date (`kite_session.is_fresh`, `make kite-fresh`). Verify: `uv run pytest -q tests/test_minute_no_refetch.py` |
| T-4037 | Kite login and minute bars from the Instruments page | DONE 2026-10-12 — `api/kite_routes.py` (status, login by pasted address, a callback route), a Kite strip on Instruments, and an "India minute bars" feed step with its own row button. The step skips itself, in green, when no token was minted today. **Not tried with a real login**: that needs you to sign in on Zerodha's page |
| T-4035 | **The price panel and paper books update by themselves on data change** | DONE — ADR-062. Any run that fetches NSE files also runs the panel and the paper books (`DEPENDENTS`); the API checks every 5 minutes and catches up whatever landed by other routes. A check with nothing to do takes under a second. Off with `EULERLAB_AUTOUPDATE=0`. Verify: `uv run pytest -q tests/test_autoupdate.py` |
| T-4034 | **An Update button per dataset and per group** | DONE — each Data coverage row runs only its own steps (`coverage.STEPS_FOR`, `POST /api/data/feed` with `only`, no mirror); each group header runs its rows' steps. The row being updated shows "updating…". Verified on the live API: Nifty options in 22s, nothing re-downloaded |
| T-4033 | The crypto, MF, FX and US panels in the API never reloaded | FIXED with T-4032 — they now reload when the landing census changes |
| T-4031 | `build-panel` printed "wrote 0 new days" while 8 Oct was added | CLOSED 2026-10-12, not reproduced — on 8 Oct no lock existed, so a second writer (the nightly job or the feed button) could append the day between this process's read and its message. The `panel` file lock (ADR-061, 9 Oct) removed that window. The cause is the likely one, not a proven one; reopen if the message disagrees with the file again |
| T-4024 | A new deployment said "ok" before it could trade | FIXED — the engine runs only once two sessions follow the start; until then the state is "waiting" with that reason |

---

## Tuning volatility-adjusted momentum (2026-10-07)

Operator: "optimize this strategy and ensure no overfitting", then "optimize the set of parameters in the strategy, no other parameter addition". Research 067.
Verify: `uv run pytest -q tests/test_tune_sharpe_momentum.py`; `make workbench` → Strategies → Volatility-adjusted momentum → Optimisation; `make tune-sharpe-momentum ANALYSE=1` (needs the sweep's runs on disk; without them `make tune-sharpe-momentum` re-runs all 64, about 50 minutes, resumable).

| ID | Task | Status |
|---|---|---|
| T-4008 | **Sweep window, names held and rebalance; choose on 2016-2023, test on 2024-2026** | DONE — 64 settings. Only the window matters (9-12 months beat 3-6 in-sample and holdout). PBO 0.71; walk-forward re-tuning earned Sharpe 1.28 against 1.38 for the paper's setting. Paper setting kept |
| T-4009 | 252/10/10 made holdout Sharpe 1.16 against the paper's 0.80 | OPEN — likely luck (its neighbours made 0.60-0.82, grid edge, 3× costs). Paper-trade it beside the paper setting if it is to be believed |
| T-4010 | **The sweep was not on the web** | DONE — Strategies → the strategy's side panel, and Full report → Optimisation: verdict, before/after table with 2× costs, Sharpe heatmap per rebalance (in-sample or holdout), growth curves with the holdout shaded. Read-only, from `GET /api/tuning?strategy=` (`tuning_view.py`) |
| T-4011 | **Derived tables were never in B2** | DONE — `make sync-derived` mirrors `data/derived/` to `nse/derived/`, one file at a time; `DROP=path` deletes a file only when B2 holds it at the same size and SHA-256. The old close-only panel (528 MB) is dropped. Raw landing pruned the usual way (56,405 files, 1.02 GB) |
| T-4012 | Twelve parallel uploads of large files dropped the Mac offline | FIXED for derived (one worker). `sync_directory` takes `workers`; the landing trees keep 12. RUNBOOKS/upload-saturates-uplink.md |
| T-4014 | A 5% stop-loss inside each holding period | KILLED — tested on the best case and the paper setting; it lowered return and Sharpe in both. Results and code not kept, at the operator's request |
| T-4016 | **The optimised setting can be deployed beside the original** | DONE — `india_sharpe_momentum_opt` (12-month, top 10, every 10 sessions) registered and backtested: Sharpe 1.23, +2,171%, −39%, 3,199 fills. The original keeps its paper settings |
| T-4015 | The 710 MB price panel will not upload to B2 on this connection | OPEN — fails mid-part even at 32 MB parts (multipart added). 116 of 117 derived files are in B2; re-run `make sync-derived` on a steadier link |
| T-4013 | `data/landing/macro/2026-10-07.jsonl` differs in size from its B2 copy | OPEN — kept on disk by prune-local; today's file was rewritten after it was uploaded |

---

## The left-out paper strategies (2026-10-07)

Operator: "now run all leftout strategies", then "yes" to four papers the new data unlocked. Research 064, 066.
Verify: `uv run pytest -q tests/test_india_papers.py tests/test_session_studies.py`; `make india-papers`; `make session-studies`.

| ID | Task | Status |
|---|---|---|
| T-4000 | **Sector rotation (Sharma 2025)** | DONE — fifteen sectoral indices as instruments through the engine (`market_history.INDEX_UNIVERSE`), ranks 6-10 held yearly. Sharpe 0.84, +256% after costs. A first run traded 2,793 times because the view held one year and the rank's base date slid daily; the lookback is now two years |
| T-4001 | **Bullish candles (Manoharan 2019)** | DONE — hammer, bullish engulfing, rising window on the point-in-time top 50, held five days. Sharpe -0.34, -56%: costs of ₹7 lakh on ₹10 lakh |
| T-4002 | **Overnight, VIX gap and expiry SIP, calculated** | DONE — `research/session_studies.py`, on Nifty futures and the index, not the engines (they fill at closes only). Results in research 064 |
| T-4003 | **The cost model charged ETFs the share STT** | FIXED — 0.1% each side against 0.001% on the sale (research 066, HISTORY #18, A-047). `fund_unit` reaches the cost model from both engines and the paper executor; the nine ETF strategies in research 064 were re-run. Monday/Wednesday -85% → +20% |
| T-4007 | ETF results stored before 2026-10-07 | OPEN — any other run that traded an ETF (builder strategies on NIFTYBEES, the US-style signals on Indian ETFs) still carries the old cost until re-run |
| T-4004 | An ETF's open in the panel is its first print | OPEN — NIFTYBEES opens sit up to 20% off the previous close. Any rule reading `open` on a thin instrument reads noise; nothing flags it |
| T-4005 | Nifty futures, daily, from 2015 | DONE — `nifty_futures.jsonl`: every live contract's OHLC, settlement, OI and volume, from NSE's F&O files over four connections |
| T-4006 | Mid caps follow large caps on the real indices | TODO — Sahoo (2022) ran on ETFs listed from 2022; the index history now reaches 2016 |

---

## Missing market data (2026-10-07)

Operator: "now look for missing data to be added in our database", then "yes" to items 1-4 of research 065.
Verify: `uv run pytest -q tests/test_market_history.py tests/test_india_papers.py`; `make market-history`.

| ID | Task | Status |
|---|---|---|
| T-3993 | **Every NSE index, daily, from 2015** | DONE — `ind_close_all` landed for every trading day (`make ingest-nse-daily`): open, high, low, close, volume, turnover, P/E, P/B, dividend yield, for 177 indices incl. the sectorals, Midcap, Smallcap and India VIX. 2,894 days; 9 days in 2015-16 are missing at NSE. `index_history.jsonl`, one line per day; 48 renamed indices joined by closing level |
| T-3994 | **Delivery % from 2015** | DONE — `MTO` files landed for all 2,903 days; `delivery.jsonl` holds traded, deliverable and delivery % per EQ stock per day |
| T-3995 | **Open, high and low for every stock** | DONE — `make rebuild-ohlc` re-read all 2,898 panel days from NSE's archive; `SWAP=1` replaced the panel after all 5,378,038 stored closes were reproduced exactly. The close-only panel is `price_panel.close_only.jsonl` |
| T-3996 | **The real expiry and holiday calendar** | DONE — 144 expiries in `nifty_expiries.json`, each confirmed by its own day's F&O file (two scheduled dates had moved: June 2023, September 2025). They match the weekday rule on every past month, so `india_expiry_day`'s result stands. `nse_calendar.json`: 2,902 trading days, 166 closures. A-041 |
| T-3997 | Nothing reads the delivery table yet | OPEN — index history, OHLC and the futures are used by the strategies in T-4000 to T-4002; delivery % is used by nothing, and no chart or API shows any of them |
| T-3998 | Scheduled holidays and unscheduled closures look the same | OPEN — both calendars are dates with a file. NSE's holiday circulars would separate them (A-041) |
| T-3999 | Items 5-9 of research 065 | TODO — FPI flows, ETF corporate actions, point-in-time index membership, market cap, dated fundamentals |

---

## The Strategies page, as a table (2026-10-06)

Operator: "the ui of the strategy tab is very difficult to understand, ideate other platforms". Modelled on Composer's, QuantConnect's and Streak's strategy lists.
Verify: `make workbench` → Strategies.

| ID | Task | Status |
|---|---|---|
| T-3988 | **Cards with jargon and one number** | DONE — a sortable table: name, equity sparkline, annual return, the Nifty over the same period, max drawdown, Sharpe, win rate, trades and a plain verdict (Beats the bar / Positive, not proven / Loses money / Not run). Filters by market, style, source and verdict. A side panel holds the rules, key stats, Backtest, Full report, How it works and Deploy, with the old detail beneath. The four summary boxes are one line |
| T-3990 | **"Equities (NSE)" and "US equities" listed the same 38 strategies** | FIXED — the filter used every market a strategy *could* run on; it now uses the market of its displayed run (`homeMarket`). Renamed "Equities (NSE)" to "Indian equities". 28 India, 10 US, 10 crypto |
| T-3989 | Win rate and trades are blank for runs recorded before reports carried trades | OPEN — re-running a strategy fills them |

---

## Twenty papers on Indian equities (2026-10-06)

Operator: "gather 20 research paper based on Indian equity market and do backtest", then "whatever done push it, left out backtest we will do later". Research 064.
Verify: `uv run pytest -q tests/test_india_papers.py`; `make india-papers`; Tools → Research Library.

| ID | Task | Status |
|---|---|---|
| T-3985 | **Thirteen Indian-equity papers in the library, twelve backtested** | DONE — 11 read in full, 1 abstract only, 1 unreadable. Strategies in `backtest/india_papers.py`, registered and run 2016–2026, Tier B, after costs. None clears the bar; results in research 064 |
| T-3986 | The seven momentum papers | DONE — abstracts only (SSRN blocks full text); rules assumed where unstated and said so per paper. Backtested; research 064 |
| T-3992 | Twenty more Indian papers | DONE — 19 added (batch A 10, batch B 9 read directly after the batch-B reader stalled for 9 hours on blocked sites). 11 backtested; the rest need sector indices, India VIX, open-to-close fills, OHLC history, or publish no reproducible rule. Research 064 |
| T-3984 | **Named universes are not point-in-time** | OPEN — HISTORY #16. The India-paper strategies re-rank a top 250 at each date; every other daily strategy on `nifty50/100/250` is still biased |
| T-3991 | **CI red: the calendar strategies read the 550 MB panel when built** | FIXED — the registry builds every strategy to check it can be invoked, and CI has no panel. `IndexCalendar` now loads the exchange calendar on first use |
| T-3987 | The intraday-momentum paper could not be read | OPEN — in the library as an idea with no strategy |

---

## Tweezer to the operator's report, and a research library (2026-10-06)

Operator: "tweezer bottom strategy i am providing properly ... build a research paper repo ... every paper have summary, trade idea and implementation logic". ADR-059, research 063.
Verify: `uv run pytest -q tests/test_intraday_tweezer.py tests/test_research_library.py`; `make tweezer-report`; Tools → Research Library.

| ID | Task | Status |
|---|---|---|
| T-3977 | **Tweezer did not follow the operator's report** | FIXED — 15/30/60-minute candles, indicators across sessions over 100 candles, 15:00 signal cutoff, the report's stop formula, no breakeven move, the breakout candle after C2 can fill. HISTORY #15 |
| T-3978 | **The report's result, re-measured** | DONE — not reproduced. 15-minute: PF 1.31, +0.12%/trade, +24% summed after costs vs the report's 2.65, +0.95%, +169% before costs. 30-minute loses. Research 063 |
| T-3979 | **A research library** | DONE — `research/papers/*.yaml`, Tools → Research Library: summary, trade idea, implementation logic, red flags, reported results, linked strategies with results and Backtest. Seeded with the Tweezer report, Mesfin (2026), Zarattini (2024) |
| T-3980 | The paper signals cannot fill on the candle after the signal | OPEN — `bracket.run` skipped `forward[0]` for every caller; Tweezer now passes `first_fillable=0`, the nine paper signals keep the old behaviour until their recorded results are re-run |
| T-3981 | The report's trade list | OPEN — needed to compare trade by trade; its PENDING fill rule and holding limit are unstated |
| T-3983 | **Tweezer Bottom showed "not runnable" on Strategies** | FIXED — only paper signals and weight strategies counted. It now runs through the same intraday batch path (`intraday_runs._run_intraday`) on 15-minute candles, records a result and a report, and scans up to 50 names rather than the paper signals' 12. Verified: Nifty 50, Jun 2025–Jun 2026, report opens |
| T-3982 | Papers added from the page are uncommitted files | OPEN — the API writes `research/papers/`; commit them like any other research |

---

## Strategy builder, rebuilt (2026-10-06)

Operator: "strategy builder is very vague right now ... research better and build whole new strategy builder without any old code preference". ADR-058, research 062.
Verify: `uv run pytest -q tests/test_builder.py`, then `make workbench` → Tools → Strategy Builder → a template → Save and backtest.

| ID | Task | Status |
|---|---|---|
| T-3970 | **A builder you can read back** | DONE — five steps (universe, entry, exit, sizing, risk), rules as sentences, 22 streaming indicators, four templates, a plain-English summary checked by the server on every edit. The old Compose/Code page is removed |
| T-3971 | **Built strategies were never kept** | DONE — saved per workspace, listed in Strategies, backtested through `/api/run/batch` with the full report. The spec digest is in every run's params |
| T-3972 | **Daily rebalancing traded drift** | DONE — `Strategy.hold_unchanged`, read by both engines. Golden cross on nifty100: 1,853 round trips → 39 |
| T-3973 | **The view adjusted the close and not the bar** | FIXED — `PanelRow.adjusted()` divides open, high, low and close. HISTORY #14 |
| T-3974 | Volume is not split-adjusted | OPEN — a split spikes "volume above its average" rules. Needs volume multiplied by the factor in the view; it would change any volume feature |
| T-3975 | Stops are judged on closes, from the signal close | OPEN — intraday stops need the minute bars and a fill-price entry; stated on the page |
| T-3976 | The whole equity panel is slow for a builder strategy | OPEN — about 40s on nifty100–250 over 800 days; "all" (4,000 names) is much longer. The page warns |

---

## Backtest result storage (2026-10-06)

Operator: "check how the backtest results are stored in different platforms and store that one". ADR-057, research 061.
Verify: `uv run pytest -q tests/test_trades.py tests/test_reports.py`, then `make verify`.

| ID | Task | Status |
|---|---|---|
| T-3965 | **A re-run overwrote its report** | DONE — every run kept at `reports/<strategy>/runs/<configuration>/<run_id>.json`; the configuration file is the latest copy. `/api/report?run=` opens an older run, `history` lists them |
| T-3966 | **A result could not name its code** | DONE — `provenance` on every report: run id, time, git commit, uncommitted paths, cost-model stamp |
| T-3967 | **Closed trades existed only in the browser** | DONE — `trades.py`, FIFO round trips with MAE/MFE on adjusted daily closes, plus `trade_summary`. Same rule as `lib/backtestStats.ts` |
| T-3968 | The report page still matches trades client-side | OPEN — it could read the stored `trades` and show MAE/MFE. Left alone because another thread owns that page |
| T-3969 | Intraday trades have no MAE/MFE | OPEN — those paths pass no price series; needs the session candles |

---

## The interface — one home per feature (2026-10-06)

Operator: "make it the same as OpenAlgo's UI, keep one thing in one place". ADR-056.
Verify: `cd web && npx tsc --noEmit && npm run build`, then `make workbench`.

| ID | Task | Status |
|---|---|---|
| T-3956 | **Nine tabs, three places to configure one backtest** | DONE — six pages (Dashboard, Strategies, Charts, Options, Live & Risk, Tools). The Backtest dialog is the only place a run is configured, for one strategy or a selection; the Run tab and the Library's universe and instrument pickers are gone |
| T-3957 | **The Data tab existed and could not be reached** | DONE — it is Data Status under Tools, beside the Strategy Builder and Instruments |
| T-3958 | **⌘K listed things it could not open** | DONE — entries were inert and one ("RUN") did nothing. Every entry now navigates: a page, a tool, or a strategy's explanation |
| T-3959 | OpenAlgo's look | DONE — zinc tokens, icon navigation, card summaries, sentence-case labels, a bottom bar on phones. `app/terminal/shell.css` |
| T-3960 | The Run tab's per-strategy result table has no successor | OPEN — a selection backtest updates each row in place and reports counts; a side-by-side table of the batch just run would need its own place in the Strategies page |
| T-3961 | **The backtest report had no list of trades** | DONE — the report is a page now (`#report/<id>`), laid out after OpenAlgo's results: eight stat cards, then Overview, Equity, Drawdown, Returns, Trades, Instruments and Orders tabs. Round trips are matched FIFO from the fills (`lib/backtestStats.ts`, hand-checked on a five-fill ledger including a partial exit and a short), with win rate, profit factor, expectancy and a CSV export. Drawdown episodes and a monthly-returns heatmap are compounded from the equity curve |
| T-3962 | **Options had no OI tracker, vol surface or straddle history** | DONE — three more Options views after OpenAlgo's tools: OI tracker (support at the largest put OI, resistance at the largest call OI, PCR, OI change against the previous landed day), Vol surface (IV at −10%..+10% moneyness across up to six expiries, read from the OTM side), and Straddle & IV (ATM straddle and IV per day from `GET /api/options/history`, which loops the existing chain endpoint through `options/history.py`; untraded legs are flagged, expiry rolls drawn as rules). Five tests in `tests/test_options_history.py` |
| T-3963 | **No SIP backtester** | DONE — Tools → SIP Backtester: monthly amount, day of month, yearly step-up, 1–10Y, over landed closes from `/api/history`. XIRR by bisection (hand-checked: exactly 10% on a one-flow case, ≈100% on a series that doubles yearly) and a same-total lump-sum comparison. A calculator, not an engine run: no costs, fractional units, not in the trial ledger, and the page says so |
| T-3964 | CSS variables `--muted`, `--fg`, `--line`, `--line-faint` were used but never defined | DONE — aliased in `tokens.css` to the zinc tokens; affected text and rules had fallen back to inherited colour |

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
| T-3311 | Forward-test as an explicit per-strategy stage | DONE 2026-11-02 — ADR-117, `forward.py`: gate PROMOTE + a paper deployment started after it; promoted hypotheses deploy as their card; `/api/deploy/forward` |
| T-4380 | Operator: add `forward_test:` to mandate.yaml (`min_days: 60`, `min_sharpe_ratio_of_backtest: 0.5`, `max_drawdown: 0.25`, ADR-117) | DONE 2026-11-02, on the operator's instruction ("add it"); the operator kept 25% over a suggested 10% |
| T-4381 | A Forward tab on the Deploy page from `/api/deploy/forward` | TODO |
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
| T-3711 | **Delta Exchange India fee model** | DONE — closes S-028 for one venue. 0.02% maker, 0.05% taker, plus 18% GST **on the fee**: a taker round trip is 0.118% of notional. Read 2026-08-22 from two Delta pages that agree on futures (A-025) |
| T-3712 | Options, tax and funding are deliberately absent | OPEN — A-026 to A-028. Two official pages disagree on the options rate; VDA tax is a levy on outcome rather than a cost of execution and modelling it inside a backtest would confuse the two; funding needs a rate feed the platform does not hold |
| T-3713 | **Ten minute-level crypto signals** | DONE — `intraday/crypto_signals.py`. Provenance is a field, not a footnote: **1 paper** (Cohen 2023, AIMS Mathematics, rules read in full), **2 literature**, **7 practitioner with no academic validation found**. Presenting them identically would flatter seven of them |
| T-3714 (FIXED — see T-3846) | The Delta rates are not yet charged by the engine | OPEN — the model exists and is tested, but `_costs_for` hardcodes `Segment.EQUITY_DELIVERY`, so threading an asset class through both engines is the remaining step. Until then crypto still runs `replication`, which is wrong-but-visible rather than wrong-and-silent |
| T-3715 | Crypto minute bars are pruned locally | DONE — superseded by T-3716. `intraday/crypto_store` streams them from B2 |
| T-3716 | **Backtests read the cloud directly** | DONE — `ingest/landing_reader` serves any landing tree from disk or B2, listing the union of both and caching on the way through. Pruning stopped being a reason a backtest cannot run: verified by scanning crypto with `data/landing/crypto` at **0 bytes** |
| T-3717 | **All ten crypto signals are on the UI and runnable** | DONE — routed by asset class, since a crypto signal on RELIANCE is a different question rather than a smaller sample. `par_deviation` and `vwap_reversion` both ran end to end on cloud-only data |
| T-3718 | **The unmodelled crypto cost is not a rounding error** | MEASURED — `par_deviation` took 117 round trips in 60 days across 3 pairs. At Delta's 0.118% that is **13.8% of notional in fees**, turning a reported -8.6% gross into roughly -22.4% net. This is what S-028 means in practice, and why crypto still reports `replication` rather than a flattering `realistic` |
| T-3719 | **Trader snapshot page** | DONE — `docs/RESEARCH/021`. Five bands in the order a person needs them: regime, the map, movers, cross-asset, evidence. Regime comes before price because +0.4% in a calm uptrend and +0.4% inside a volatility spike are different facts |
| T-3720 | **Sector and market cap were in the fundamentals tree all along** | FIXED — the screener scrape landed a four-level `sector` hierarchy and a `top_ratios` section with market cap, P/E, ROCE and ROE, and nothing read any of it. The map had shipped ungrouped with a note saying no such source was connected. `features/company` reads them; `make company-digest` reduces 2,353 Parquet files to one JSON |
| T-3721 | **The snapshot rescanned the panel per day** | FIXED — 400 days against 1.1M rows is roughly 880 million comparisons. It returned to curl in minutes and timed out through the browser's proxy, which is how a "500 error" turned out to be an algorithm. Indexed once by day: 1.9s warm |
| T-3722 | Breadth is the honest index | DONE — a cap-weighted index can be carried by five names while most of the market falls, so advancers-versus-decliners is what actually happened. Today: 1,202 up against 1,415 down on a +1.54% twenty-day proxy |
| T-3723 | The snapshot's three named gaps | **ALL THREE CLOSED** — index levels shipped (T-3792, six India plus six world), news with ticker tagging shipped (T-3749/T-3759), live quotes shipped (T-3772, and T-3809 made the whole India map live). The row stayed OPEN for a day after the last of them landed, which is its own small lesson about task lists |
| T-3724 | **ForexFactory economic calendar** | DONE — `make calendar`, in the daily job. 100 events a week with impact, forecast and previous. Verified: FOMC minutes, UK CPI, Australian employment |
| T-3725 | The calendar is a forward schedule, not a research dataset | OPEN — measured 2026-08-23: `lastweek`/`nextweek`/`thismonth` all 404, and **no `actual` field** in either JSON or XML, so surprise against forecast cannot be computed. It cannot backfill Mesfin's 993-event study. History must be accumulated, which is why the ingest is append-only and merges per ISO week |
| T-3726 | A macro calendar is not the missing *why* | DONE, as a distinction — a CPI print explains why the market moved, not why one small-cap rose 40%. Its own band, saying what it does not cover, rather than dressed as stock news |
| T-3727 | **The catalog was still local-only** | FIXED — `prune-local` moves data to B2 rather than deleting it, so a local glob reported an emptied tree as absent: the snapshot said 4 crypto instruments against 20 landed and 0 mutual funds against 14,280. Reading only the disk was as wrong as reading only the directory entry, one layer up |
| T-3728 | `_has_files` derived the tree name from the wrong path component | FIXED — `root.name` on `data/landing/mf/history` gives `history`, so it searched for a landing tree of that name. Mutual funds reported unsupported while the picker listed 500 of them, and the two disagreed about identical data |
| T-3729 | **My own test left the real EURUSD data hidden** | FIXED — a cloud-read verification renamed the directory aside and its restore never ran, because the command timed out first. The complete 3,481 files sat under a dotfile while the visible directory held only the 516 re-fetched from B2. Merged back rather than deleted, after checking which set was the complete one |
| T-3730 | **FMP news client** | DONE, unwired — `make fmp-probe` and `make fmp-news`. Budget is an explicit argument, not a comment: 250 calls/day means a 15-minute poll of one endpoint is 96 calls |
| T-3731 | FMP's free plan excludes news | ANSWERED, a key arrived — the plan matrix (read 2026-08-23) puts "Financial Market News" on the paid Starter tier. The `demo` key is retired, so the boundary cannot be tested without an account, which is the operator's action. `make fmp-probe` answers it in one command for ten calls |
| T-3732 | FMP `economic-calendar` takes a date range | ANSWERED — **402, paid tier.** if it is free it beats the ForexFactory feed outright, which has neither history nor an `actual` value (T-3725) |
| T-3733 | FMP's India coverage is untested | OPEN — US coverage starts at Starter, and this platform's first market is NSE. A paid tier may still not cover the instruments that matter most here |
| T-3734 | **News provider survey** | DONE — see `docs/RESEARCH/023`. No commercial vendor covers India+US+crypto+FX; the two that might (FMP, EODHD) gate India behind payment and will not let you verify before paying |
| T-3735 | Google News RSS is the only universal per-instrument layer | DONE — `make news`. Landed 3,525 stories across equity/crypto/FX at 92/82/83% on-topic. 100 items for every class tried; 20 NSE symbols in 5.9s at 6 workers, 20/20, no throttling. Carries pubDate, source and a stable guid so dedup is solved |
| T-3736 | NSE announcements need a cookie bootstrap | OPEN, to build — fetch the corporate-filings page first, carry the jar, send a Referer. Without it the API returns an **empty list rather than an error**, which is a silent failure and must be guarded |
| T-3737 | SEC's old browse-edgar atom feed looks retired | OPEN — returned 0 entries on 2026-08-23; `data.sec.gov/submissions/CIK{n}.json` returned 1,001. Anything built on the atom feed should move |
| T-3738 | Yahoo Finance RSS is gone | CLOSED as unusable — 429 on every attempt, retried. Treat as dead rather than flaky |
| T-3739 | The query form was measured, not assumed | DONE — ticker beat company name, 88% vs 83% over ten awkward tickers. So NSE's name list is loaded for **scoring** relevance, not for building the query, which is the reverse of the obvious design |
| T-3740 | Relevance scoring read 0% for crypto and 3% for FX | FIXED — the token table held only NSE names, so `BTCUSDT` was scored against headlines saying "Bitcoin". The items were fine; the scorer was wrong. Now sourced from the catalog, which already carries `EUR/USD` and `AAVE`. 82% and 89% after |
| T-3741 | A pair name must match whole, never by its legs | DONE — "EUR/USD and GBP/USD Outlook" carries both legs of EUR/GBP and is not a EUR/GBP story. Splitting would inflate the match rate exactly where it is least deserved |
| T-3742 | SBIN is the known relevance floor | OPEN, low — registered name "State Bank of India", press writes "SBI", and no part of that appears in ticker or name. 8/20. An abbreviation table would be invented data unless sourced |
| T-3743 | News is landed but not on the snapshot | DONE — the movers band still shows prices without reasons (T-3723). The stories now exist to fix it |
| T-3744 | News dedup is scoped to a month | OPEN, low — Google re-dates evergreen quote pages, so one stable guid can land in two month files and the per-file merge cannot see both. Measured 3 of 3,525 (0.09%), all quote pages not articles. A slow leak rather than a one-off, but a cross-file guid index would be re-read every sweep and grow without bound to catch it |
| T-3745 | News regrouped from daily to monthly files | DONE — 970 files at a **median 877 bytes** became 136. Same shape already recorded as a mistake for FX (T-3710); crypto already stored monthly. Migrated with a guid-level check before any day file was removed: 3,525 records, all 3,522 guids verified present |
| T-3746 | **The test suite talked to Backblaze, and hung** | FIXED — tests calling `catalog.search` transitively listed 34,000 remote keys. One run sat in `SYN_SENT` against B2 for **33 minutes**, burning 5s of CPU, hanging every commit behind it. A hang and a failure look identical from outside, which is the worst property a test can have. Suite now runs offline: **1:49**, slowest test 9.4s |
| T-3747 | boto3's defaults are not defaults this project can wear | FIXED — 60s connect timeout × 5 attempts is five minutes per stalled call, and a pruned tree needs many. Now 10s connect, 30s read, 3 attempts. A handshake that has not completed in ten seconds is not going to |
| T-3748 | `search()` and `capabilities()` could disagree | FIXED — a fixed quarter-share over four hardcoded builders offered mutual funds while the matrix called them unsupported, whenever a class had a snapshot but no history. The split is now derived from the matrix, so the two cannot drift. Verified both ways: offline 3 classes, online 4, each self-consistent |
| T-3749 | **News on the snapshot** | DONE — the freshest strongly-matched story sits under each mover, with publisher and age. A mover with no story says so: a large move without news is a different fact from one with news, and a blank cell would read as "not checked" |
| T-3750 | An unwindowed Google search cannot be shown as news | DONE — measured: **0.8% of 3,525 landed stories were from that day**, 63% one to twelve months old. `when:1d` returns 100% inside 36 hours, newest one to four hours. Live uses 1d, the daily sweep 7d, so the archive stops being a relevance dump |
| T-3751 | Loose matching attributed the wrong company | FIXED — "Reliance Communications (RCOM)" scored as a Reliance Industries story. Two causes: the ticker `RELIANCE` is itself the word, so the ticker shortcut fired on every Reliance-prefixed company; and `NAME_STOPWORDS` dropped "industries", collapsing the name to one token. Attribution now uses a narrower stopword set and needs ticker-or-two-tokens. 11 cases verified including Power and Infrastructure |
| T-3752 | **`capabilities()` enumerated 50,000 remote keys per call** | FIXED — the `_detail()` helpers listed whole trees to build description strings: 34,051 fx keys over 35 paginated requests, plus 14,280 mf and 1,200 crypto. Measured 51–189s **per call**, and it renders on every snapshot. Now a 300s listing cache plus a one-request `any_under` probe for the booleans: 50s cold, **1.8s warm** |
| T-3753 | Snapshot is still slow cold | FIXED — 1:51 cold, 9.7s warm, against 8:19 before. The remaining cost is the first listing of each tree. A local manifest refreshed by `make daily` would remove network from the request path entirely, which is the actual fix |
| T-3754 | `any_under` is on neither protocol, deliberately | DONE — putting it on `ObjectStore` broke 37 sync tests, on `ReadableStore` 9 results tests, both forcing fakes to implement a method those paths never call. Only the landing reader asks, and it reaches the store dynamically |
| T-3755 | **A TTL cache moves the cost, it does not remove it** | FIXED — with a 300s expiry one request in every five-minute window still paid the full 43s, and it was whichever arrived first. Intermittent 43s page loads are harder to diagnose than consistent ones. Counts are now computed once by `make manifest`, in the ingest that changes them, and read from a local file |
| T-3756 | The snapshot listed the bucket to print three numbers | FIXED — `len(catalog.search(asset_class=..., limit=500))` built full instrument lists (34,773 fx + 14,280 mf + 1,200 crypto keys) to display an instrument count. **62 seconds** for three numbers. Now from the manifest, 0.00s |
| T-3757 | `groups or files` rendered "1 mutual fund" | FIXED, caught before commit — mf files live at `mf/history/<scheme>.jsonl.gz`, so the second path level is the literal directory `history` and the census recorded one group, against 14,280 landed schemes. Which number is the instrument count is now stated per tree, not inferred |
| T-3765 | **`make daily` never rebuilt the price panel** | FIXED — its steps ran EOD → OI → fundamentals → MF → calendar → minute → crypto → news → sync → prune, with no `build-panel`. The snapshot reads the panel, so even a working daily job left a stale date on the screen. The bug that made the job fail hid the bug that would have kept it stale anyway |
| T-3766 | `build-panel` must run **after** the sync | FIXED — it reads each trading day from B2, so a day landed locally but not yet uploaded raises NoSuchKey. That is exactly how the first rebuild died at 2026-08-20 with Aug 21 sitting on disk |
| T-3767 | launchd gets a minimal PATH | FIXED — `zsh -lc` does not source `.zshrc`, so `uv` was not found and every step died with "uv: No such file or directory". PATH is now set in the plist rather than left to shell init files, which differ between a terminal and an agent |
| T-3768 | Moving the repo broke the venv and the git hooks | FIXED — editable installs and hook shebangs bake absolute paths. `.venv` rebuilt with `uv sync --all-extras` (plain `uv sync` skips dev, so ruff/mypy/pytest were absent) and `pre-commit install --overwrite` |
| T-3769 | **Sync button on the Instruments page** | DONE — `POST /api/data/sync`, a job rather than a blocking call because a full mirror takes minutes and a proxy cuts the request first. Refuses a concurrent second run. Verified: 355 objects in 174s, manifest recounted |
| T-3770 | Calendar and tape scroll inside their panels | DONE — a hundred events and forty headlines pushed the cross-asset and evidence bands off screen, and the band order is the design |
| T-3771 | Disk is at 99%, 3.9 GB free | PARTLY FIXED — `prune-local` freed 0.83 GB (37,035 files verified in B2 first); 3.8 → 5.6 GB. The repo holds only ~1.4 GB, so the remaining pressure is outside it and is the operator's to judge. Originally: the Next dev server died mid-session under it, and it broke tool output earlier. `make prune-local` reclaims, but the trend needs watching |
| T-3772 | **Live quotes, Zerodha primary** | DONE — `quotes.live()`. Verified live: 23 of 24 movers priced via Kite with change against previous close. Zerodha is primary because it is the venue this platform trades through, so its quote is the price an order would meet |
| T-3773 | Yahoo is implemented and currently blocked | OPEN, measured 2026-08-23 — `query1`, `query2`, v8 chart and v7 quote **all 429 on a first request**. A block on scripted access, not a rate limit earned by traffic; same wall the Yahoo RSS feed hit (T-3738). Written anyway so the fallback exists if it lifts, and the reason is reported rather than shown as an empty column |
| T-3774 | The Kite token expires at 6 AM daily | OPEN, inherent — a regulatory requirement, not a design choice. `live()` returns the broker's own message ("Incorrect api_key or access_token") so the operator knows to mint rather than seeing a blank band |
| T-3775 | Calendar showed 8 of 100 events | FIXED — `high or rows` meant only high-impact whenever any existed, hiding the other ninety-two. Now high-impact first, then filled to the budget: 20 rows (8 High, 4 Medium, 8 Low) |
| T-3776 | News tape 25 → 50, calendar 14 → 20 | DONE — both bands scroll inside their own panel now, so a longer list lengthens the band rather than the page, which is what made the short caps necessary |
| T-3777 | **The Telegram bot token is dead** | OPEN, needs the operator — notifier is built and tested, but `sendMessage` returns **401 Unauthorized**. The credentials are present in `.env` and the token is invalid, consistent with the tracked-`.env` exposure that still needs rotating. A new token from BotFather turns alerts on with no code change |
| T-3778 | There is currently **no** working quote fallback | OPEN, measured — Yahoo 429s on every endpoint and NSE's own `quote-equity` **403s even with the cookie bootstrap** that works for corporate announcements. Zerodha is not merely primary, it is the only source: when the Kite token expires at 6 AM there are no live quotes at all rather than degraded ones |
| T-3779 | The manifest counts the bucket, not what is reachable | FIXED — offline it reported 34,773 FX files that nothing local could open, so the matrix called FX supported while the picker offered none of it. `_census` now returns None when the bucket is unreachable |
| T-3780 | `FX_LANDING.exists()` — a directory entry is not data | FIXED — a prune moves the bytes to B2 and leaves the tree behind, so the raw existence check kept reporting FX supported against an empty directory. Same mistake as T-3727, one tree over |
| T-3781 | A capability assertion kept going stale | FIXED — crypto, then FX, then FX again in the other direction when the prune moved its bytes out of reach. Anything whose support depends on which files are on this disk is a moving target; options do not move, because no strategy path reads the chains at all |
| T-3782 | **The snapshot "500" was a 576-second hang** | FIXED — stack trace at the block: `news.live()` → `urllib.urlopen`. Google News began stalling, `_open` retries three times at a 30s timeout, and 34 symbols at 6 workers is ~576s. The server sat at 0% CPU with nothing logged; the proxy gave up and the browser reported a 500 it never received. **A page that makes a third-party request to render is only as reliable as that third party** |
| T-3783 | The snapshot reads landed news now | FIXED — `news.recent()` opens files and never the network, scoped to the current and previous month because a 36-hour window straddles at most two. `make news` still does the fetching, on a schedule |
| T-3784 | The one remaining live call is bounded | FIXED — quotes run under a 15s deadline. A broker that has not answered by then will not answer usefully, and a snapshot without live prices is a far smaller loss than one that never arrives |
| T-3785 | `capabilities()` was called once per asset class | FIXED — inside the cross-asset loop, unmemoised, so three classes meant three full passes. Hoisted out: 52s → 0.15s cold |
| T-3786 | The census collapsed two different things in one tree | FIXED, caught before commit — `mf` holds 14,280 per-scheme histories **and** one dated enriched snapshot, and `newest` came from the histories. Asking for the latest enriched returned `154641.jsonl.gz`, a scheme code, where `2026-08-21.jsonl.gz` belongs. Census entries are keyed by pattern now. **A count that is merely absent gets noticed; one that is confidently wrong does not** |
| T-3787 | **`make news` was broken and the sweep never ran** | FIXED — `if __name__ == "__main__"` sat mid-module, so `_main()` executed before `live()` and the window constants below it existed: `NameError: DAILY_WINDOW`. Moved to the end with a note. This is why the archive had not grown |
| T-3788 | The archive covered 15 symbols; the snapshot asked about movers | FIXED — the sweep ran the top 25 by liquidity, so the corpus held large caps while the band asked about the day's movers, which are usually small caps nobody swept. Widened to 120. Landed 2,951 new stories across 150 symbols |
| T-3789 | The tape was mover-scoped and therefore empty | FIXED — `recent_all()` reads market-wide. The per-mover *reason* must be about that mover or it is a false explanation; a tape is just what happened, in order. 0 → 50 stories |
| T-3790 | A quarter of the tape was generated pages | FIXED — 56 of 200 (**28%**) were "ETH price range on Aug 24, 2026 at 12am EDT" template pages, one per coin per hour. Not wrong, just not news, and at that share they push out what is. Filtered on **read**, never on ingest: a filter is a judgement, and a story deleted at ingest cannot be reconsidered |
| T-3791 | Movers still show no reason | OPEN — 0 of 33, because today's movers are small caps outside the 120 swept. Widening the sweep to reach them costs one query each; the honest alternative is that most small caps have no coverage on any given day |
| T-3792 | **Index levels, at last** | DONE — the page said "there is no index here" since it was built, so breadth had nothing to diverge from. NIFTY 50 / BANK / MIDCAP / IT / SENSEX / INDIA VIX from the broker, plus S&P, NASDAQ, DOW, FTSE, NIKKEI and HANG SENG from FMP |
| T-3793 | **World movers** | DONE — the free FMP tier serves gainers/losers/most-actives at 50 rows each. NSE opens after Wall Street closes and while Asia trades, and this screen had never shown any of it |
| T-3794 | The FMP free tier, finally measured | DONE — a key arrived, so `make fmp-probe` answered what the pricing page could not. **18 of 25 endpoints reachable**: index quotes, movers, sector and industry performance, EOD, profile, treasury rates. **402 on all six news endpoints and the economic calendar**, confirming the earlier read of the matrix |
| T-3795 | `batch-index-quotes` is paid, singular `quote` is not | FIXED — batch answered 402 while per-symbol worked. Seven calls against a 250/day budget, cached ten minutes |
| T-3796 | One refused index was hiding five that worked | FIXED — the loop broke on first error, so a 402 on DAX meant NIKKEI and HANG SENG were never asked. 4 of 7 became 6 of 7 |
| T-3797 | Half the "world movers" were sub-$5 shells | FIXED — raw feed median price **$4.75**, top gainer a $0.52 shell up 57%. A $5 floor keeps 73 of 150 and lifts the median to $18.91. Leveraged ETFs still slip through, so one underlying can appear under three tickers — noted rather than pattern-matched away |
| T-3798 | **`pct()` was rendering quote percentages 100× too large** | FIXED — it multiplies by 100, right for the panel's fractions and wrong for quote APIs that already send percent. NIFTY's +0.20% read "+20.00%" and INDIA VIX's −3.30% read "−330.00%". The live-quote cell had carried the same bug since it shipped |
| T-3799 | The map owned the viewport | FIXED — 2301px to 587px, capped and scrolling inside itself. Page height 5602 → 4499, so movers, world and tape are reachable without scrolling past a full screen of tiles |
| T-3800 | The hero was a 96px number over three lines of caveat | FIXED — 40px, caveat moved to a tooltip. It has to stay reachable, since the number is an equal-weighted proxy and not an index, but not in the largest type on the page |
| T-3801 | **India / US toggle** | DONE — the selected market leads the ribbon and drives which detail bands render. Two states only: this platform has a full panel for one market and quotes for the other, and a third tab would imply a symmetry that does not exist |
| T-3802 | The unselected market stays on the ribbon, demoted | DONE — an Indian trader reads NIFTY against last night's S&P, so hiding the other side removes the comparison that makes the strip worth having |
| T-3803 | **The session line was NSE data under a US toggle** | FIXED, caught on screen — breadth 1,364/1,324, the equal-weighted proxy and volatility are all computed from the NSE panel, and they sat unchanged under "United States". The reader has no way to tell from the numbers themselves that they are Indian. Gated, with a note saying why the US has no session line |
| T-3804 | US sectors as the map's counterpart | DONE — eleven ranked bars from FMP's free sector snapshot. Not a treemap: eleven averages is what the data supports, and a treemap drawn from them would imply constituent detail that is not there |
| T-3805 | **Crypto and Forex as first-class markets** | DONE — four tabs now. Six crypto majors and six pairs, quoted live via FMP's free tier, ranked by move. USD/INR sits second among the pairs because it is what actually reprices an Indian book overnight |
| T-3806 | **A live sweep could not fit the free budget** | FIXED — the expanded sweep is **29 FMP calls** against 250/day. Even a three-hour cache is 232 calls and leaves nothing for anything else; the ten-minute cache I first wrote would have spent the day before lunch. `make world` sweeps once and the page opens the file, which is the division the news band already makes |
| T-3807 | The gap note said "for the US" under every non-India tab | FIXED, caught on screen — the else-branch was hardcoded to the US text, so Crypto and Forex both claimed to be missing a US session line. Each market states its own reason now: crypto has no population to count advancers in, a currency pair has no advancers at all |
| T-3808 | Crypto archive is a month stale, FX ten days | FIXED — crypto's newest landed file is 2026-07 and FX's is 2026-08-14. `crypto_backfill` runs in `daily` but FX has never been in it, and `alt_panel.crypto_daily` reads local disk only, so it returns nothing at all after a prune |
| T-3809 | **India is live** | DONE — Kite quotes **500 instruments in 0.2s**, so the whole liquid universe is six calls and under four seconds. 2,627 of 2,853 quoted; live breadth read 1,800 up / 843 down where the settled panel said 1,364 / 1,324. Substituted into `returns` rather than carried alongside, so breadth, the map and the movers all move together |
| T-3810 | **The session band claimed one date for two provenances** | FIXED — it showed the panel date and "end of day, not live" while breadth underneath was live and the 20-day proxy genuinely was not. Stated per stat now: breadth carries a live dot, the proxy says which close it ends at |
| T-3811 | A persistent freshness stamp | DONE — beside the market toggle, always on screen, saying live-or-EOD and when. The page used to carry a settled date while quoting live prices under it, a disagreement the reader had no way to notice |
| T-3812 | Text under headings moved into (i) | DONE — eight explanatory paragraphs down to three. The movers band's two stacked notes became one status line on the heading; the calendar printed its reason twice |
| T-3813 | FX had never been in `make daily` | FIXED — crypto ran nightly, FX did not, which is why one was a month stale and the other ten days |
| T-3814 | `alt_panel.crypto_daily` read local disk only | FIXED — after a prune it returned nothing at all, reporting 1,200 landed symbol-months as no crypto data. Same defect the catalog had, one layer down. 0 rows became 62 |
| T-3815 | The month filter was sliced, not parsed | FIXED, caught immediately — `relative[-15:-9]` gave `026-07`, which sorts below every real cutoff and skipped the entire archive. Matched with a regex now |
| T-3816 | **Neither archive was stale — both sources publish in arrears** | MEASURED — Binance posts a month once the month has ended, so `crypto_backfill` pulled 10.4M candles and still could not reach August. FXCM simply stopped: weeks 33, 34 and 35 of 2026 all 404. Calling either "stale" pointed at the pipeline when the answer was in the publishing schedule |
| T-3817 | **`make crypto-fill`** | DONE — Binance publishes daily files on the same host in the same format, covering exactly the window the monthly archive does not. First run: **636 symbol-days, 915,840 candles, 28 symbols, nothing missing**. Day files sit beside month files, so readers pick them up unchanged |
| T-3818 | FMP EOD is the general daily filler, with one hole | MEASURED — free tier serves crypto and FX **current to today**, US equities and indices to the last close, and refuses India with 402. The hole does not matter: NSE's own bhavcopy is free, official and already in the daily job |
| T-3819 | Dukascopy can fill the FX minute gap | OPEN — the reader already exists. Ten pairs over ten days is 2,400 hourly requests, minutes rather than the 245 days the full-history backfill measured. Not started |
| T-3816 | **The redesign was verified all along** | RESOLVED — I said three times I could not confirm it rendered, because the browser pane returned blank screenshots. Reading the DOM directly showed every change live: four tabs, the LIVE stamp, all 24 ribbon cells, and the per-stat provenance labels. The tool was failing to capture, not the page, and I should have queried the DOM instead of repeating that I could not see it |
| T-3817 | 74 uploads failed silently in the first sync | FIXED — B2 closed connections under 12-way concurrency. The retry recovered every one: 1,940 crypto objects in the bucket, **0 files on disk missing from it**, verified by set difference rather than by the summary line. A partial failure is easy to lose in the scroll of a per-tree count |
| T-3818 | Stale OPEN rows in this file | FIXED — T-3723 named three gaps (index levels, ticker-tagged news, live quotes) and **all three had shipped** while the row still read OPEN, as had the two FMP questions the key answered. A task list that lags the work is worse than none, because it is trusted |
| T-3819 | **The index ribbon went blank after a prune** | FIXED — `indices.load()` globbed the local directory only, so `prune-local` moving the sweep to B2 read as "no sweep landed" and every index, mover and sector disappeared at once. **The third reader this session written against the disk alone**, after the catalog and `crypto_daily`. The landing zone is the union of disk and bucket, and a reader that forgets it works right up until the next prune. Pinned by a test that patches the reader and asserts the bucket is consulted |
| T-3820 | **A real charting surface** | DONE — TradingView's Advanced Chart: drawing tools, indicators, symbol search, six intervals, and market presets for NSE, BSE, US, crypto and FX. Any symbol can be typed |
| T-3821 | The chart shows **TradingView's data, not ours** | STANDING NOTE — every other number on this terminal is traceable to the panel, the broker or a landed archive. This one is a window onto a third party's feed, and vendors adjust corporate actions differently. **A backtest must never be reconciled against this chart.** Said on the page, not just here |
| T-3822 | `lightweight-charts` was the road not taken | RECORDED — it renders *our* bars with TradingView's engine, which is the honest-provenance option, and it has no drawing tools, no indicator library and no symbol search. Capability won; the banner says so |
| T-3823 | **Yield curve and commodities** | DONE — FMP's free tier serves a full 12-tenor Treasury curve (1M to 30Y, dated) plus Brent, gold and silver. The curve carries its own 2s10s spread, which is the number read off a curve before any other. WTI, natural gas and the dollar index all answer 402 |
| T-3824 | **A rate-limited sweep overwrote a complete one** | FIXED — past FMP's 250/day limit a sweep came back 429 on five of seven groups and replaced a sweep taken twenty minutes earlier: FX, movers, sectors and commodities to zero, the curve gone, and the new file's timestamp making the wreckage look fresher than the data it destroyed. `land()` now refuses to write a sweep that fills fewer groups, and says it discarded one. Two tests, both directions |
| T-3825 | The `__main__` block was mid-module, again | FIXED — appending `treasury_curve` after it gave `NameError` when `_main` called `land()`. **The identical mistake was made in `ingest/news.py` earlier the same day**; appending to a module is not free when the module executes something partway down |
| T-3826 | I exhausted the FMP daily budget testing | OPEN until reset — the probe, repeated sweeps and this session's testing spent 250 calls. The architecture that keeps a sweep to one a day was built precisely for this and I spent the budget proving it worked |
| T-3827 | **The chart refused NIFTY** | FIXED — "This symbol is only available on TradingView". `NSE:NIFTY` is a real symbol; the **free embed will not render index data**, which is licensed separately from equity data. Charted through NIFTYBEES and BANKBEES, which are ordinary securities tracking the same indices, with the substitution stated on the page — an ETF carries tracking error and its own premium, so it is close and not identical |
| T-3828 | Presets expanded to what actually embeds | DONE — 16 NSE, 12 US, 10 crypto, 9 FX and a Macro set: US 2Y/10Y/30Y and India 10Y yields, WTI, Brent, gold, silver and VIX. TVC aggregates embed where the underlying exchange feeds do not |
| T-3829 | **A free source for everything FMP paywalls** | DONE — TradingView's public scanner: no key, no signup, no daily budget, and **all seventeen series in one request**. It carries WTI, natural gas and the dollar index, which FMP answers 402 for, plus VIX and sovereign yields for seven countries |
| T-3830 | India's 10-year yield, at last | DONE — 6.869%. No other free source tested reaches it, and it is the one an Indian desk actually watches. Germany, Japan, UK and China 10Y came with it |
| T-3831 | Trading Economics is not an option | MEASURED — every guest endpoint answers **410 Gone**, not a rate limit. FRED times out from this machine on every series, repeatedly. World Bank works but is annual: context, not trading |
| T-3832 | **The overwrite guard threw away good data** | FIXED — the first version discarded the whole payload when a sweep filled fewer groups, so a sweep past the FMP limit dropped all seventeen macro series that had succeeded, because they come from a source that is not rate limited. Merged per group now: sources fail independently, so they are kept independently |
| T-3833 | A merged sweep carries two provenances | FIXED — `taken_at` is when the sweep ran while retained groups are older, which is the same defect the session band had this morning. The file names `stale_groups` and `stale_since` rather than leaving one stamp to cover both |
| T-3834 | The curve is drawn, not listed | DONE — inversion is a shape. Four numbers in a row do not answer "is the front end above the long end" at a glance; a line that slopes the wrong way does |
| T-3835 | **Charts from our own bars** | DONE — `/api/history` serves OHLC from the price panel for equities and the landed archives for crypto and FX, drawn with `lightweight-charts` (TradingView's engine, MIT). Verified: RELIANCE, NIFTYBEES and BTCUSDT all return 120 bars. **The same rows a backtest reads, so a chart and a result cannot disagree** |
| T-3836 | The ETF substitution was treating a symptom | FIXED properly — the embed refuses index data, so NIFTY was charted through NIFTYBEES, which is a different instrument with its own tracking error. The panel holds the real series; charting it from our own data removes the licensing question rather than working around it |
| T-3837 | Both charts, side by side | DONE — the embed keeps the drawing tools, ours keeps the provenance, and a reader comparing them can see where a vendor's adjusted close differs from the panel's. Neither pretends to be the other |
| T-3838 | Nothing landed shows the embed alone | DONE — US listings, sovereign yields and the dollar index have no landed bars, so they render the embed without an empty panel claiming otherwise |
| T-3839 | **The macro charts drew nothing** | FIXED — the widget looks for its own container: the script must sit inside a `tradingview-widget-container` beside an empty `__widget` div, and appending it to a bare node renders nothing **silently, with no console error**. Verified after: 17 iframes at 589×180, correctly labelled |
| T-3840 | The lazy mount was a bad trade | FIXED — an IntersectionObserver saved seventeen script loads and cost the charts entirely whenever it did not fire. The widgets are small; a chart that sometimes does not appear is worse than one that always loads |
| T-3841 | Two charts per row | DONE — `auto-fit` packed four or five across on a wide screen, small enough that a trend could not be read off them, which is the whole reason for drawing a line instead of printing a number. Fixed at two, one on narrow screens |
| T-3842 | **Six macro charts were empty boxes** | FIXED — `TVC:US10Y`, `US30Y`, `DE10Y` and `GB10Y` answered "No data here yet"; `IN10Y` and `JP10Y` answered "This symbol is only available on TradingView". **I verified every symbol against the scanner and assumed the widget served the same set.** They are different products with different licensing, and nothing in the code showed the difference |
| T-3843 | Charts drawn from ordinary securities instead | DONE — ETFs, the class the embed serves without complaint: USO, BNO, UNG, GLD, SLV, CPER, UUP, SHY, IEF, TLT. Each labelled as the fund it is, not the concept it stands for |
| T-3844 | Bond ETFs move **inversely** to yield | HANDLED — a chart of TLT rising is the 30-year yield falling, so labelling one "US 30Y" would draw the line the wrong way round. Named as funds, with the direction stated on each |
| T-3845 | **Macro history accumulated from each sweep** | DONE — the scanner has no history and the widget refuses most series, so the only reliable line is one we build. Every sweep appends 17 rows; after a fortnight there is a fortnight of curve. Same shape as the calendar ingest, for the same reason: the source publishes a present, not a past |
| T-3846 | **The Delta fee model is charged at last** | FIXED — `bracket.py` hardcoded `Segment.EQUITY_INTRADAY`, so every crypto backtest paid STT, SEBI turnover fees and stamp duty on a venue that levies none of them. Measured on one BTC fill: 0.0373% as Indian equity against **0.0590% on Delta**, an undercharge of 58% per fill |
| T-3847 | **All ten crypto signals lose on Bitcoin** | MEASURED, 84 sessions to 2026-08-23 — 0 of 10 profitable, best −5.94%, worst −13.44%. **Fees are 88% of the loss**: −₹942,949 net against −₹110,226 gross, with ₹832,723 paid to the venue across 787 fills. Mesfin's friction ceiling again, in a different market |
| T-3848 | What the cost fix was worth | MEASURED — charged as Indian equity the same runs would have shown −₹636,676 rather than −₹942,949, **understating the loss by ₹306,273**. Still losing either way, so the verdict holds, but by a third less — the difference between "unviable" and "close enough to keep tuning" |
| T-3849 | My own filler broke every crypto read | FIXED — `crypto-fill` writes one file per day and `crypto_store` parsed only monthly names, reading `08` as the year and `01` as the month: `month must be in 1..12` on every fetch. Both shapes matched explicitly now |
| T-3850 | **US daily bars landed** | DONE — 501 S&P symbols, **737,351 bars** from 2016, 9.4 minutes, 142 MB. In B2: 36,446 objects. Alpaca's multi-symbol endpoint is what made this a ten-minute job instead of the multi-day rationing FMP's 250-a-day budget implied |
| T-3851 | The S&P list is landed but not used to select | DONE — ADR-008 rejects published index membership for backtest universes: today's 502 applied across 2016-2026 silently drops everything removed in that decade. Landed dated for labelling; the tradable universe will be ranked from turnover the way `all_liquid` is |
| T-3852 | **Pagination was silently truncating** | FIXED — `daily_bars` never followed `next_page_token` despite a helper existing for it. Twenty symbols returned exactly 10,000 bars — the cap, not the answer — and four symbols got nothing because the first sixteen used the budget. 16 of 20 became 20 of 20 |
| T-3853 | Minute history starts 2024, not 2016 | MEASURED — 2016 and 2020 return **zero** minute bars while daily reaches 2016 on the same key. Asking for 2016 returns success and nothing, so a backfill written the obvious way lands an empty archive and reports success |
| T-3854 | Minute backfill is sized to the disk | DONE — ~2 MB per symbol-year gzipped, ~3 GB for the full window against ~4 GB free. Fetch → sync → prune per 25 symbols, so the local footprint stays at one batch. **A batch that fails to sync is not pruned**, because a prune after a failed upload is data loss |
| T-3855 | The backfill log is empty | OPEN, minor — Python buffers stdout off a tty, so a multi-hour job writes nothing until it exits. `python -u` fixes it; the running job was left alone rather than restarted and losing its progress |
| T-3856 | **Delta is primary for crypto quotes** | DONE — Delta is the venue this platform would trade crypto on, so its mark is the price an order would meet, and the fees already charged against these strategies are Delta's. Quoting one venue's price against another's costs was a mismatch. FMP stays as the fallback |
| T-3857 | Open interest and funding, at last | DONE — Delta publishes both per contract. `funding_drift` is named for a number this platform could not previously measure, and A-026 records funding as unmodelled because there was no source. There is now |
| T-3858 | The crypto previous close is reconstructed | STANDING NOTE — Delta publishes a 24h percentage move, not a prior close, so the close is derived from the move. Every other `Level` carries a real prior close; this one is inferred, and the code says so |
| T-3859 | Delta's BTCUSD is not Binance's BTCUSDT | **SETTLED** — one is a USD-margined perpetual with a contract value, the other a spot pair, and the archive this platform holds is Binance. They track closely and are not the same instrument, so a Binance-vs-Delta backtest difference could be a contract-spec artefact rather than a venue effect. Must be settled before comparing |
| T-3860 | **I reported local counts as bucket counts** | FIXED — `landing_reader.available()` returns local ∪ remote by design, so a pruned tree still reads as present, and I used it as a bucket count. Reported 36,451 US objects in B2 when 12,763 were there; the S&P snapshot read as uploaded and was **not in the bucket at all**. Caught when a sync said "802 uploaded, 0 already there" for files I had called safe. Remote-only counts from here |
| T-3861 | The batch sync was rescanning the whole landing zone | FIXED — the runner shelled out to `sync_cloud`, which relists every tree to decide what to upload: fx 34,773, mutual funds 14,286, US bars 36,446. **One batch took 29 minutes** of relisting to move a few megabytes, which is ten hours of syncing for three gigabytes. Calls `sync_directory` in-process against one directory now, and a batch syncs in seconds |
| T-3862 | **The ten crypto scans are on the UI** | DONE — recorded into the result store with `asset_class: crypto`, `cost_mode: realistic`, `universe: BTCUSDT` and the venue in params, so nothing here can be read as a gross-of-costs equity number. Sharpe is computed from **per-trade** returns rather than a daily series, because one trade per session is not a daily series and treating it as one overstates the sample |
| T-3863 | **US minute bars complete** | DONE — **502 of 502 symbols, 71,074,407 bars in 8h03m**, 15,944 objects verified in B2. One sync failure held its batch rather than losing it and cleared on the next pass. Disk ended **higher** than it started (6.8 GB vs 3.9) because nothing accumulated |
| T-3864 | The census did not know the US tree existed | FIXED — a tree absent from `TREES` is invisible to the capability matrix and the instrument counts, which read the census rather than the bucket. 71 million minute bars would have sat in B2 while the US tab reported holding nothing |
| T-3865 | **Corporate actions landed** | DONE — 15,629 rows over 128 months: 15,525 dividends, 95 forward splits, 9 reverse splits. The equity panel currently **infers** these from price jumps; this is the record of what actually happened |
| T-3866 | US news landed | DONE — 410 rows with article body and publisher-assigned tickers. FMP answers 402 on every news endpoint; the Google News layer has headlines only and infers relevance from the title |
| T-3867 | **A fourth local-only reader** | FIXED — `sp500_symbols()` read the local directory, so after a prune it returned an empty list and `land_actions` exited on `if not symbols` **reporting success having fetched nothing**. After the catalog, `crypto_daily` and `indices.load`. Each works until the prune, which is the step that proves the data is safe |
| T-3868 | `merger` and `spinoff` are not valid action types | FIXED — the endpoint answers **400** and rejects the whole request rather than returning fewer categories, so one bad name cost every action |
| T-3869 | **The venue mismatch is immaterial** | MEASURED 2026-08-25 — Delta's BTCUSD perpetual and Binance's BTCUSDT spot agree within **0.026%** on daily closes, against a round-trip fee of **0.118%**, four times larger. So the Binance archive is a fair proxy and re-running the ten signals on Delta prices would not move the conclusion: **the fees are the whole story**, which is what the backtest already said |
| T-3870 | Delta candles landed | DONE — 5,275 daily rows across six majors, 176 objects in B2. Daily rather than minute: a minute archive here would duplicate the Binance one at four times the storage for a difference smaller than the spread |
| T-3871 | **I described the adjustment system wrongly, repeatedly** | CORRECTED — I said several times that the panel "infers splits from price jumps". It does not. `corp_actions/` builds a **bitemporal factor store**, and `panel.py` stores what the exchange printed precisely because a static panel cannot hold point-in-time adjusted prices — a strategy deciding in January must not see prices adjusted for a May bonus. The machinery was right; only a US feed was missing |
| T-3872 | Alpaca actions wired into the existing engine | DONE — 15,629 translated: 15,525 dividends, 104 splits, 433 symbols. Verified against known events: NVDA 4:1 in 2021 and 10:1 in 2024, AAPL 4:1 in 2020 |
| T-3873 | **`Kind.SPLIT` takes face values, not ratios** | FIXED — it means an NSE face-value change and its multiplier is `face_value_from / face_value_to`, ignoring the ratio fields entirely. Filling in ratios gave `multiplier=None` on all 104 splits. That was the **lucky** failure: `Kind.BONUS` would have returned 1.5 for a 1:2 doubling and nothing downstream would have objected to a plausible wrong number |
| T-3874 | **The US tab reads real bars** | DONE — 257,013 rows across 501 symbols in a derived panel. Breadth 322 up / 176 down, 499 tiles all sector-tagged, movers from our own bars. Band computes in 0.8s, snapshot warm 4.1s. The tab has shown a quote ribbon since it existed because there was no US panel; there is one now |
| T-3875 | **A narrow `except` killed an hour-long build** | FIXED — the handler caught `(OSError, ValueError, FileNotFoundError)` and botocore raises `EndpointConnectionError`, which is none of them. One transient blip at symbol 280 of 502 discarded everything fetched. Broad now, and it **reports what it skipped**: 18 of 12,550 files, which is a different thing from zero and the row count alone cannot say which |
| T-3876 | **Paper links in the (i) button** | DONE — `paper_url` and a served `/api/paper/{id}` PDF. Matched on citation prefix rather than stored per signal: seventeen signals cite six sections of one paper, and repeating a URL seventeen times is seventeen chances to drift. 10 of 32 strategies carry a link, 9 with the PDF present |
| T-3877 | **A strategy optimizer, with the cost made visible** | DONE — `make optimize`. Sweeps each strategy on its paper's `recommended_class`, records every configuration to the trial log, and reports trials before and after plus the t-statistic the new count demands |
| T-3878 | **Optimising is not free here, and the number proves it** | STANDING — 12 trials had been spent, ever. The deflated-Sharpe and t-stat corrections take the **total** count as denominator, so every sweep permanently raises the bar for every result. First sweep of `orb_breakout`: best +31,399 against a median of +4,011 on 9 fills — the best is **8× the median**, which is the shape of variance, not edge. The paper's own 1.4 stop returned +3,691; the sweep's "winner" is 2.0 |
| T-3879 | The sweep refused an invented parameter | DONE — the first space swept `target_r_multiple`, which does not exist on `PaperRules`. Every strategy errored rather than silently ignoring the unknown key, which is the behaviour worth keeping |
| T-3880 | **Ten of twenty-one strategies were being swept on the wrong market** | DONE — nine cite Mesfin, tested on MNQ (Micro E-Mini Nasdaq 100 futures); one cites Zarattini, tested on ~7,000 US equities. All ten were evaluated on `RELIANCE`. Nothing errored: every one produced a plausible number. `orb_breakout` on RELIANCE showed best +31,399 against median +4,011 — an 8x spread reading as one lucky parameter. On QQQ it is +25,668 against +19,622, a 1.3x spread. The wrong market gave a *differently shaped* answer, and the shape was the finding. ADR-043 |
| T-3881 | **A US minute reader, cut to the cash session** | DONE — `intraday/us_store.py`. The 71M Alpaca minute bars were unreachable from any backtest because `candles_for` knew only NSE and crypto. Alpaca's bars include pre- and post-market, so an opening-range signal read an 08:01 pre-market print as the open; the session filter lives at the read where every signal inherits it, computed in `America/New_York` because a fixed UTC offset is an hour wrong from November to March |
| T-3882 | **US trades were being charged Indian STT and stamp duty** | DONE — `costs/us_equity.py`. `asset_class="us"` fell through to `Segment.EQUITY_INTRADAY`; a QQQ trade paid STT, SEBI turnover, stamp duty and GST. Exactly the error the Delta model was written to fix, arriving from the other direction. Rates verified against FINRA Information Notice 03/17/26, not assumed: Section 31 is **$0.00/million through 2026-04-03 and $20.60 after**, so it is a dated schedule, not a constant. The first draft hardcoded $27.80 — the fiscal *2025* rate. A-029 |
| T-3883 | **This reframes the crypto result** | STANDING — the finding on record is that all 10 crypto signals lose on Bitcoin and 88% of the loss is Delta's 0.118% round trip. The same round trip in US equity is **0.002%**, a fiftieth. So "these signals do not work" was never the right reading; "these signals do not work *at Delta's fee schedule*" was, and the US sweep is the first evidence that can separate the two |
| T-3884 | **`orb_in_play` never finished, and had the wrong baseline** | DONE — it ran 17 minutes at 99% CPU on 22,000 bars before being killed. Two bugs in one function: a full window scan nested inside a loop over the window (cubic overall, once per bar), and a baseline averaging **every** prior session when the paper specifies 14 — on a 58-session backtest that is a 58-day mean and a materially less selective screen. Now bounded, memoised per session, and 84s. The memo key fingerprints the first bar's OHLCV, not its timestamp: every US series here starts at the same instant, so a timestamp key served SPY's baseline to a QQQ scan |
| T-3885 | **`_session_bars` made every signal quadratic** | DONE — it filtered the whole window to re-find the ~390 bars already at its tail, on every one of 22,000 `detect` calls. Bars arrive sorted so the session is contiguous; walking back from the end returns the same list. `ou_reversion` went 30s to 0.9s, `orb_breakout` to 1.07s |
| T-3886 | **All 20 strategies swept, each on its paper's market** | DONE — 6 of 20 had any profitable setting, all six on US bars. Every one of the 10 crypto signals loses on every setting tried. Only 1 of 20 had a best more than twice its median, which is the sweep behaving: on the right market, most of these results do not hinge on the parameter |
| T-3887 | **A Sweep tab, and deliberately no button on it** | DONE — `/api/optimize` serves the last recorded sweep; `OptimizeTab` shows best beside median with equal weight plus a best÷median column. There is no "run sweep" control anywhere in the UI: every candidate spends a permanent trial against the deflated-Sharpe denominator, and that cost belongs to an operator running `make optimize` on purpose, not to whoever clicked a tab |
| T-3888 | **The best÷median column is withheld when the median loses** | DONE — a strategy losing on every setting (−100 best, −110 median) would otherwise report a tidy 0.9, which says nothing in the vocabulary of a healthy result. The API sends null and the table shows an em dash |
| T-3889 | **Two more whole-window scans, found by the sweep not finishing** | DONE — `session_momentum` recomputed ATR over all 120,960 crypto bars per bar (~4e10 ops, 32 min CPU without finishing one setting); `trend_pullback` did the same with `sma`. Both bounded: 51s and 8.6s. The ATR bound is an approximation (~1e-9, documented); the SMA bound is exact in real arithmetic and *less* float-drifted than the whole-window form, since `sma`'s running sum accumulates error with distance walked |
| T-3890 | **Every paper link in the sweep was empty, and one in the (i) button too** | DONE — two separate silent failures. The endpoint passed a strategy id to `paper_url`, which takes citation text. And `[paper] Cohen, G. (2023)` never matched the `Cohen (2023)` key, because the classification tag sits in front of the citation — so `par_deviation` showed no source while citing one. 11 of 20 rows now link, 9 with a local PDF. `volume_climax` still resolves to nothing and should: it mentions Mesfin in passing but is a practitioner construction, and attributing it to a paper would be the worse bug |
| T-3891 | **US results were dollars wearing a rupee sign** | DONE — every backtest in this app had been NSE, so `₹` was hardcoded everywhere. QQQ and SPY are quoted in dollars and the SEC/FINRA fees are dollar amounts, so a US row labelled ₹ is off by the exchange rate and reads as directly comparable to the India rows. Currency is per market now. Crypto is marked $ because the notional genuinely is, though its fee model charges 18% Indian GST on a dollar notional — a question about the cost model, flagged rather than papered over |
| T-3892 | **CLI and UI disagreed about the same run** | DONE — the CLI said "1 of 20 had a best more than twice their median", the tab said 3. The CLI's test misreads a negative median: `gap_fill_fade` at +$3,729 best against −$3,980 median has a best that is *entirely* tail, and `spread > 2×abs(median)` scored it as narrow at 7,709 against a 7,960 threshold. Both use share-of-best-above-median now |
| T-3893 | **The optimised parameters are the strategy now** | DONE — `intraday/tuned.py` reads adoptions from the recorded sweep and `paper_scan` runs them by default, so a backtest, a paper run and a live signal all use the tuned value. 6 of 20 adopted; 14 kept their published parameters because every setting in their grid lost. Four of the five changes move the stop the same way, 1.4 → 1.0 ATR |
| T-3894 | **The bar was reading the wrong ledger, and understating itself by 10×** | DONE — **the important find of this session.** There are two: `validation/ledger.py` (19 hash-chained validated results) and `features/trials.py` (192 configurations evaluated). The multiple-testing correction wants the second and was reading the first, so a 180-trial sweep left the noise bar at 1.88 when the search it had just performed put it at 2.78 — and the results that sweep selected were judged against a bar never charged for the search that found them. Exactly the failure `features/trials.py` warns about in its own docstring. `searches_run()` now sums both. Nothing sat between the old and new bar, so raising it disqualified nothing |
| T-3895 | **A full backtest report, not a summary of nine** | DONE — `AdoptedReport` leads the library drawer: equity curve, net beside gross beside costs, Sharpe against the bar, max drawdown, win rate, best and worst session, how trades ended and why the signal declined. The sweep grid sits below it, where it belongs: it is evidence for the parameter choice, not the result of the strategy |
| T-3896 | **The row was captioned with a different run than it displayed** | DONE — `gap_continuation` showed "equity · nifty50 · 12" and an NSE equity curve beside a QQQ result, because the tag, the graph and the number came from three different runs. Market, instrument, session count and curve all now come from the adopted run. `clears_bar` was reading the stored Sharpe while the row showed the adopted one, so two strategies could get opposite verdicts under the same rule |
| T-3897 | **The (i) button contradicted itself** | DONE — it said "stop 1.4 → 1.0" two blocks above "Stop at the range high minus 1.4 x ATR(14)", because the logic steps are static strings in the declaration. Named explicitly rather than pattern-substituted into the prose: rewriting sentences by matching numbers eventually replaces one that meant something else |
| T-3898 | **The drawer carried two contradicting accounts of one strategy** | DONE — caught from a screenshot. The fact grid read straight from the daily result store, so a QQQ report showing 20 fills over 58 sessions sat directly above "nifty50 · 179 fills · 90d · −7.1%", both presented as fact. It also listed Universe twice and Instruments/Names-traded, which are the same thing. The grid now describes the run shown above it, the caveat describes that run's weaknesses, and the "Full analysis" button — which opens the *daily* engine's report — reads "Report is above" for a swept strategy rather than silently offering a different run |
| T-3899 | **Every winning exit in the repository was billed Indian STT** | DONE — **the most consequential bug of the session.** `bracket._cost` took `asset_class` with a default of `"equity"`, and two of its six call sites — the target-1 and target-2 exits, which are the *winning* legs and the most common — forgot to pass it. Entries and stops were billed correctly; profitable exits were billed NSE STT, SEBI turnover and stamp duty regardless of venue. A US sell that should have cost $10 cost $167. It was invisible because the number it produced was plausible. The default is gone: a missed call site is now a TypeError, not a wrong number at the end of a backtest |
| T-3900 | **US and FX are backtestable from the UI** | DONE — `AssetClass.US`, `alt_panel.us_daily()` from the 257,013-row Alpaca panel, and a `_load_alt` branch. FX and mutual funds were already supported by the backend and simply never offered by the dropdown, which was hardcoded to equity and crypto. The daily cost path is routed by asset class too, so a US daily run is not charged Indian STT — the same fix as the intraday one, in the other engine |
| T-3901 | **Both US brokers, priced from one run** | DONE — INDmoney (0.25% a leg capped at $25, plus GST) and Firstrade ($0 commission, regulatory only). Sizing depends on risk and stop distance, never on cost, so the fills are identical under both and only the bill differs; the second figure is recomputed from the same trade list rather than simulated again. Firstrade is worth 3-9% of net on the profitable signals — real, and not the difference between working and not |
| T-3902 | **US is selectable, searchable and backtestable** | DONE — `AssetClass.US` reached the capability matrix, the instrument catalog, the backtest dropdown, the Instruments tab and the intraday symbol selector. Each was a separate place that had to be told, which is the actual lesson: adding an asset class is five edits, and missing any one of them fails in a way that reads like absent data. `orb_breakout` on QQQ over 90 days now runs from the UI: Sharpe 5.37, 24 fills, $1,799.50 of cost at INDmoney's rate |
| T-3903 | **US search timed out at 90 seconds** | DONE — `us_instruments` globbed `us/minute/*/*.jsonl.gz`, enumerating 71 million bars across tens of thousands of B2 objects on every keystroke. Symbols come from **directory names** now, which survive a prune and answer "which symbols exist" without touching the bucket: 0.00s for 504 symbols. One implementation in `us_store.symbols()`, shared with the picker, so the two cannot disagree |
| T-3904 | **Intraday US backtests failed with "no symbols with minute bars"** | DONE — `_intraday_symbols` knew crypto and NSE; `us` fell through to the NSE store, matched nothing, and produced an error that reads like missing data rather than a missing branch. The 71M US minute bars were reachable by the sweep and unreachable from the UI at the same time |
| T-3905 | **Every strategy backtested on US equity, not just the ones whose paper used it** | DONE — `make us-all` runs all 20 on QQQ at INDmoney's rate. 7 of 20 made money. Spends one trial per strategy and says so: a signal on an instrument it has never seen is a new configuration, unlike `adopted-results` which re-runs recorded ones and spends nothing. Ledger 192 → 212, bar 2.783 → 2.812 |
| T-3906 | **A crypto signal that works on US** | STANDING — `session_momentum` returns −$78,281 at Sharpe −12.08 on BTCUSDT and **+$10,225 at Sharpe +1.40 on QQQ**. The only one of the ten to cross over, and the finding most easily missed: its home-market row shows a large loss, so nobody opens it. The library row carries a "works on US" badge for exactly this case. It does not clear the 2.81 bar and is not a result — it is a reason to sweep it on US rather than to trade it |
| T-3907 | **The same signal, two instruments, very different answers** | STANDING — `orb_in_play` returns Sharpe 3.31 on SPY and **0.12 on QQQ** over the same window. It is a relative-volume selection signal, so this is not noise between two large-cap index ETFs; it is the screen behaving differently on a broad benchmark than on a concentrated one. Both runs are shown, because reporting either alone would be a claim about "US equity" that the other contradicts |
| T-3908 | **Every NSE minute bar was being read three times** | DONE — **the most damaging find yet.** The archive's 60-day chunks overlap: three files each cover 2026-06-02 for `NIFTYBEES`, so the reader returned 1,125 rows for a 375-minute session. Every indicator counts bars, so a 60-period mean covered twenty real minutes and session volume tripled. Every NSE intraday result this platform has produced was computed with its lookbacks divided by three, including the `RELIANCE` sweep this session opened with. `fetch` deduplicates by timestamp now, later chunk winning |
| T-3909 | **Four NSE adaptations, and they do not work** | DONE — `orb_breakout_in`, `gap_continuation_in`, `ou_reversion_in`, `orb_in_play_in`: separate registry entries sharing the US `detect` functions, swept 36 trials on NIFTYBEES. Three lose on every setting; the fourth makes ₹523 on 3 fills. Diagnosed rather than shrugged at: NIFTYBEES rejects "range closed down" 17,268 times against QQQ's 12,574 and yields 7 plans against 24. The ETF is too quiet for an ATR-scaled opening-range trigger — which is a fact about NIFTYBEES, not about Indian equity |
| T-3910 | **A subset sweep silently un-adopted everything it did not mention** | DONE — `tuned.load` and `adopted_run` both read only the newest sweep document. `make optimize ONLY=` writes a document containing only what it swept, so the four-strategy NSE run dropped the twenty already measured, with no error. Both read every recorded sweep now, later overwriting earlier per strategy, and `adopted.merge` replaces `write` wherever a subset can be passed |
| T-3911 | **The bracket exemption claimed to be a property and was a list** | DONE — `{*SIGNALS, *CRYPTO_SIGNALS}` had to be edited for every new source of bracket signals, which is what a list is. Now `ALL_SIGNALS`, the set `paper_scan` actually dispatches on: a strategy is bracketed iff the scanner can run it |
| T-3912 | **Signal-specific sweep grids, chosen from why each failed** | DONE — the optimizer swept `stop_atr_mult` and `target_r` for everything, which are the two knobs every bracket signal shares and therefore the obvious sweep and often the wrong one. A signal with no gross edge cannot be rescued by where it takes profit. Each NSE adaptation now gets a grid picked from its own diagnosis: selectivity for `ou_reversion_in` (costs 3× gross), opening-range length for `orb_breakout_in` (7 fills, 17,268 "range closed down" rejections), gap threshold for `gap_continuation_in`, the relative-volume screen for `orb_in_play_in` |
| T-3913 | **Optimising NIFTYBEES: one of four improved, and it still does not clear** | DONE — 36 trials. `ou_reversion_in` went from −₹9,080 to **+₹13,714** on `ou_entry_z=-2.0, ou_lookback=120`, Sharpe 2.25 against a bar of **2.899**. Profitable and still short. The other three did not improve; `gap_continuation_in`'s "best" of 0 is **0 fills** — a threshold high enough to stop it trading, which the sweep reports as break-even and is not |
| T-3914 | **My stated hypothesis was wrong, and the grid says so** | STANDING — I predicted `ou_reversion_in` would improve by trading *less*, since costs were three times gross. The winner trades 53 times against the original 56. It won on a longer lookback (120 vs 60), not on selectivity. Worth recording because the outcome improved anyway, which is exactly when a wrong mechanism goes unnoticed |
| T-3915 | **The winner sits at the corner of its grid** | STANDING — `ou_entry_z=-2.0` is the shallowest threshold tested and `ou_lookback=120` the longest window. An optimum on the boundary is not bracketed by the search: the true best may lie outside it, and the reported figure is the edge of what was looked at rather than a peak that was found. Only 3 of 9 settings were profitable and the median lost ₹8,002 |
| T-3916 | **The first out-of-sample evidence this platform has produced** | DONE — `make walk` cuts the sessions into six blocks, holds two out at a time in every combination (15 splits) and estimates PBO through the existing `validation/statistics` machinery. Everything before this was in-sample: the noise bar corrects for *how much searching happened*, which is a real correction and not the same as testing on days the choice never saw |
| T-3917 | **The extended grid brackets its winner** | DONE — `ou_reversion_in`'s optimum sat on the boundary at `entry_z=-2.0, lookback=120`. Extended to −1.5 and 240; the same setting still wins, now with tested neighbours on both sides. It is a peak, not a slope. PBO 0.07, and it holds up out of sample — though only 8/15 splits make money and Sharpe 2.25 is under the 2.99 bar |
| T-3918 | **A high PBO has two opposite meanings** | DONE — and reading the number alone gets one of them backwards. `orb_breakout` is PBO 0.47 with **9/9 settings profitable out of sample**; `ou_reversion_in` is PBO 0.07 with **5/16**. The first is a flat grid where the ranking is noise because the parameter does not matter; the second is a narrow one where the search reliably finds the few that work. `verdict` reports the profitable share beside the ratio (A-039) |
| T-3919 | **This revises the final selection** | STANDING — I picked `ou_reversion` on in-sample flatness. Out of sample it is the weakest of the four: 11/15 splits against 13/15 for the other three, and the lowest Sharpe. **`orb_breakout` is the pick**: 13/15 splits, 9/9 settings profitable out of sample, Sharpe 3.69. Flatness read from the in-sample grid was the right instinct measured on the wrong sample |
| T-3920 | **One source for asset classes, after three copies drifted** | DONE — `BacktestDialog`, `RunTab` and `InstrumentsTab` each carried a private `<option>` list. US was landed, panelled, costed and sweepable while all three offered only NSE, crypto and funds; FX had been runnable longer still and appeared nowhere. `lib/assetClasses.ts` is the single source |
| T-3921 | **US looked absent because the capability check hung** | DONE — the capability rows asked for tree `"us"` with a `bars/...` pattern, but the manifest keys them `us/bars` and `us/minute`. Every lookup missed the census and fell through to enumerating the whole US minute prefix in B2 — tens of thousands of objects, which does not return inside a web request. The instrument table came back empty and US read as data the platform did not have. Same shape as the `root.name` bug `_has_files`'s own docstring describes: a tree name that does not match what the manifest wrote. `capabilities()` went from hanging to **0.11s** |
| T-3922 | **FX enumerated 34,051 keys on every page load** | DONE — 21.7s inside a call the picker makes on load, and most of why the page stalled. `_has_files` learned this one layer up and its docstring says so; the builder underneath kept doing it to answer a count. Counted from local month directories now, 0.03s. Labelled **months**, because the day files are pruned to B2 and calling months "days" would understate twenty-five-fold while looking right. Cold mixed search: 35s → 13s |
| T-3923 | **Intraday runs stored a Sharpe and no report** | DONE — the daily engine wrote a report; the intraday engine never had. So every intraday backtest anyone ran from the interface produced a number with no way to see what it was made of, and "Full analysis" opened a dialog saying no report existed. A bracket trade becomes one entry row plus one row per exit, which is what makes the attribution reconcile — it does, to a residual of $0 |
| T-3924 | **The report was filed under a hash nothing would look up** | DONE — `_run_intraday` derived the configuration from its own `Run`, using `tier` from the request ("A"); the recorder builds one using `tier` from the payload ("intraday"). Two hashes, and the report landed under the wrong one. The material is carried out and saved by the recorder, where the configuration is a property of the run actually stored |
| T-3925 | **Disabling "Full analysis" stranded the last run** | DONE — I disabled it for adopted strategies on the reasoning that the report above is the real result. That left an operator who ran a backtest with no way to open it. A result someone explicitly asked for has to be reachable whatever else the row shows; the button reads "Last run" and says what it opens |
| T-3926 | **The report was written in rupees for a dollar run** | DONE — `ReportDialog` hardcoded ₹, right while every backtest was NSE and wrong the moment a US run could be opened. Bound to the report's own market, so switching runs in the picker switches currency with them |
| T-3921 | **The instrument picker enumerated the bucket and hung** | DONE — three separate calls did it. The US capability rows asked for tree `"us"` with a `bars/...` pattern while the manifest keys them `us/bars` and `us/minute`, so every census lookup missed and fell through to listing the whole US minute prefix — tens of thousands of objects, which does not return inside a web request. `fx_instruments` globbed 34,051 keys for a per-pair count, 21.7s. Cold `/api/instruments` went from hanging → 500 to **13.4s**, and the US-only call to 1.8ms. The same tree-name mistake `_has_files`'s own docstring warns about |
| T-3922 | **A backtest you ran had no result you could open** | DONE — two bugs stacked. I had disabled "Full analysis" for adopted strategies on the reasoning that the report above it is the real result, which stranded any run executed from the dialog. And the intraday engine had **never written a report at all**, so even reachable runs opened an empty dialog. `_run_intraday` now produces report material and the batch recorder files it under the run's own configuration hash |
| T-3923 | **The report hash has to come from the recorded run** | DONE — my first attempt rebuilt a `Run` inside `_run_intraday` to derive the hash. It used `tier="A"` from the request while the recorder writes `tier="intraday"` from the payload, so the report landed under a configuration nothing would ever look up. Deriving a hash in two places means deriving it differently |
| T-3924 | **A full report for all 24 strategies, not just whatever was last run** | DONE — `make adopted-results` records each strategy's standing result as a real `result_store.Run` and files a report under its configuration. Every one opens from the library with per-instrument attribution reconciling to zero residual, the drawdown window, cost drag and the full order ledger. `ou_reversion`: $34,062 change, Sharpe 3.22, 147 orders, 116× turnover, $4,337 of cost |
| T-3925 | **The fill extraction is shared, so two reports can be compared** | DONE — the batch API and `adopted_run` both need to turn a scan into report rows, and a strategy whose report came from a different code path than its neighbour's is a strategy whose report cannot be compared to it. `intraday/report_material.py` is the one implementation. One row per bracket leg, with the whole trade's cost on the entry row: splitting it across legs would be inventing a breakdown, and collapsing the trade to one row would report half the turnover |
| T-3926 | **The adopted curve is P&L, the report wants equity** | DONE — caught before running rather than after. `compute` builds cumulative P&L from zero; `reports.build` wants an equity path from `starting_cash`. Handing the raw curve over would have drawn a strategy that made $27,855 as one that lost 97% of the account, and every derived metric would have looked precise the whole way down |
| T-3927 | **One stored run per strategy, and the denominator survives it** | DONE — 68 superseded runs dropped across 31 strategies. The *payloads* go; the **count** does not. `Best.runs` is the denominator of the selection-bias correction — a Sharpe of 2.19 means one thing as the only run and another as the highest of forty — so each keeper carries `superseded` and reports the sum. `ou_reversion` has one row on disk and the same denominator of 3 it had before |
| T-3928 | **No "best version" of a strategy, anywhere** | DONE — the keeper is the *adopted* run, never the highest Sharpe. A max over stored runs is a biased estimator of any one of them, and choosing one in storage would smuggle that bias where nothing downstream could see it. Where a strategy does best is a question about **markets**, answered by a derived tag |
| T-3929 | **A tag for the market each signal does best on** | DONE — computed at read time from the runs that exist, never stored: it is a `max` over two numbers, and freezing it would make a third artefact to keep in step with the two it came from. 10 of 20 do best away from their paper's market, marked `↗`. `session_momentum` is why it earns a place on the row: crypto paper, loses on BTCUSDT, **makes money on QQQ** — and nothing in the row said so before |
| T-3930 | **A backtest report with an actual chart** | DONE — the report's only picture was a 280×64 sparkline, which is a shape rather than a chart: you can see a line went up, not when or how far it fell. Now a full-width equity path with the starting balance drawn as a baseline (without it a losing run and a winning run have the same silhouette) and a drawdown panel beneath it. The run picker is gone — with one stored run there is nothing to choose |
| T-3931 | **Audit: one bug shape has caused most of this session's defects** | STANDING — a plausible default silently applying the wrong thing. `asset_class="equity"` billed crypto Indian STT, then US Indian STT, then every *winning* exit Indian STT. A tree name that missed the manifest enumerated 71M objects. Three hardcoded asset lists drifted. Newest-only reads un-adopted 20 strategies. A hash derived twice diverged. In every case the wrong output was **plausible**, which is what let it live |
| T-3932 | **`asset_class` no longer has a default at the dispatch point** | DONE — `bracket.run` required it and mypy immediately named the one caller relying on the default: the NSE Tweezer scanner, where `"equity"` was *correct*. That is the finding, not a footnote — the same default made one call accidentally right and three others silently wrong, and only being forced to state it distinguishes them |
| T-3933 | **Eight stores hold evidence; nothing knew all eight existed** | DONE — `make evidence` enumerates every one with its row count and whether the noise bar is charged for it. The bar bug was not in either file: two answered "how many configurations have been evaluated", the bar read one, and the denominator was 10× short. A test holds `evidence.bar_denominator()` equal to `budget.searches_run()`, so a new counted store that is not wired in fails rather than quietly lowering the bar |
| T-3934 | **The census missed a store in the module written to stop that** | DONE — `rglob("*.json")` does not match `.jsonl`, so 39 workspace runs read as zero. Caught by looking at the output rather than by trusting it |
| T-3935 | **Five money formatters, three signatures, one currency bug** | DONE — `money(v)`, `money(v, market)` and `moneyIn(class)(v)` across five components; the one that took no market wrote ₹ on dollar figures. `lib/money.ts` is the only one now and **market is required**: formatting money is a decision about which market the number came from, and a function that cannot see the market cannot make it |
| T-3936 | **The daily engine's US cost routing had never executed** | DONE — **found by the audit, and it was my own incomplete fix.** A `us` branch was added to `vector._costs_for` and none of its three callers passed `asset_class`, so every daily run including US was charged Indian *delivery* costs while the code above them said otherwise. The same shape as the bug it was meant to fix, one layer up |
| T-3937 | **One cost router, replacing three that had diverged** | DONE — `bracket._cost` knew crypto, US and NSE-intraday; `vector._costs_for` knew US and NSE-delivery and had **no crypto branch**; `server.COSTED_CLASSES` decided separately whether to charge at all. `costs/router.py` owns it: venues are an enum, uncosted ones are named rather than falling out of a missing branch, and an unknown class raises instead of guessing. A test asserts the two engines agree on venues they share and differ only on the NSE segment, which is the one difference that is real |
| T-3938 | **`asset_class` threaded to every call site mypy could find** | DONE — removing the default named 30-odd sites across `vector`, `event_driven`, `execution`, `paper/runner`, `stress`, `selftest`, `gate_acceptance`, `montecarlo` and the API. Most legitimately mean `"equity"` and now say so. The only default left is on `paper.run`, where it is the **account's** property rather than a guess about the data — a distinction that makes it safe there and unsafe everywhere below |
| T-3939 | **Mutual funds enumerated 14,280 keys on every keystroke** | DONE — 18.7s per call, eleven of the thirteen seconds the instrument picker took. Unlike FX and US this one **cannot** be answered from local directory names: fund history is flat (`mf/history/119551.jsonl.gz`), so a prune leaves nothing behind. Cached per process instead: 18.5s → 0.01s on repeat, with the first call still paying. Recording the code list in the manifest would remove even that and is the right fix if it matters again |
| T-3940 | **Two files, one schema, and a comparison encoded as a filename** | DONE — `adopted_results` and `us_all_results` held the identical 25-field row, separated only by what they were called, and `_best_asset` opened both and `max`ed across them. `strategy_results.jsonl` carries a `kind` column, so the comparison is a query: a third question about a strategy becomes a new value rather than a new file, a new reader and a new `max`. `merge()` keys on `(kind, strategy_id)` so a subset run cannot wipe the other kind — the failure that has already happened twice |
| T-3941 | **Five provenance chips competing with one number** | DONE — the row carried PBO, "tuned", "best: QQQ", "intraday" and the market: five chips saying three things, with the market stated three times over. One chip now, showing only the most surprising fact, with the rest in its tooltip. A strategy on its paper's market with published parameters and unremarkable PBO gets **no chip at all**, which is the right amount of attention for the unremarkable case. `session_momentum` reads "wins on QQQ ↗" |
| T-3942 | **The panel layer and intraday runner left the HTTP module** | DONE — `api/server` held four unrelated jobs: parsing HTTP, loading panels, running intraday signals, building reports. `api/panels.py` (145 lines of data access, including the dispatch that decides what data a backtest *sees*), `api/intraday_runs.py` (190 lines of engine work), `api/requests.py` (the shapes both need). The seam: **nothing in either module knows about HTTP** — they take a request object for its fields and return plain dicts, which is why they could move and why keeping them there was arbitrary. `BatchRunRequest` had to move too, or extracting the runner would have imported the transport module from the module extracted out of it. server.py 3,597 → 3,256 |
| T-3943 | **The docs-check hook caught a commit with no rationale, and I batched past it** | STANDING — the server split was rejected for touching `src/` with no docs entry. Correct behaviour. The next commit carried its own docs, so the un-documented files rode along inside it: the guard held on the commit it examined and the change still landed undocumented. **A pre-commit gate that only inspects the current staging area cannot stop work being swept into a later commit** — worth knowing before trusting it as the last line of defence |
| T-3944 | **The docs did not know about four venues** | DONE — `ARCHITECTURE §4.2` described the Indian charge stack as though it were the whole cost model, which it stopped being when crypto, US and FX arrived. It now carries all four with the two counter-intuitive facts stated: US is the *cheapest* venue and only because of the $25 cap, and which venue a trade pays is a required argument everywhere because the default produced four wrong-number bugs in sequence |
| T-3945 | **Three architectural decisions had no ADR** | DONE — ADR-045 (one cost router, no default venue), ADR-046 (one reader for eight evidence stores), ADR-047 (one result file with a kind column). Each records the bug that motivated it, the options rejected, and what the choice does *not* fix |
| T-3946 | **The optimisation pipeline had no home in the docs** | DONE — `ARCHITECTURE §5.5` and a runbook. Four commands, what each spends, and the two results that are routinely misread: a sweep's best without its median, and a PBO without its profitable-settings share. The runbook leads with the trial cost because that is the part that cannot be undone |
| T-3947 | **130 of 177 modules were unreachable from the docs** | DONE — pre-existing, not this session's doing, and a line per module would have gone stale before it was useful. `ARCHITECTURE` gained a **package** map instead: 22 packages grouped by what they are for — data in, deciding, judging, acting, serving — each naming the two or three modules worth opening first. Packages change rarely; files change weekly. Every module is now reachable, verified by script rather than by eye |
| T-3948 | **Every backtest died: `Object of type date is not JSON serializable`** | DONE — **my own regression.** `_run_intraday` began handing report material out through the result dict — `date`s and dataclasses, for the recorder to consume once — and the batch cache tried to serialise the whole payload. `write_cached` drops underscore-prefixed keys now, which is not a workaround for the serialiser but what a cache *means*: a hit says the run did not happen again, so there is no new report to write. A public key that will not serialise still raises, because that is a real defect and swallowing it would hide a lost field |
| T-3949 | **The fund-history ids live in the manifest, so the first search is free too** | DONE — the leftover from T-3939. `build()` already walks every key, so recording the 14,280 leaf names costs nothing it was not paying. Cold picker: 18.5s → **3.3s**; the mixed search 13.4s → 3.1s. Only `mf` records ids — `us/minute` alone is 15,952 keys and storing every tree's would bloat the census for no reader |
| T-3950 | **I wrote the tree key wrong, for the third time in this codebase** | STANDING — `ID_TREES` was `{"mf/history"}`, which is what the *pattern* suggests; `TREES` calls it `"mf"`. A name that does not match what the manifest records reads as "no such tree" and falls silently through to a bucket enumeration. Caught by checking rather than by the tests, and now asserted: `ID_TREES <= {key for key, _, _ in TREES}` |
| T-3951 | **A backtest spent 98.8% of its time listing four files** | DONE — profiled rather than guessed. Loading QQQ's bars took **58.65s** and the scan the operator was waiting for took **0.72s**; of the 58, **42.7s** was `_months()` listing four objects. `_remote_listing` listed the *whole tree* and filtered in Python — 52,000 objects to find four — while `_literal_prefix`, written for `has_any`, sat unused beside it. Scoping the listing: full US backtest **59s → 2.25s**, and the numbers are byte-identical, because it changed how much is asked for and never which paths match |
| T-3952 | **The row said "running…" and threw away what the job reported** | DONE — the API already reports which symbol it is scanning and how far through it is; the row discarded all of it. Now `1/1 12s` with the full message on hover. The elapsed count is the part that matters: without it a two-second wait and a two-minute one feel identical, so every wait feels unbounded |
| T-3953 | **Your backtest ran, stored, reported — and changed nothing on screen** | DONE — my regression. `_headline_sharpe` preferred the adopted result unconditionally, so running a strategy over a longer window looked like it had not happened. Recency decides now: the adopted result is what a strategy shows **until someone asks it a newer question**. The adopted run is excluded from the comparison, or it would perpetually supersede itself |
| T-3954 | **A date range and a starting amount, both askable** | DONE — the presets always end *today*, so "how did this behave through 2022" could not be asked at all. `start`/`end` override `days` when both are set; one alone falls back rather than guessing, because a start with no end could mean "until today" or "for N days" and picking one silently answers a different question |
| T-3955 | **Custom capital reported twice the return it earned** | DONE — **found by checking the arithmetic, not by a test failing.** A ₹5 lakh run reported 5.57% where the ₹10 lakh run reported 2.6% — exactly double. `scan_many` was called without `equity`, so it sized every position against the default million while `total_return` divided by what the operator asked for: the same trades in the numerator, half the capital in the denominator. Position sizing is a fraction of equity, so halving the account must halve the P&L and leave the percentage alone. It now does: 27,855 → 13,053, 2.79% → 2.61%, the residual being the $25 cap taking a larger share of a smaller trade |
| T-3951 | **"Whatever date range I choose I see one backtest"** | DONE — two causes. The report showed only the **traded** window, so a 90-day and a 180-day request both read `2026-05-29 → 2026-08-20` with 24 fills and looked identical — while returning different P&L, because the longer request fetched three more sessions of leading history that moved the ATR warmup and the early stops. Asked-for, seen and traded are now three separate numbers on the report |
| T-3952 | **Removing the run picker stranded six runs** | DONE — I removed it when `prune-runs` left one run per strategy, which stopped being true the moment anyone ran a second backtest. Seven had accumulated and only the newest was reachable. Restored as chips rather than a dropdown: the point is comparing them, and a dropdown shows one label at a time |
| T-3953 | **Every intraday run's Sharpe was overstated by ~40%** | DONE — **the most consequential find here.** `_run_intraday` built its equity curve from trading days only, so a signal firing on 24 of 63 sessions produced a 24-point curve with no flat days. The report claimed "invested 100%, 0 flat days" of a strategy flat two thirds of the time, volatility was measured only over days it acted, and the Sharpe read **5.37 against the 3.24** the same run scores when sessions are padded. `SignalScan.session_pnl` had the correct treatment and the docstring explaining it; the API path did not use it |
| T-3954 | **A return figure with nothing to compare it to** | DONE — `benchmark.py`. `orb_breakout` returns +2.6% on QQQ; QQQ **fell 2.7%** over the same sessions, Sharpe −0.53, worst fall −11.3%. Difference +$52,963. Deliberately buy-and-hold of *the instrument traded*, not an index: an index measures stock selection the strategy never claimed, while holding isolates the only claim it makes — that timing the thing beats holding it. Exposure is reported beside it rather than folded in, since the two are not risk-equivalent |
| T-3955 | **Two interfaces, one of them unmaintained** | DONE — `/` and `/terminal` grew in parallel reading the same API. The root page still had its own fleet table, instrument picker and equity chart, none of which had learned about US equity, the cost router or walk-forward. `/` redirects now; 1,508 lines removed. A second interface is not a spare, it is a second thing to keep correct, and the one nobody looks at is the one that quietly goes wrong |
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
| T-3336 | Kite adapter has never met the real API | OPEN — the tests prove contract conformance, not that Kite accepts these calls. Needs a market session and credentials. The riskiest untested part is the rejected/unreachable split: it keys off substrings in Kite's error text. Step 1, read-only: `make kite-readonly` after `make kite-login` (2026-11-02). Step 2, one small supervised order: operator only |
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
