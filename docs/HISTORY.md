# What was built, and what it got wrong

*The project's memory. Every sprint that ran, what it produced, and — the part
worth keeping — where it was mistaken. Replaces eighteen separate sprint review
files, which were per-session artefacts and had stopped being read.*

**Why keep the errors.** Three times a conclusion stated confidently in one
sprint was overturned by a stronger test in a later one. A record that lists
only what worked would have let each of those be re-derived from scratch. If
you are deciding whether to trust a number in this repository, this page is
where you find out what has already been found wrong.

---

## The record

| # | Built | Verify | Outcome |
|---|---|---|---|
| 0 | Repo, `make verify`, docs gate, typed config | `make verify` | Complete |
| 1 | NSE EOD ingest — 11y daily, 6y participant OI, 5y minute bars (173M rows) | `make check-landing` | Complete |
| 2 | Options chain recorder | — | **Not built.** Needs a VPS; every day unrecorded is data that cannot be bought later |
| 3 | Security master: identity, time-versioned lots, calendars, succession | `make check-master` | Complete — 6/6 |
| 4 | Bitemporal read API + lookahead firewall | `make test-lookahead` | Complete |
| 5 | Corporate actions + adjustment engine — 25,713 actions | `make check-adjust` | Complete — 7/7 |
| 6 | Data quality engine: gaps, OHLC sanity, MAD spikes, staleness | `make quality` | Complete |
| 7 | Options quality: parity, monotonicity, convexity, own IV | `make quality-options` | Complete |
| 8 | Feature library (10 features) + IC harness | `make ic` | Complete — **figures since invalidated** |
| 9 | Cost model: brokerage, STT, stamp, GST, exchange fees | `make check-costs` | **Partial** — never met a real contract note |
| 10 | Tier A vectorised backtester | `make backtest-fast` | Complete — **headline conclusion was wrong** |
| 11 | Tier B event-driven backtester | `make backtest` | Complete |
| 12 | Engine self-tests — the project's most important gate | `make test-engine` | Complete — 10/10 |
| 13 | Overfitting battery: CPCV, DSR, PBO, MinBTL, stress, trial ledger | `make validate` | Complete |
| 14 | Promotion gate + mandate, locked holdout | `make gate-acceptance` | Complete — killed the only candidate |
| 15 | Paper scout, hypothesis cards, search budgeting | `make scout` | Complete |
| 16–18 | Research loop: codegen, critic, orchestrator | `make research` | Complete |
| 19–28 | OMS, EMS, order state machine, reconciler, kill switches, paper trading, attribution | `make chaos` | Complete — 11/11 |
| — | Workbench: UI, sandboxed authoring, model integration, architecture doc | `make workbench` | Complete |
| — | Monte Carlo resampling, ported from TradeMaster | `make montecarlo` | Complete |
| 29–31 | Compliance, static IP, CA review, first capital | — | **Outstanding — operator's work** |

---

## Eighty-seven times this project was wrong

Ordered by how much they mattered, not by when they happened.

**1. Download time was being used as knowledge time.** (Sprint 4) Every landed
file recorded when *we fetched it* as when the information became knowable. The
median gap between real publication and our download was **1,820 days** — five
years. Every backtest built on it was silently reading the future. Fixed by
separating `event_time`, `knowledge_time` and `receipt_time` (ADR-015).

**2. Positions were marked from raw, unadjusted prices.** (Sprint 11) VIVIDHA
went 1,290.55 → 140.75 across an 11:1 action and the engine booked an **89%
phantom loss**. The holder had lost nothing. It dragged an eleven-year
buy-and-hold to −3.3%. Found by disbelieving a number, not by a test.

**3. Sprint 10's headline conclusion was wrong.** Corrected in place by Sprint
11. Non-trading holdings were valued at zero, producing a −50% drawdown that
was an accounting artefact. Two sprints reached opposite conclusions from
different windows of the same data — which is why `by_regime` stress exists.

**4. Sprint 8's IC figures are still wrong.** Computed on **raw, unadjusted**
prices over a 3-year panel. Never recomputed. **T-1317 is still open** — do not
rely on those numbers.

**5. The cost stress test was measuring nothing.** (Sprint 13) It scaled only
*brokerage*, which is **zero** on delivery trades. So "2× costs" quietly meant
"introduce a 0.06% fee that did not exist", while STT and stamp duty — the
charges that dominate — went untouched. It reported 95% of Sharpe surviving 5×
costs. Now the multiplier applies to every charge.

**6. The corporate-action join lost 21.9% of matches.** (Sprint 5) Joining on a
raw ISIN string instead of the internal instrument id. Recovering it moved
factor coverage from 78.1% to 98.1% and restored 3,073 dividend factors. The
same class of bug recurred in Sprint 8's panel (ticker vs ISIN) and was caught
before shipping.

**7. The leakage check condemned 14 of 15 correct paths.** (Sprint 13) It
measured purge gaps against the real calendar rather than the filtered timeline
of days actually present. The test was wrong, not the splits.

**8. Blanket warning suppression hid three real gaps.** (Sprint 6) Suppressing
by category rather than by name. Suppression is now per-finding and named.

**9. The Monte Carlo report printed −2258.9%.** (2026-08-20) Drawdowns were
stored pre-multiplied by 100. The same unit confusion inverted the
shallower-than-median verdict, so it told the operator history had been kind
about ordering when it had not.

**10. The engine's zero-alpha identity cannot catch double-charged costs.**
(Sprint 12) Found by a mutation suite, not by reasoning: both sides of the
identity double, so it stays satisfied. An independent recomputation was added.

**11. A trial was spent by accident.** (2026-08-20) `make gate H=H-0001` was
run merely to check the command still worked. It logged trial #19 — a second
evaluation of an already-killed hypothesis — and moved the noise bar from
Sharpe 1.83 to 1.88 permanently, for every future candidate. There is no
un-spend function and there should not be (T-2609).

**12. CI was red for five consecutive merges while the project reported
itself green.** (2026-08-20) `make verify` passed locally and `STATE.md` said
7 of 7, but every CI run since PR #20 — the workbench sprint — had failed. CI
installs `uv sync --extra dev`, which omits the optional `web` extra, so mypy
could not resolve the `fastapi` import in `src/eulerlab/api/server.py`; the
unresolved module turned all eight route decorators untyped and the type gate
failed. It passed on this machine only because fastapi happened to be
installed in the local venv. **The local pass was an artefact of the
developer's environment, which is the exact failure mode CI exists to catch.**
Two things were wrong at once: the workflow did not install what the type gate
needed, and nobody read the CI result because the local one was green. Fixed
by installing the extra in CI. Worth noting separately: `server.py` still has
no test coverage — no test in the suite imports it — so the type gate was the
only thing checking that file at all.

**And the type failure was hiding two test failures.** Types runs before Tests
in the workflow, so once mypy passed, two tests failed in CI that had always
passed locally. Both read the real `data/derived/trial_ledger.jsonl`, which is
gitignored: 19 trials here, zero in CI. `test_no_history_makes_a_trial_
unaffordable` was the dangerous one — it takes a `tmp_path` and **looks**
hermetic, but the affordability rule it asserts is computed against the ambient
ledger, and on an empty one the bar is Sharpe 0.00 and nothing is ever
unaffordable. It now pins the trial count explicitly. The other,
`test_the_gate_verdict_is_read_from_the_ledger`, genuinely asserts accumulated
project state rather than code behaviour, so it skips when the ledger is absent
and is marked as belonging with `make acceptance`. **The general lesson is that
a green gate downstream of a red one proves nothing** — five merges of "verify
is 7 of 7" covered a suite that CI had not actually finished running.

**13. A re-run destroyed the report it superseded.** (2026-10-06) `results/`
was described as append-only, and it is, but the full report beside it was one
file per configuration, `reports/<strategy>/<configuration>.json`, replaced on
every re-run. So the summary row of an earlier run survived while its orders,
attribution and equity curve did not, and nothing recorded which commit had
produced either. No published number is invalidated: the latest report of each
configuration was always the one shown. Fixed by keeping every run under its
own id with its commit and cost-model stamp (ADR-057).

**14. Corporate-action adjustment moved the close and left the bar behind.**
(2026-10-06) Both engines back-adjusted a view by replacing `close` alone, so a
pre-split bar kept its raw open, high and low around a halved close. Any range
read from `row.ohlc()` — a candle body, an ATR, a 52-week high — saw the split
as a price move. Found while building the strategy builder's ATR and Donchian
indicators. `PanelRow.adjusted()` now divides all four prices. The engine
self-test golden file is unchanged, because its synthetic panel has no
recorded ranges; results of candle-shape strategies on instruments with
corporate actions inside their window may move.

**15. The Tweezer port was not the operator's strategy.** (2026-10-06) The
first port ran on 1-minute candles, restarted its indicators every morning,
moved the stop to breakeven after T1, had no 15:00 signal cutoff, scaled the
ATR stop buffer by entry, and — through `bracket.run` — never let the candle
straight after the signal fill, which on 60-minute candles is the breakout
hour itself. The operator's report specifies 15/30/60-minute candles and none
of the rest. Every earlier Tweezer number (the "2 setups in 136,740 candles")
measured a different strategy. Re-measured on the report's rules in research
063: the report's result is not reproduced.

