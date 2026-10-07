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

## Nineteen times this project was wrong

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

**19. The test suite wrote into the landing zone and quietly used the
network.** (2026-10-07) `tests/conftest.py` said the suite runs offline, but
it only switched the bucket off. Two `indices.land` tests appended their fake
DOLLAR INDEX reading (98.9) to the real `data/landing/macro/<today>.jsonl` on
every `make verify`, and the unstubbed one also asked TradingView for live
quotes and appended those. That file is raw data, and `sync-cloud` mirrors it
to B2. Nothing reads it yet (`macro.series` has no caller), so no result is
wrong, but every day's macro history on the operator's machine and in B2 may
carry duplicate 98.9 rows stamped at test time. Separately, the news-tagging
tests downloaded NSE's company list when it was absent and the quotes test
fell through to Yahoo, so they passed on the operator's machine and failed
anywhere else. Fixed: those tests are stubbed, the suite now refuses any
connection to another host, and it fails if any file under `data/` changed
during the run. To clean history, drop rows with `"symbol": "TVC:DXY"`,
`"last": 98.9` and `"change_pct": 0.15` from `data/landing/macro/` (T-4030).

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
