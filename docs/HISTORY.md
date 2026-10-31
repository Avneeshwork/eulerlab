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

## Forty-two times this project was wrong

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

---

## What the project has actually concluded

**Nothing has beaten the bar.** 19 trials are logged. A candidate must clear
**Sharpe 1.88** from noise alone. The best result ever produced here is
**1.27**. The most recent Monte Carlo on `momentum_12_1` puts the bootstrap 5th
percentile at **−0.96** — the data cannot rule out that there is no edge.

**The gate has killed everything it has seen.** H-0001 (momentum), plus three
deliberately overfit strategies fed to it as acceptance. It has never promoted
anything, so the PROMOTE path has never been exercised (T-1407).

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
