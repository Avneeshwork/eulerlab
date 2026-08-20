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

## Twelve times this project was wrong

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