**16. Named universes are today's list applied to every past date.**
(2026-10-06) `nifty50/100/250` are the most-traded names as of the ranking
date, so a backtest from 2016 runs on stocks chosen for having become liquid
by 2026 — largely the ones that rose. Measured on the Indian-paper strategies:
an illiquid-decile strategy made +4,204% on `nifty250` and +585% on a top 250
re-ranked at each decision date; 12-1 momentum +1,098% against +474%. Every
cross-sectional result run on a named universe is inflated by this, by an
unknown amount until re-run (T-3984). ADR-008 avoided index membership for
this reason and the liquidity list reintroduced it.

**17. NIFTYBEES's 2019 unit split was never adjusted.** (2026-10-06) The ETF
split 1:10 on 2019-12-19 and changed ISIN; NSE's equity corporate-actions feed
does not carry ETF actions, so no factor existed and the engine marked a held
position down 90% overnight. Found when "hold the Nifty in December" lost 88%.
Every result that held NIFTYBEES across that day was wrong — the Indian-paper
calendar strategies, the MACD and moving-average rules, and any buy-and-hold or
index benchmark run through the engine. The beta of every stock against
NIFTYBEES was also distorted by the one-day -90% print. Fixed with a manual
factor (A-043); the affected India-paper strategies were re-run.

**18. The cost model charges an ETF unit the tax on a share.** (2026-10-07)
`costs/model.py` applies STT of 0.1% to both legs of every equity-delivery
trade. A unit of an equity-oriented fund pays 0.001% on the sale and nothing on
the purchase (research 066, from two AMC publications; the statute itself was
not readable). So every round trip in NIFTYBEES, or any ETF, was charged about
0.2% too much. Every ETF strategy in research 064 is too pessimistic in
proportion to how often it trades: Monday/Wednesday (2,054 fills, -85%) paid
₹10.7 lakh of costs on ₹10 lakh, most of it this tax; turn of the month,
expiry day, post-holiday, MACD, the 60-day average, Budget days, December and
the mid-cap lead-lag are all affected. Fixed the same day: a fund unit (an
`INF` ISIN) now pays its own rate in both engines and paper trading, and the
nine were re-run (research 064). Monday/Wednesday went from -85% to +20%,
turn of the month from +15% to +49%, the 60-day average from +155% (Sharpe
0.98) to +192% (Sharpe 1.12). Any other result that traded an ETF through the
engines before 2026-10-07 is still too pessimistic until re-run.

**19. The minute-bar ingest re-fetched the whole year on every run.** (2026-10-09)
`backfill_minute` was described as resumable: "a chunk already in the manifest
is skipped". It cut its 60-day windows from `today - 1 year`, a start that moves
every day, so no window matched a key landed the day before. The 2026-10-08 run
logged `chunks: 2898 total, 2898 to fetch` and pulled 37.6 million bars it
already had; 14,927 of 25,099 neighbouring chunks in the manifest overlap. No
result is wrong: `intraday/store.fetch` keeps one bar per timestamp. The cost
was about fifteen minutes of Kite requests a day and duplicate bytes in B2.
Fixed: chunks are planned from the days each symbol does not hold
(`uncovered_chunks`), and today is fetched only after 15:45 IST. The same day's
plan fell from 3,108 chunks to 210. The overlapping files already landed stay,
because landing is immutable.

**20. Three "opening range" results on NIFTYBEES measured its first print.**
(2026-10-12, research 075) `orb_breakout_in`, `orb_in_play_in` and
`gap_continuation_in` were run on NIFTYBEES and stored as tests of
opening-range rules on the index: Sharpe -3.83, -1.73 and -3.68. The opening
range included the first one-minute bar, and on NIFTYBEES that bar sets the
range's high or low on 99.6% of days and makes it three times as wide (72.7 bps
against 25.2). Research 071 had already shown that print is on average 71 bps
from a fair price. The three numbers are valid measurements of a rule nobody
meant to test. They stay failed and are not re-run; they are not evidence
about opening-range breakouts on the Nifty either way. Shares are affected
far less (the first bar widens the range by about 40%, as an opening auction
would).

**21. A file pruned from this machine could not be found in the bucket by its exact name.**
(2026-10-14, ADR-072) `landing_reader._literal_prefix` returned a pattern's
folders with a trailing slash. For a pattern with no wildcard, such as
`2026/10/2026-10-13_udiff.zip`, that asked the bucket for a *folder* of that
name, and `available` came back empty. While a file was still on disk nobody
saw it. Once the local copy was gone the file read as missing everywhere. The
overnight deployment reads its lot size from the day's F&O file by exact name:
on 13 October the lookup failed, the order was rejected for "lot size not found
in that day's F&O file", and the paper book did not take a signal it should
have. Found while adding gap risk, which needs the same lookup. Fixed: a
pattern with no wildcard is its own prefix. Not re-run: the 13 October night
is not traded after the fact. **Any exact-name read of a pruned file before
this date failed the same way**, and ADR-070 now prunes after every dataset,
so it would have happened every night.

**22. A test that builds throwaway repositories wrote into the real one.**
(2026-10-16) `tests/test_docs_check.py` creates temporary git repositories and
was believed to touch nothing else. Git sets `GIT_DIR` and `GIT_INDEX_FILE` for
a hook run from a linked worktree; the pre-commit pytest hook passed them on,
so the test's `git init` and `git config` ran against the real `.git`. It set
`core.bare = true` and a local `Test <test@example.com>` identity. Every git
command then refused to run in a work tree, and any commit would have been
signed "Test". No commit or ref was changed. Fixed: the fixture removes every
`GIT_*` variable before it runs git; proved by running the test with `GIT_DIR`
aimed at a decoy repository, whose config stayed unchanged. `core.bare` was put
back by hand. The `[user]` section the test wrote was removed the same day at the
operator's instruction.

**23. Both snapshot deadlines were inert.** (2026-10-16) The live map (20 s)
and the movers' quotes (15 s) were each wrapped in `with ThreadPoolExecutor(1)`
and believed to be bounded; the code's own comment said a hung broker could no
longer hold the page. Leaving the `with` block calls `shutdown(wait=True)`,
which waits for the abandoned call. Measured: a 3 s call behind a 0.5 s deadline
returned after 3.0 s. `daily_feed._run_step` had found and fixed the same fault
earlier; these two were never changed. Fixed: `server._bounded` shuts the pool
down without waiting, and a test fails if a deadline waits for the work. No
stored number depended on it; only how long a broken broker could stall the
dashboard.

**24. The research library's AI depended on one free model.** (2026-10-17)
Both drafts (paper summary, strategy code) sent every request to the single
model named in `config/llm.yaml`. When OpenRouter dropped that model's
zero-retention endpoint, every draft failed before it was sent. Its own
"free ZDR" list turned out to be unreliable too: of nine models listed, six had no such
endpoint, two answered 403 ("agentic harnesses only"), and the one that served
took 470 s and broke off mid-reply. Behind that, Next's proxy dropped any
request over 30 s, so a slow success also failed in the browser, and a dropped
connection (`IncompleteRead`) escaped as a 500. Fixed: `chat.complete_any`
walks every model the locks allow, skips refusers for 30 minutes, bounds each
try (150 s) and the walk (420 s); the proxy allows 600 s; a malformed reply
counts as that model failing. No stored result depended on it. What it does not
fix: with Groq's key invalid and Ollama not installed, no model may be up.

**25. Money added or withdrawn was counted as profit or loss.** (2026-10-17)
The engine's own `total_return` was time-weighted and correct, but the risk
page, its live-against-backtest chart, the paper page's sparkline and the
Telegram `pnl` reply all measured equity against the *starting* capital.
Measured on the two deployments with flows: ₹10,000 plus ₹20,000 added showed
**+200.59%**; it had made ₹59, **+0.40%**. ₹1,00,000 less ₹20,000 withdrawn
showed **−19.97%**; it had made ₹35, **+0.30%**. Drawdown and the "last
session" figure jumped on the flow day the same way, and the live line left
the backtest band for no reason. Every since-start, drawdown and band verdict
shown for a deployment with flows before this date is invalid. Fixed:
`risk.book.growth` takes flows out; `tests/test_risk_book.py` pins a deposit
and a withdrawal.

**26. A position rule paid STT to re-size every holding every day.** (2026-10-18)
Research 113's position strategies (`github_daily.PositionRule`) and three
others gave every stock in a trade 1/max(n, slots) of capital. With a hundred
names above a golden cross, each day's change in n trimmed or topped up all of
them: 122,004 fills for the golden cross, 239,553 for MACD, 171,132 for Turtle.
The repositories hold a fixed position to the exit. Fixed: fixed 1/slots, the
longest-held kept. Per year, before -> after: golden cross 12.9% -> 18.3%,
Supertrend 7.9% -> 17.5%, Turtle 7.1% -> 13.5%; MACD +3.1% -> -4.7% and the
high-volume premium 8.4% -> 5.5% (their old versions were costly index funds).
Every first-pass figure for those eight strategies is invalid; research 113
states both.

**27. `--from`/`--to` never reached the daily engine.** (2026-10-18) The batch
read only `days` and ran every daily request over the panel's whole span; only
the intraday path applied an explicit window. Research 113's event strategies,
asked for 2021-08 to 2024-11, ran 2016-2026 and kept trading into 2025, and
were compared with the Nifty over the wrong dates. Fixed: `server.windowed`
keeps a year of warmup before the start, and the adjusted-price cache is keyed
on the window too. Any earlier run that passed `--from`/`--to` to the daily
batch (`make india-papers` defaults among them) ran on the whole panel instead;
for ten-year windows the difference is the last few weeks.

**28. A stock that left the data stayed in the book, and buys spent cash that was not there.** (2026-10-18, finished 2026-10-27)
Both engines kept positions by symbol. A stock renamed while held (TATAGLOBAL
-> TATACONSUM) or delisted had no more prices, so its position could never be
sold and stayed frozen at its last price. Buys were sized on the decision day's
equity and filled whatever the sells raised, so a sell that failed or fetched
less left cash negative: leverage the strategy never asked for. Fixed: the
panel carries each ISIN under its current symbol (`canonical_symbols`); a
holding with no later row is sold at its last price; sells go before buys, and
no buy goes beyond the cash on hand (0.3% held back for charges). Tier B got
this on 2026-10-18 and Tier A did not, so the two engines disagreed (4.5e-05)
until 2026-10-27, when Tier A got the same rules (back to 1.4e-16). The golden
file moved by Rs 74.62 of Rs 16.7 lakh (0.0045%), all from trimmed last buys:
with the cash rule off it reproduces the old file exactly. Any stored backtest
that held a renamed or delisted stock, or rebalanced from a sell that fetched
less than planned, is affected. Measured 2026-10-27 (T-4139) on the 9 equity
strategies that ran on both engines over 3,000 days, Rs 10 lakh, Tier B
(the run was stopped early; 44 others ran only on the new engine, or did not
exist in the old one). Rejected orders fell everywhere (433 -> 0 for buy and
hold). Six of nine moved by less than 0.04 Sharpe. Three moved more:
`fifty_two_week_high` 1.52 -> 2.39 (total return 7.5x -> 41.9x),
`illiquidity_premium` 1.04 -> 1.24, `india_contrarian_36m` 0.13 -> 0.09. Any
stored Sharpe or return for those three from before 2026-10-18 is invalid.
The 41.9x needs its own check before anyone trusts it. The paper attribution split also paired a buy in one
book with a sell in the other on the same day, and stopped closing (Rs 2,875
residual on its test). Fixed the same day.

**29. An F&O stock's minute bars end at 15:14, not 15:29.** (2026-10-26) The
minute ingest, and the first version of provisional bars (ADR-079), took a
session as complete only at its 15:29 candle. From 2026-08-03, F&O stocks stop
continuous trading at 15:15 for the closing auction (A-053), so Kite has no
candle after 15:14 for them. On 2026-10-26, all 210 Kite symbols that ended at
15:14 were stock-future underlyings in the F&O bhavcopy, and none of the 203
that ended at 15:29 were. So the first provisional run left out every F&O
stock as "incomplete" (203 bars where 413 were due). Fixed before commit:
`provisional_daily.session_ends` accepts 15:14 from 2026-08-03. No stored
number changed. Any rule that reads an F&O stock's bars after 15:14 since
2026-08-03 (an exit "at 15:25", an end-of-day-reversal entry, a close taken
from the last bar) never had them. Its intraday figures for those dates need
rechecking (T-4137). For F&O stocks, NSE's close is the auction price, which no
minute bar shows.

**30. FX backtests paid no cost while marked "realistic".** (2026-10-27) The
cost router returns zero for FX, saying the engine charges the bid-ask spread
carried on each row. Neither engine did: `vector.spread_cost` existed,
documented, and was never called, and nothing read `PanelRow.spread`.
`COSTED_CLASSES` includes FX, so every FX daily run was labelled `realistic`
and charged nothing. Found by a dead-code sweep. Fixed: `_costs_for` charges
half the spread recorded on the fill day per unit (`spread`, from
`vector.fx_spreads`) in Tier A, Tier B and the paper executor, which still agree.
No FX result was stored in any workspace, so no stored number changes. Any FX
figure produced outside the result store before this date was frictionless.

**31. On an expiry day the option chain read a contract that had already settled.** (2026-10-27) With no expiry asked for, `_chain_payload` took the nearest expiry, and on an expiry day that is the one settling that afternoon. The bhavcopy is end of day, so the chain was dead: on 27 Oct 2026 the Nifty "straddle" was 45,499.5 with no implied vol. Found building the dashboard's options panel. Fixed: the default is the nearest expiry after the trade date (an expiry asked for by date is still served). Every options history point for an expiry day was wrong; `HISTORY_POINT_VERSION` 1 -> 2 retires the saved points so each is recomputed.

**32. The dashboard's Trend and Participation words had no source.** (2026-10-28) ADR-081 called Trend from Nifty against its 200-day average plus its 3-month change, and Participation from 60/40% of stocks above their 50-day average. Both sets of numbers were chosen without a source. On 2016-2026 data they changed word 16 and 22.6 times a year, and the breadth rule called 10% of the 2021 rally Narrow. Replaced by published rules (research 122, ADR-083): Faber's 10-month rule (2 changes a year) and the 200-day share confirmed by the High-Low Index (10.5). Both still read Downtrend and Narrow on 27 Oct 2026. "Sideways" no longer exists: Faber's rule has two states.

**41. The first futures-to-cash prototype did not implement its frozen rule.** (2026-10-29) The draft calculated a within-contract lookback instead of a front-contract series with correlation from the strictly prior 60 cash sessions. Its one-minute percentage changes also crossed session boundaries, and its bar backtest could hold overlapping positions in the same share. Corrected it to calculate returns within contract and session, select the nearest-expiry contract per minute, pair each futures return with the next cash-minute return using only prior sessions, and block overlapping holds. The draft produced no P&L, so no reported performance numbers need revision.
**33. The configured Groq model had been shut down for ten weeks.** (2026-10-29) `config/llm.yaml` pointed `groq` at `llama-3.3-70b-versatile`. Groq shut that model down on 2026-08-16 and named `openai/gpt-oss-120b` as its replacement (research 123). Nothing noticed, because no code used Groq by default and `health()` deliberately sends no request. The fixed OpenRouter `:free` llama id and the 3B local model were also unused and are removed. No stored result depended on any of them. A model id in config is a claim about a vendor's catalog, and it has a recheck date like any other (A-019).

**34. `make agent` crashed for any agent that found something.** (2026-10-29) `python -m eulerlab.agents.runtime` runs the file as `__main__`, a second copy of the module with its own `Item` class. Workers build items from `eulerlab.agents.runtime.Item`, so the output failed validation and the run ended in a traceback with nothing written. Unit tests call `runtime.run` directly and never saw it; the three launchd agent jobs (T-4179) would have failed every night. Fixed: `__main__` hands over to the imported module's `main()`, and a test runs the module the way `make agent` does.

**35. The API could not start on a clean install.** (2026-10-29) `market_context.py` and `attribution_detail.py` import numpy at server start, but numpy was not a dependency; it was present on the Mac only through another extra. `uv run --extra web uvicorn ...` failed with `ModuleNotFoundError`. numpy is now declared.

**36. The SIP calculator counted a bonus issue as a loss.** (2026-10-30) It read raw closes from `/api/history`, the chart's endpoint, with no adjustment for splits or bonuses. Reliance's 1:1 bonus of 28 Oct 2024 halved the close, so a 3-year Reliance SIP showed XIRR −19.6% and a value of ₹3.42 L on ₹5.40 L put in. Adjusted, it is −5.5% and ₹4.76 L. Found walking the workbench on the operator's data. Fixed: `/api/history?adjusted=true` back-adjusts equity bars with the same factors a backtest uses, and the SIP asks for it. Every SIP figure for a stock that split or issued bonuses inside its window was wrong. None was stored; the calculator records nothing.

**37. An NSE day that was not published yet landed as a day with nothing in it.** (2026-10-30) `nse_reports` landed any well-formed answer and never fetched that day again. NSE's API answers a day it has not published with an empty 200, so short selling for 30 Oct, fetched at 23:26 IST that night, landed with 0 rows and would have stayed empty. Found reading the Deals & filings tab, whose short-selling panel showed 29 Oct. Fixed: an empty API answer within 3 days of its date is not landed; an empty file landed early is fetched again and the new copy lands beside it (`_recheck`), so nothing is overwritten. The one-year backfill landed holidays and this day; the holidays are right, and the 30 Oct file is replaced on the next run. No study read these files yet.

**38. A refused request looked like a timeout once retries ran out.** (2026-10-30) After its last attempt, `Fetcher.get` returned `status=None`, which dropped the HTTP status it had just seen. So a caller could not tell a 429 from a dead connection, and a scraper meant to stop on 429 kept going. The FII/DII backfill test caught it. The status is now kept. No stored data depended on it: every earlier caller looked only at `outcome`.

**39. A brief missing three of its signals went to Telegram looking complete.** (2026-10-31) The first brief in the Trader's read format (ADR-100) ran at 12:17 IST while the workbench API was down. Breadth, FII futures and options were missing; the bottom line read "Mixed, leaning weak ... 2 of 4 signals weak", not the full read's "Risk-off ... 3 of 7", and only a small note said why. It was sent to Telegram. A rerun with the API up was sent 41 seconds later. Fixed (ADR-101): an incomplete read starts "Incomplete: N of 7 signals missing", marks the rows, and Telegram gets one line instead. The 12:17 brief in `data/agents/market_brief/20261031T064745Z-a268d7` is the partial one.

**40. A paper book's drawdown counted a withdrawal as a loss.** (2026-10-31) The first draft of the Trader's read measured drawdown from the raw equity curve, so the ₹20,000 taken out of one `india_sharpe_momentum_opt` book on 16 Oct showed as 23.1% below its peak. The loss limit's time-weighted figure is 3.7%. Caught on real data before the read was merged; the merged code uses the loss limit's figure. No stored number depended on it.

**42. The mandate's t-statistic bar is not checked by the gate.** (2026-10-31) `mandate.yaml` has carried `min_t_statistic: 3.0` since it was written. `gates.py` never reads it: its statistical checks are deflated Sharpe, PBO and backtest length only, and no code anywhere reads the key. Found writing `docs/METRICS/validation/t-statistic.md`. No strategy was promoted on the strength of it: every one evaluated was killed on other checks. Both files are operator-owned, so nothing was changed; T-4250 asks the operator to decide.

**43. The after-close brief described the day before, and briefs ran on non-trading days.** (2026-10-31) `make agents-close` ran the after-close brief at 16:15, but index closes, participant OI and FII/DII flows arrive in `make daily` at 19:30, so the 16:15 note reported the previous session. And nothing checked the calendar: the brief forced on Saturday 31 October repeated Friday's numbers under Saturday's date. Fixed (ADR-105): the after-close note runs inside `make daily` after the data; a weekend or NSE holiday gets a markets-closed note that says so and shows the last session's date, once per break; every brief states its data date. No stored number depended on it.

**44. Sixty-eight stored daily strategies are about three bets.** (2026-10-31) The library lists 68 India daily strategies with stored reports, and research 113 ranked them as if they were separate candidates. `make strategy-map` (ADR-106) measured them for the first time: 39 of them, every momentum, trend, low-volatility and value variant, move together (average correlation 0.79, lowest pair 0.55), and the participation ratio of the whole correlation matrix is 2.78. With Nifty taken out, 17 momentum and trend rules still form one family (0.80) and the count rises only to about 6. An equal-weight book across all 27 families has Sharpe 0.60, and hedged −0.28: most families are single calendar or candle rules that earn nothing. No stored number is wrong, but no combination of these rules can be counted as diversified, and adding another momentum variant buys nothing.

**45. The noise bar assumed a spread of Sharpes twice the measured one.** (2026-10-31) Since Sprint 14 the deflated Sharpe used σ_SR = 1.0 (A-021), a default nobody had measured, and N = trial-ledger rows. Research 138 measured σ_SR across the 68 stored daily strategies at 0.39, and 0.48 across their 27 families. At 19 rows and σ 1.0 the bar was 1.88; with 27 families and the measured σ it is 0.98. The assumption, not the count, was most of the bar. Every "Sharpe 1.88 bar" figure in earlier reviews and in research 113's verdicts overstated the bar by about 0.9. No strategy was promoted or deployed on the old bar; the gate also killed them on other checks. By operator decision (ADR-108) the gate now uses families with measured σ, plus Romano-Wolf StepM over Nifty.

**46. The weekend note could not be found in the workbench.** (2026-10-31) The operator wrote "i can't see weekly brief" the evening it shipped (ADR-105). The note was written and served. Two things hid it. A later run on the same closed day (a Run press, or the evening job) returned "skipped: already written", so the agent card showed a skip and no brief. And "Open the brief" opened the AI tab on Live, not on Market brief. Fixed: every closed-day run writes and shows the note, and only the Telegram message is limited to one per break; "Open the brief" goes to `#agents/brief`, the Market brief view. No stored number was affected.

**47. The idea lab never tested an idea.** (2026-11-01) ADR-089 built the lab to test the research agent's drafts, and ADR-107 lifted its trial limit, but its first run on the operator's Mac tested 0 cards and the trial log holds no `agent|` row. Three causes. It read only the research agent's latest run, whose one draft named a feature the library lacks (`liquidity_beta`). The research agent flagged that draft as waiting for minute bars, delivery and futures data because of words in its abstract, and the lab skips such drafts, so the previous run's buildable draft (1-month reversal and turnover) was never looked at. And research made about one draft a run from one fixed topic, re-reading the same abstracts. Fixed (ADR-111): the lab writes its own formula cards from 13 signal families every day, keeps a memory of every test, reads every untested draft, and hands research its feedback; a draft whose features the library can build is never marked as waiting for data. No stored number depended on it: the lab had produced none.

**48. The idea lab's first results came from stocks that barely trade.** (2026-11-01) The first `make agents-ideas` reported robust Sharpe 5.6 for 21-day low volatility and 3.5 for the share of up days, with no skeptic objection, and called anything with a positive Sharpe a survivor. ADR-111 generated cards without a turnover floor, although `RankAndHold` has documented since Sprint 8 that an unfiltered top-30 book buys stocks trading a few thousand rupees a day, and a long-only book has a positive Sharpe from the market alone. Fixed (ADR-112): a Rs 1 crore floor on every generated card and in its IC screen, survival judged against Nifty, and the first run's own cards left out of the lab's learning. Every number from the lab's runs on 2026-11-01 before this fix is invalid; none reached the gate.

**49. A crashed agent's notes showed where the run started, not where it broke.** (2026-11-01) Since ADR-085 the runtime kept `traceback.format_exc(limit=4)`, which is the four outermost frames: the runtime and the worker's top, rarely the line that raised. Found while building the doctor (ADR-113), which needs the deepest frame to know which file to fix. Now the last six frames are kept. Crash notes in earlier run folders may not name the failing file; no number depended on them.

**50. The workbench judged strategies on a different bar from the gate, and tests wrote into real data.** (2026-11-01, audit) Four faults found by one audit. (a) ADR-108 moved the gate to the idea-family bar (0.98), but every screen (Strategies "Beats the bar", the dashboard count, backtest caveats, deploy preflight, `/api/health`) still drew Sharpes against the ledger-count bar with σ 1.0, so a strategy between the two bars was "below the bar" on screen while the gate would judge it on 0.98. All screens now show the gate's family bar (`search_bar.shown_bar`) and fall back to the ledger bar, labelled, only when fewer than two reports are stored. (b) The deflated Sharpe's kurtosis term was `excess/4`; the paper's `(γ₄ − 1)/4` with raw kurtosis is `(excess + 2)/4`. Fat tails were penalised slightly too little; at a daily Sharpe of 0.1 the denominator moved by 0.25%. Every DSR printed before is very slightly too high; none crossed 0.95 because of it. (c) `test_indices` appended a fake Dollar Index reading (98.9) to the real `data/landing/macro/<today>.jsonl` on every `make verify`, and the dashboard and news tests downloaded NSE's company list into `data/` when it was absent. On the operator's Mac the macro history has one fake DXY row per day `make verify` ran; those rows are `symbol TVC:DXY, last 98.9, change_pct 0.15` and should be ignored (landing is immutable, so they are not deleted). (d) `make install` left out the `web` extra, so a fresh `make install && make verify` failed with 107 type errors.

**51. The OMS counted a partially filled order twice, and the order path promised a defence Kite does not give.** (2026-11-01, audit) `OMS.executions()` summed every fill entry in the journal, but each entry holds the broker's *cumulative* filled quantity (Kite's `filled_quantity` is cumulative). An order seen at 4 of 10 filled, then at 10 of 10 after a restart, counted 14 shares, and reconciliation would report a break that was not there. Fixed: the latest fill entry per order is the whole of it. No paper book was affected: the paper broker fills at once, so no order ever had two fill entries. Also found, not fixed (live is refused in code, S-015): `oms.py` says a duplicate client order id is rejected by the broker as a second line of defence, but Kite does not enforce unique tags and `KiteBroker` never raises `DuplicateOrder`, so the journal lookup is the only defence (T-4348); Kite's order book holds only today's orders, so an order left `UNKNOWN` overnight would be read as never sent (T-4349); and each process has its own rate governor, so two books placing orders at once are not held to 5 a second together (T-4350).


**52. A strategy row mixed two runs, and the macro history was pruned from the disk it was read from.** (2026-11-01, audit on the operator's Mac) (a) The Strategies table showed `momentum_12_1` at Sharpe 1.27, "beats the bar", beside the annual return and drawdown of its latest stored run, whose Sharpe is 0.39 (`data/workspaces/default/reports/momentum_12_1/`). `_headline_sharpe` put the ledger's validated Sharpe ahead of the latest run. It now shows the latest stored run and uses the ledger figure only for a strategy with none, so the row and its verdict come from one run; the count of strategies beating the bar falls from 13 to 12. (b) `data/landing/macro` was empty on the Mac: `prune-local` deletes landed files once the bucket holds them, and `macro.series` read only the local folder, so the fair-value model's India 10-year series had no history. Worse, a day file pruned mid-day was recreated by the next sweep with only the later rows, and the tree upload replaces a bucket object whose size differs, so that day's earlier rows in B2 could be overwritten. Fixed: `macro` is never pruned, `macro.series` reads pruned days through the landing reader, and a tree upload never replaces a bucket object with a smaller local file. Whether any day in B2 already lost rows is not known (T-4353). The seven macro charts on the Charts page are TradingView embeds, not this history; they were blank for a different reason (T-4354). (c) The dashboard showed "Trials spent", a sum of per-strategy counts, beside the bar, which reads as the bar's basis; it now shows the idea families the bar is computed from. (d) The Charts page now draws NSE symbols and the macro series from our own data (ADR-114), and macro readers skip the fake DXY row (98.9, +0.15%) a test used to write into the real folder (T-4347). The first version drew raw daily prices, so NIFTYBEES's monthly chart showed its 2019 unit split (A-043) as a 90% crash; backtests were never affected, they read adjusted prices, and the chart now does too (T-4361).

**53. Split-adjusted prices kept raw volume, and a book's daily returns counted deposits as gains.** (2026-11-01, line-by-line review of the backtester, T-4346) (a) `PanelRow.adjusted` divided open, high, low and close by the split factor but left volume raw, so before a 1:10 split a stock traded a tenth of its true share count in the strategy's view, and any volume-ratio feature (`features/library.py` compares the last five days with the window) read a split inside its window as a tenfold spike. Volume is now multiplied by the same factor; turnover, in rupees, is unchanged. Backtests of volume-based rules whose window straddled a split are changed by this; their stored reports predate it. (b) `TierBResult.daily_returns` divided each day's equity by the day before, so a deposit into a paper or SIP book read as a gain and a withdrawal as a loss, although `total_return` and the loss limits already took flows out. It now does the same. (c) Both engines loaded the corporate-action factor file twice per run and used one copy; the unused load is gone. Not changed, for the operator (T-4363): both engines accept negative weights and hold a short overnight in cash equity, which Indian delivery does not allow, and Tier B's realised P&L treats the proceeds of a short sale as profit. No daily strategy here returns a negative weight today; a pasted one could. The review found Tier A's and Tier B's order of operations, cash checks, delisting exits and next-close fills as documented.

**54. The mirror kept NSE's first copy of a revised file, one segment's revision graded five datasets, and the B2 macro history did lose rows.** (2026-11-01, data checks on the operator's Mac and bucket, T-4353, T-4355, T-4356) (a) The 7 to 9 Oct cash and F&O bhavcopies were not the problem: every re-landing was byte-identical. The index closes were: NSE publishes them and later adds indices, so 11 days (7 to 9, 12 to 15 and 26 to 29 Oct) landed twice with different checksums, the second copy a superset of the first (162 then 167 rows; no row removed, no value changed). `cloud.sync` put a bucket object of the wrong size in `mismatched`, reported it and never sent it, so B2 still held the short file for 15 and 26 to 29 Oct while the manifest named the long one; pruning the local copy would have lost it. Fixed: when the bucket's copy is an earlier landing of ours, the latest is uploaded over it (B2 keeps the old version); anything else is still never overwritten. (b) `check_duplicate_keys` reads the shared `nse` manifest, so the index revision failed the sense check of the cash bhavcopy, the F&O bhavcopy and, through them, the price panel, which is why all three showed grade C. Findings now carry their segment and a dataset is graded on its own. (c) B2's object history shows six macro days that lost rows to the prune-and-recreate overwrite described in #52: 24 Aug (331 rows), 7 Oct (491), 14 Oct (52), 15 Oct (17), 18 Oct (577) and 29 Oct (17). Every lost row survives in an older version. Three of the six were overwritten by a *larger* file, so the smaller-file guard added in #52 would not have caught them; what stops it now is that `macro/` is no longer pruned. Restoring them is an upload, so it waits for the operator (T-4365). (d) Fundamentals stopped because the launchd job is gone: only `briefweekend` is loaded on the Mac, and no plist exists for fundamentals, daily, the agents or the others. The last run, Sunday 18 Oct, lost the network after about 40 symbols (831 fetched, 1,833 failed on DNS) and its upload failed; the 831 files reached B2 later. How the plists were removed is not known (T-4356).

**55. The first holdings fix would have counted every sale out of holdings twice.** (2026-11-01, T-4364, caught before merge) `KiteBroker.positions` was changed to add Kite's `holdings` (`quantity + t1_quantity`) to `positions.net`, on the assumption (A-091 as first written) that `quantity` does not fall on the day of a sale. Kite's forum says it does: 100 held and 40 sold shows `quantity` 60, `used_quantity` 40 and a net CNC row of -40 (thread 16259; a 2017 staff reply in thread 2053 agrees). The sum would have read 20 and the reconciler would have reported a break on every sale. Now a holding counts as its `opening_quantity` plus the net book, which gives 60 whichever way Kite shows the sale, and a holding whose fields do not add up raises instead of being guessed. No number was affected: live trading is refused in code (S-015) and the change was never merged.

**56. The workbench showed pairs of numbers that did not agree.** (2026-11-01, every screen checked against the files on the operator's Mac, T-4345) (a) A report's net profit read Rs 5,87,725 beside 58.87%: the rupees were from the starting cash, the percentage from the first day's close, which is already net of that day's costs. A report's total return and CAGR are now measured from the starting cash; stored reports keep the old figure until rerun, and the tile divides its own rupees. (b) The Strategies list worked out annual return over calendar years (+12.8%) and the report over trading days / 252 (13.14%); the list now shows the report's CAGR. (c) Live & Risk printed rupees made (money in) beside a time-weighted percentage, so after a Rs 50,000 deposit +Rs 686 read +0.02% instead of +0.20%; the percentage beside rupees is now rupees over money in. Deployments were named by their first capital ("Rs 10,000" holding Rs 30,000); now by the money in them. (d) The option chain priced with a parity-fitted discount factor above 1, a negative rupee rate, so a deep call showed delta 1.001; such a fit is now replaced by parity with the discount fixed at 1 (the median of C - P + K). (e) A calendar release the source moved (BOJ, 08:00 to 08:32) showed twice; the latest schedule now wins on screen and in the brief, landed files unchanged. (f) A day missing F&O lowered the cash bhavcopy's grade too; a segment gap now names the missing segment. (g) Forex opened on USD/INR, which no source lands; the list is now the ten landed pairs. (h) The macro numbers were labelled "live" while showing a Friday mid-session sweep; they now show the sweep's time.

**57. Crypto days were counted twice, and the newest days were never asked for.** (2026-11-01, measured on the operator's Mac, T-4369) (a) The daily filler lands a month's days while the month is open; Binance's month file for the same days lands later and the day files stay. Every reader read both. For BTCUSDT, 1 Aug to 28 Aug and 1 Sep to 29 Sep 2026 had both; on 15 Sep the panel said volume 43,365.43, the day file alone 21,682.72: exactly doubled, prices right. The minute reader returned two candles a minute for those days. Invalid: crypto daily volume and turnover for those days, so any liquidity filter, volume feature or Amihud figure over them, and every intraday crypto paper or scan that read those days. Fixed: a day file whose month file is landed is not read (`crypto.without_superseded`); the landed files are unchanged. (b) The filler started at the first of the current month, so on 1 Nov it asked for 1 Nov to 31 Oct, no days at all, and 30 and 31 Oct stayed missing until October's month file appears; the newest bar was 29 Oct. It now starts at the first of the previous month and skips days already landed in B2 (before, it downloaded the month's days again every run, because `prune-local` empties the disk). (c) `/api/history` for BTCUSDT downloaded 99 files from B2 per load: 51 to 74 s with an empty local tree, 8.8 s only when an earlier read had refilled the disk. Each file's daily bars are now saved in `data/cache/crypto_daily.json` and missing files are fetched eight at a time without being kept. (d) The Data quality screen graded every source on each visit (2.2 to 3.7 s); one grading now serves it for two minutes.

**58. The live preflight asked for a Kite token where none is ever kept.** (2026-11-02) `_credentials_present` required `ZERODHA_ACCESS_TOKEN` in the environment, but Kite's token expires at 6 AM and `broker/kite_session.py` deliberately keeps it in `.kite_session.json`, never `.env`. So "Broker credentials configured" could not pass however the operator logged in. Now it asks for the API key and secret in `.env` and a fresh session from `make kite-login`. No order was affected: live is still refused.

**59. The (i) popups were drawn inside their cards.** (2026-11-02, operator report, T-4390) ADR-082 put every explanation behind an info button, and the popup was positioned inside the card it belonged to, on the 52%-opaque glass surface. So it was cut off by any card with `overflow: hidden` (the Strategies table's header popups among them), painted under the next card (each glass card is its own stacking layer), ran off the right edge near the window side, and let the card text show through. Now it is drawn above every card in a window-level layer on a solid background and kept inside the screen (ADR-119). No number was affected.

**60. A ₹50,000 Clenow paper book became one BOSCHLTD share.** (2026-11-02, T-4385, ADR-120) The operator asked why "Clenow's Stocks on the Move, top 25" traded so little. The rule was fine: its 2016-2026 backtest made 14,382 fills, and in 523 of 535 weekly decisions 25 or more names passed its filters. The paper deployment was not. `fit_to_capital` ranked names by weight and kept the largest top-ranked set in which every name could buy one share. Clenow weights by inverse volatility, so its largest weight is its calmest stock, not its best trend: BOSCHLTD, 22nd of 25 by momentum, ranked first. At ₹47,589 a share it fitted only in a one-name book, so on 29 Oct the book sold its six names and put 89% of its money into one share; the other 24 were "cut". Now a name its capped weight cannot buy is skipped instead of cutting the list below it, a strategy whose weights are sizes is ranked by its own order (`ranked_by_order`), and no name may exceed the operator's caps (35% of 5 names, 25% of 10, 15% of 20). Replayed on the 29 Oct targets the same ₹53,300 holds 19 names, none above 8%. Every earlier paper deployment that held fewer names than its strategy asked for was sized by the old rule; its fills stand, but its concentration was the fitting's, not the strategy's.

**61. ADR-118 said the last npm advisories needed Next 16 and ESLint 9. Neither was true.** (2026-11-02, T-4379, ADR-121) The high PostCSS advisory is in the copy Next 15.5.28 pins exactly; an npm `overrides` entry pinning PostCSS 8.5.32 under Next clears it, and the moderate it put on Next, with no Next upgrade. The 18 minimatch moderates are not cleared by ESLint 9 either: ESLint 9 and the Next lint plugins still require minimatch ^3, and no fixed release exists below 11.0.1. `npm audit` now reports 18 moderate, 0 high. No number was affected.

**62. Two cloud reads disagreed with the uploads.** (2026-11-02, audit on the operator's Mac, T-4391, T-4392) (a) `crypto.land_month` checked only the disk, and `prune-local` empties it, so every daily run downloaded each of the last twelve crypto months again and uploaded it with a new `receipt_time`: B2 held 15 versions of BTCUSDT's August 2026 month, 1,260,624 to 1,260,709 bytes. Landing is meant to be immutable; the minutes were Binance's same file each time, but the current object kept changing. It now skips a month the bucket holds. (b) NSE files are uploaded to `{prefix}cm/...`, without the tree name, as `prune_local` documents, but `landing_reader.remote_key` asked for `{prefix}nse/cm/...`, so a read of any pruned NSE file failed as if it had never been uploaded. `market_history` reads bhavcopies this way; which of its outputs missed days is not checked. The reader now makes the same special case.

**63. The version lock fingerprinted memory addresses.** (2026-11-02, T-4396) ADR-087's lock hashes a strategy's source and `repr(vars(strategy))`. For 40 of the 68 deployable strategies that repr held a function, printed as `<function momentum_12_1 at 0x7f60ae7c0900>`, and the address changes every time Python starts. So the fingerprint changed on every run: each of those paper books carried a "code changed" warning every day whether or not its code had changed, and a live book on one would never have passed the lock. Found while checking whether PR #69 would trip the lock. Now addresses are removed before hashing (`version_lock._stable`), and a test compares fingerprints from two separate Python processes. A lock written before the fix still differs once: relock it (`make relock`). No trade was affected: on paper the lock only warns.

**64. The doctor's two hand-offs did not reach the right agent.** (2026-11-03, ADR-124) ADR-113's doctor said a refused run "for data" was handed "to the data agent as a data request". It only wrote a line in `data/agents/doctor/log.jsonl`, and nothing read that log: the data agent reads requests from the research and skeptic agents' outputs, never the doctor's. The live log held no such line, so no request was lost. Separately, a run that failed because the model refused or ran out of quota ("ModelUnavailable: The free quota is used up", seen live on Groq while testing ADR-124) has a traceback inside `src/eulerlab`, so the doctor queued it as a code error for the engineering agent, which runs on paid Claude Opus, to "fix" a rate limit. Now a refused-data line becomes a `check_dataset` task for the data agent (`agents/work.py`), and a run whose summary starts `ModelUnavailable`, `Refused` or `BudgetSpent` is `model_down` (`doctor.MODEL_ERRORS`). No numbers are invalidated. Not checked: whether earlier engineering runs spent requests on such a false code error (search `data/agents/doctor/code_queue.jsonl` history in the engineering runs' outputs).

**65. "The last round has no tools, so it must answer" was not true for gpt-oss-120b.** (2026-11-03, ADR-125) The assistant's tool loop (ADR-064) assumed a model offered no tools would answer. On Groq, gpt-oss-120b wrote a tool call anyway (twice, in two live knowledge questions), and Groq refused the reply with HTTP 400 `tool_use_failed`; T-4402 and research 142 had read the first such failure as a one-off parse error. The same loop also sent rounds back to back with all 17 tool descriptions each time, about 18,000 tokens a minute against Groq's 8,000, which was the 429. Now requests are paced to the limit, the knowledge agent is offered 10 tools and 4 rounds, and the last round gets the results as plain text. Any answer the AI tab or Telegram got from Groq after a long tool loop could have failed the same way; no numbers are invalidated, since a failure gave no answer at all. The first pacing code stamped Groq's remaining count with the real clock while its test paced on a fake one; it passed on this Mac and failed on CI, whose fresh machine's clock read lower. Caught before merge; `settle` now takes the same clock.

**66. "0 drafted" read as "no papers", but the agent was dropping and forgetting them.** (2026-11-03, ADR-126) The research agent's runs on 11-01, 11-02 and 11-03 said "0 drafted" and nothing else. Re-run with every paper's outcome printed (research 144): the most on-topic momentum paper was dropped because gpt-oss-120b wrote one section as an object and the reply check was strict; one was lost to a single Groq timeout; three had no abstract; off-topic hits used read slots. And a run with no draft wrote no `run.json`, so its "not relevant" papers were read again next time. Now replies are parsed tolerantly, a failed request is retried once, reading follows topic overlap, Crossref fills missing abstracts, every judged paper is kept in the library, and the summary counts each outcome. The same topic then drafted 2. No numbers are invalidated: drafts spend no trial.

**67. The lab's hand-off to engineering could never fire.** (2026-11-03, ADR-128) ADR-127 recorded a research card the lab could not build at the step where the lab prices a card (`agent_trials.cost_of`). Since 2026-11-01 the lab drops such cards one step earlier, when it fills its queue, so they never reached the recording step and `data.unbuildable` was always empty: no signal would have been handed to engineering. The tests built that list by hand, so they passed. Found the same day, before any lab run used it. Now the card is recorded where it is skipped, and a test runs the real lab on such a card and checks the engineering task appears. No numbers are invalidated.

**68. The nightly upload never finished because the US step re-fetched ten years every night.** (2026-11-02, operator report: "the automatic data upload stalls") `make daily` fetched S&P 500 daily bars and corporate actions from 2016-01-01 on every run. `prune-local` empties the US tree after each upload, so every night `land_bars` rewrote about 37,500 month files, each with every row restamped with that night's `knowledge_time`. The gzip size moved by a few bytes, so the mirror saw tens of thousands of "changed" files: 26,131 uploads on one night, 30,402 on another, 18,219 plus 8,551 connection failures on 1 Nov. The feed ran 25,101 s and 26,362 s on two nights, and the 1 Nov run never got past the final `upload-tree us DELETE=1`. Two data faults came with it. (a) Each larger re-landed file replaced its B2 object, so B2's current copies of US bars carry the night they were last re-fetched as `knowledge_time`, not the night we first held the bar; the original stamps survive only in B2's older versions. Any as-of read of US bars before 2 Nov sees later knowledge times than the truth, so it is too strict (bars look unknown when they were known), never leaky. (b) A re-landed file a few bytes smaller was refused by the #52 guard and logged as a failure each night, so `daily` exited non-zero for a reason that was not a fault. Fixed: the nightly window starts at the first of last month; a pruned month is restored from B2 before it is merged, and not written if B2 cannot be reached; an unchanged bar keeps its first `knowledge_time`. The Kite login that expired on 29 Oct only made the Kite steps fail fast; it did not slow the run.

**69. The OpenAlex key in `.env` was never used.** (2026-11-03, ADR-131) The operator added the key as `OPEN_ALEX_API_KEY`; `paper_search` read only `OPENALEX_API_KEY`, so every search still ran on the keyless allowance ($0.10 a day, about 100 searches) instead of the key's $1. Nothing failed, so nothing said so. Found by listing `.env` names against the code's. Now each key is looked up under the standard name and the operator's spelling (`OPEN_ALEX_API_KEY`, `CORE_API`, `Semantic_API`), and `.env` is loaded before the lookup. No numbers are invalidated: the key only changes how many searches a day are allowed.

**70. The nightly upload refused 12,107 files every night and said so to nobody.** (2026-11-03, operator: "why data agent didn't work?", ADR-132) `sync_directory` never replaces a bucket object with a smaller local file, and `prune_tree` deletes a local file only when the bucket holds it at the same size, so a file that differed from B2 was kept and refused forever: 12,009 US actions and bars re-fetched with new knowledge times (HISTORY #68), 90 crypto months, and two news months that held only part of October while B2 held the rest. `make daily` ignores upload errors, so it exited 0, `daily_guard.sh` sent nothing, and the data agent, which only graded, never looked. A dry run on 2026-11-04 found the crypto and US files were the same rows as B2's, and the two news files held **1,552 rows B2 did not have**: those headlines, fetched since the month was first uploaded, existed only on this Mac. The data agent also called today's not-yet-published data "missing" at 16:15 and counted it as 18 datasets behind schedule. Now differing files are merged into B2 and deleted, in `make daily` (a failure fails the run) and every two hours by the data agent. No backtest numbers are invalidated: the news rows were never used by a strategy.

**71. A research card marked "valid" asked for a formula the language refuses.** (2026-11-03, found 2026-11-04 by tracing the lab's skipped cards) The card for "Geopolitical shock-driven mean reversion" ranked by `formula:neg(ret(0))`; `ret` windows start at 1, so the lab could not build it and skipped it as "unknown feature". The research agent checked the card's fields, not whether its formula parsed, so it was staged as complete. Now a formula that does not parse, or a ranked configuration with no feature, makes the card incomplete at drafting. No numbers invalidated: nothing was tested.

**72. A head passed up a research task that delivered nothing.** (2026-11-03) The Head of Research's checklist asked only that the run finished ok, wrote a summary and was not flagged by the doctor. The CEO's task "intraday stock trading strategies" came back "0 drafted" and was passed up as done. Now a research task that drafts nothing, or a lab task that tests nothing, is sent back once, then blocked for AI help.

**73. The lab queued cards research had marked incomplete, and retried unbuildable ones every day.** (2026-11-04, the live daily-flow test) Research drafted 3 cards on "liquidity premium Indian stocks"; one was complete. The lab queued all research drafts regardless of `draft.json`, failed to build the incomplete ones, and listed the same three "unbuildable" cards on every run, two of which no code could fix (a formula that does not parse, no signal named). Research's summary said "3 drafted" with no hint that only one could be tested. Now the lab queues only cards research staged as valid, drops a card an earlier run could not build for a reason no code fixes, and keeps one waiting for engineering to code a named signal; research says "3 drafted (1 complete)", and a head sends back a research task with none complete. No numbers invalidated: nothing unbuildable was tested.

**74. The brief showed an expired option chain's levels as today's.** (2026-11-04) The pre-open brief for 4 November gave "Range to expiry 2026-11-03 from the ATM straddle: 23,179 to 23,484", "Max pain 23,250" and "Nifty options expiry (in -1 days)" when Nifty had closed at 23,811 and that expiry had settled. The age check looked at when the chain was captured (two days, within the limit), not whether its expiry had passed. Now a chain whose expiry is on or before the last close is left out of the levels, the put-call item and the calendar, with a line saying why. No numbers invalidated: the brief feeds no strategy.

**75. `make install` would have removed the news tone model it had just been asked to run.** (2026-11-04) ADR-134 put the model in an optional `news` extra and told the operator to install it with `uv sync --extra news`, but left `make install` as `uv sync --extra dev --extra web`. `uv sync` removes what it is not asked for, so the next `make install` would have uninstalled the model and the brief would have gone back to unscored headlines with only a note. Now `make install` includes it, `make install-lite` leaves it out, and `install-news` and `remove-news` change only it. No numbers invalidated.

**76. A stablecoin entered the crypto universe.** (2026-11-04) The nightly rebuild of `config/universe_crypto.txt` (the top 20 Binance USDT pairs by volume) listed BFUSDUSDT, Binance's BFUSD dollar token, because `ingest/crypto.STABLECOINS` did not name it. A stablecoin's USDT pair is an exchange rate between two claims on the dollar, not a coin, so any crypto backtest or screen run on that day's list held a near-constant price. BFUSD and Ethena's USDe were added and the list rebuilt. That night's backfill had already landed BFUSDUSDT's minute history under `data/landing/crypto/BFUSDUSDT`; it stays (landing is immutable) and no derived file or stored result refers to it.

**77. Three agent faults behind "4 datasets not updating" and a failed engineering run.** (2026-11-04) (a) NSE published the 4 November F&O bhavcopy after the 19:30 nightly run and after the data agent's last check (20:00), so F&O bhavcopy, participant OI, Nifty futures and Nifty options all stopped on 3 November. When the data agent was run at 22:59 it re-ran the downloads and the file landed, but (b) it then described the problems it had found *before* the re-run to Groq, which answered that NSE had not published, after the file was on disk; and (c) Nifty options still did not pick it up, because `options.nifty_history` listed the bucket's `fo/` and a local `fo/` that holds only cached reads, not `data/landing/nse/fo/` where the ingest lands new files, so a file not yet uploaded was invisible. Separately, (d) the engineering agent's daily quality check ran the whole test suite under a 900 s limit; the suite takes 10-11 minutes and more on a busy machine, and the `TimeoutExpired` ended the run as failed. Fixed: the data agent re-reads freshness after a re-run and sends only what is still behind; `nifty_history.archives` also lists local `nse/fo/`; `fixer._run` returns code 124 on a timeout instead of raising, and the full suite gets 2,400 s. No stored numbers invalidated; the four datasets were brought to 4 November by hand the same night.

**78. The engineering agent could not use the free model it was given.** (2026-11-05) ADR-127 let the engineering agent try Groq first, but a bug-fix request carried the whole CLAUDE.md, the module's architecture sections, the whole file and its whole test file and asked for the whole file back: 8,600 to 12,600 tokens for the modules measured, past Groq's free 8,000 a minute (6,400 after the margin). Every fix skipped Groq and went to a paid model, or to nothing. Now, for a model with a per-minute limit, `fixer.small_context` sends the hard rules only, the module header and the function the error names, the tests that use it and the error (1,800 to 4,200 tokens for the same modules), and the model answers with find-and-replace edits that must each match the file exactly once. A first live request (1,559 tokens) was accepted by Groq; its edit misquoted the code and was refused, as designed. The checks a fix must pass are unchanged. No numbers invalidated.

**79. The agents page showed the engineering agent "Working… Starting…" when nothing ran.** (2026-11-05) `runtime.latest_run_dir` took an agent's newest folder by name as its latest run. The engineering agent keeps its fix worktrees in `data/agents/engineering/worktrees`, and "worktrees" sorts after every run id, so the page read that folder as a run with no output and no steps, called it running, and showed "Starting…" forever. The operator asked to stop a "stuck" agent that was not running. Now only folders named like a run id (`YYYYMMDDTHHMMSSZ-xxxxxx`) count. No numbers invalidated.

**80. A test said H-0001's holdout was unread after the operator had read it.** (2026-11-07) `tests/test_validation_holdout.py` asserted that `hypotheses/H-0001.yaml` declares an unread holdout. The operator read it on 2026-11-06 (ADR-143) and the file was changed to `status: read`, but the test was not, so `make verify` and CI on main went red from commit 6bd2119. Nobody saw it because the later commits were pushed straight to main. Now the test checks that the file records the read, and a new test checks that a read holdout is still cut off by `truncate`. No numbers invalidated.

**81. A test still expected H-0001's gate verdict to be KILL.** (2026-11-07) `tests/test_research_orchestrator.py` asserted that the real ledger's latest verdict for H-0001 is KILL; H-0001 was re-gated PROMOTE under the simple gate on 2026-11-06 (ADR-140, ledger #68-#95), so the pre-commit suite failed on this machine (the test is skipped in CI, where the ledger is absent). Now it expects PROMOTE. Also found in research 166: research 153's Nifty expiry list (from `nifty_options.jsonl`) lacks four expiries (2019-08-29, 2019-09-05, 2019-09-12, 2021-05-20); H-0041's numbers move from 299 trades and +6.96 bps net to 303 and +7.12. Why the file lacks them was not checked. No conclusion changes.

**82. The intraday stock screens choose from today's F&O list.** (2026-11-07) `cross_section.universe()` lists stocks with Kite minute files, which are today's F&O stocks, and every stock screen from research 112 to 172 draws from it. Stocks that joined F&O later (often after a large rise) are in the 2021-2024 tests; stocks that left are not. Checked on the two research-172 PROMOTEs by keeping only stocks in F&O on the trade date (`stock_fo_daily.jsonl`): H-0160's net edge falls from +44.1 to +8.6 bps a trade (183 of 416 trades) and H-0153's from +331 to +153 bps a position (90 of 181). Measured the same day on all eight research 168-172 stock survivors (research 173): on stocks in F&O at the time, H-0132 falls from +8.9 to +0.6 bps net, H-0146 from +15.3 to +3.2, the four PAPER scalps to -3.2 to +6.0, and none survives 2x costs. On every liquid NSE stock, daily bars, H-0160's and H-0153's rules hold (H-0161, H-0162: PROMOTE): the effect is in small stocks, not only hindsight. Results invalidated: the minute-bar PROMOTEs H-0132 and H-0146 and the four PAPER scalps are unproven until tested on a survivorship-free universe.

**83. A gated strategy had no report to open.** (2026-11-07) The operator could not see H-0161's and H-0162's results in the library: `make validate` and `make gate` write an evidence pack and ledger entries but no stored result, and only `make full-history` (ADR-143) stored reports, for fifteen named cards. Every research 166-173 PROMOTE and PAPER showed a verdict with nothing behind it. `make library-reports` now stores each one's research-window run and report. No numbers invalidated.

**84. H-0168 was gated on a rule that skipped most results.** (2026-11-07) `daily_more_screen._results_mornings` was meant to find results disclosed after the previous 15:30 and before 09:15. It skipped any disclosure on a session day at or after 09:15, which threw away every evening disclosure, the common case, and kept only pre-open and holiday ones. H-0168 was screened and gated PROMOTE on that (176 trades, +90.21 bps net; ledger #122, #123). Found while writing its test. Fixed and re-run: 1,077 trades, +48.09 bps net, Sharpe 1.91, PROMOTE again (ledger #124, #125). Numbers invalidated: H-0168's first screen and gate; H-0172's "no events" was re-checked and holds.

**85. The autopilot's first three passes were one bet, already held.** (2026-11-08) The first nightly batch (research 177) gated H-0174, H-0175 and H-0178 PROMOTE (ledger entries for each: validate, then gate). Each shorts a stock that rose on thin delivery, as H-0161 does. Their daily returns correlate 0.63 (H-0174) and 0.73 (H-0178) with H-0161's, and 0.47-0.73 with each other. The engine's bias checks looked at each rule alone, and the repeat check matched only identical specs. So "three new strategies" was one strategy counted four times. Fixed: a "new bet" check (`research/autopilot.same_bet`, A-122) now flags a clean rule whose daily returns correlate 0.5 or more with any pass, or with a better rule from the same night, and it is not gated. Under it, H-0174 and H-0178 would not have been gated; H-0175 (correlation 0.39 with H-0161) would. The verdicts stand in the ledger. The two duplicate paper books were stopped, and the cards say why.

---

**86. The paper books ignored a surveillance list landed before the open.** (2026-11-08) Every stock paper book (H-0161, H-0168, H-0187, the engine books) took the ASM/GSM snapshot on or before the *previous session*, so the list NSE published on Saturday 7 Nov (265 symbols) did not count for Monday 9 Nov, and a book with no earlier snapshot would not trade at all; the live-price plan did the same. The list was knowable before the open. Now each book takes the latest snapshot dated before the trade day (`day - 1 calendar day`), and the evening plan the latest on or before tonight. No trade was affected: no paper book had traded yet. Found by the research 178 work; fixed in `deploy/delivery_fade_book.py`, `deploy/daily_books.py`, `deploy/engine_book.py`, `deploy/live_shadow.py`.

**87. ETFs were in the stock rules' universe, priced at a stale open.** (2026-11-08) The engine's universe (the 500 most traded NSE symbols) included ETFs and fund units such as NIFTYBEES and GOLDBEES, whose official opening print often lags the market. H-0194's edge came mostly from them (research 180), and Monday's live-price plan listed LIQUIDIETF and SILVERBEES as H-0175 candidates. Measured from 09:20 instead of the official open, H-0168 keeps 1.2 of its 45.9 bps gross, so it is labelled unproven; H-0161 (29.0 vs 28.8 bps), H-0187 (34.9) and H-0175 (43.2) keep an edge. Fixed for money: paper books and the live-price plan drop INF ISINs (`rule_engine.LiveData`, `live_shadow.fund_symbols`). The research window still includes them, so research 176's reproduction holds; whether past screens should be re-run without them is open (T-4535).

## What the project has actually concluded

**Nothing has beaten the strict bar.** Under it (deflated Sharpe against the
idea families, Romano-Wolf over Nifty, stress retention, HISTORY #45) the best
result ever produced here was **1.27** and the gate killed everything.

**The operator then chose a simpler bar (ADR-140, 2026-11-06).** Under it seven
hypotheses PROMOTE and eight get PAPER (research 165), and the holdout was
read once for all fifteen (ADR-143). So there is no unseen data left: forward
paper trading is the only out-of-sample test these strategies will get. A
PROMOTE under the simple bar is not evidence that the strict bar was wrong.

Research 166-167 (2026-11-07) added one: H-0103, the BankNifty expiry-day
straddle, PROMOTE under the simple bar (it would fail the strict bar's
Romano-Wolf). Seventeen other intraday rules died at the screen.

**No capital has ever been traded.**

---

## Where the durable detail now lives

| You want | Read |
|---|---|
| How the system works, with the mathematics | `docs/ARCHITECTURE.md` |
| Where the project is right now | `STATE.md` |
| What is open | `TASKS.md` |
| What is fake or unbuilt | `docs/STUBS.md` |
| What is unverified, and when to recheck | `docs/ASSUMPTIONS.md` |
| Why a choice was made | `docs/DECISIONS/ADR-*.md` |
| What a source actually said | `docs/RESEARCH/` |
| What to do when something breaks | `docs/RUNBOOKS/` |

## 2026-11-08 — workbench pages were slow for reasons other than data size (perf, branch perf-workbench-load)

Believed: pages were slow because the data is big. True, measured with headless Chrome against a production build:
- Most API time was pure-Python YAML parsing of unchanged cards: `rule_engine.card_spec` parsed 388 times per `/api/fleet`. Now `filecache.read_yaml` (libyaml loader, memoised by file stamp; every repo YAML parses identically under both) plus memoised `card_spec` and agent specs.
- Every page first rendered the dashboard (the URL hash was read after the first render), so every page also fetched the snapshot and market context. The page now waits for the hash.
- The shell and the page sent identical GETs at once (activity, inbox, snapshot twice on Charts). `lib/api.get` now shares an in-flight request; each caller parses its own copy.
- All tabs were in one 242 KB page bundle; each is now loaded on first open (`next/dynamic`), 123 KB first load.
- `/api/history` scanned millions of panel rows for one symbol; it now bisects the per-symbol list (`PANEL.symbol_window`, equal output checked on real data).
- Market context and cloud status are warmed at server start.

Warm page load, median of 13 pages: 1.12 s → 0.36 s; API calls per full page tour 150 → 82. No research numbers invalidated. Still slow: the first page opened in the ~60 s after an API restart waits for the panel preload (about 18 s), unchanged.

## 2026-11-08 — the org chart listed engineering's "reads mode" twice

Believed: the capability audit makes one check per thing an agent needs. True: it made one "reads <arg>" check per skill, so an argument two skills share (engineering's `mode`, passed by both fix and feature) appeared twice under one name, and the AI tab's org chart raised a React duplicate-key error. Now one check per argument, naming every skill that passes it; a test asserts each (agent, check) pair is unique. No numbers affected.

## 2026-11-08 — NSE stopped filing "Financial Result Updates", so live results feeds saw no results (research 182)

Believed: `nse_earnings_announcements.derive` finds every results disclosure, as it did for 2021-2024. True: every daily answer landed from 2026-08-10 holds no "Financial Result Updates" row; results now arrive only as "Outcome of Board Meeting" rows saying the company "has submitted to the Exchange, the financial results for the period ended ...". `daily_books.results_times` therefore returned nothing for 2026, so the H-0168 and H-0187 paper books (not started) and the brief's movers could not see a single results morning. Fixed: such an outcome row counts as a result for a (symbol, day) that has no results row (594 for 2026-11-03 to 2026-11-07). The 2021-2024 backtests are unaffected: those years have results rows, and those win. Any 2026 paper replay of H-0168 or H-0187 run before this fix had no trades and should be re-run.

## 2026-11-08 — NSE weekend sessions were never collected, and Muhurat counted as a full day (research 183, ADR-157)

Believed: skipping weekends misses no trading session (A-011), and every bhavcopy day is a normal day. True: NSE opened on 12 Saturdays and Sundays from 2015 to 2026-11-08 (Budget days, Muhurat, 2024's special and DR sessions), and none was held. Seven weekday Muhurat sessions and the 2017-07-10 late open were held but traded as full days in every daily backtest, rule screen and paper book. Now the nightly bhavcopy step probes weekends, the other NSE feeds follow it, and the engines hold through a short session (turnover under 50% of the 20-session median). Numbers that move: every India daily backtest and rule screen whose window crosses one of those eight days changes slightly (a decision and a fill move one session later); no gate verdict was re-run. On 2026-11-08 the Muhurat file landed before the engine change, and paper book `nse_github_weinstein_stage2` fc4b65 filled four sells at the Muhurat close.

## 2026-11-09 — the dashboard had no Angel One feed, so a day without a Kite login showed no live prices (ADR-158)

Believed: Angel One was the live-quote fallback when Kite's token had expired (ADR-154). True: only `live_shadow` asked Angel; the dashboard's map and movers asked Kite and then Yahoo (blocked), so with the 2026-11-06 Kite token expired the page showed the settled close. The Angel SDK was also not installed by `make install` or `make api`, so even `live_shadow`'s fallback failed with "SDK not installed" under the Makefile, and `angel_check.tokens_for` searched symbols one by one, which Angel rate-limits after a handful. Fixed: Angel is asked in `quotes`, tokens come from the scrip master, the extra is installed. No research numbers invalidated.

## 2026-11-09 — the watchdog chased its own overdue tasks, so one problem became 13 tasks (ADR-159)

Believed: the watchdog's "open past its due day" check finds work that agents have dropped. True: it also flagged its own watchdog tasks and engineering fixes that wait for the operator to press Run (no agent may start them). Each day it raised a new task about the last one, and the head split each into fresh "optimize slow pytest tests" and "review the branch" steps, so 13 near-duplicate tasks were open on 9 Nov about an engineering run failure that had already stopped (engineering ran ok on 6 and 8 Nov after the pytest timeout fix). Now the check skips watchdog-raised tasks and operator-only tasks, and the watchdog keeps one open task per head and problem. The 13 were cancelled. No research numbers affected.

## 2026-11-09 — H-0202's Sharpe of 7 was the opening auction (research 184)

Believed: the autopilot's H-0202 (fade a 3% gap on a quiet-volume name) passed the gate at a net Sharpe of 7.1, 141 bps a trade. True: on the 1,154 trades in F&O stocks with minute data it makes 85 bps gross from the official open but 19 bps from 09:20, and its long side 8 bps, below the ~12 bps cost. The backtest fills at the auction print, which a 09:20 order cannot get; ETFs added 205 trades of stale prints. It is also the same bet as H-0194. Invalid: H-0202's screen and gate figures as a measure of what money would earn. The ledger entries stand. H-0194 keeps 31 bps (long) and 48 bps (short) from 09:20 and is the card traded (ADR-162).
