# 192 · The agent fund's new pieces, run on the Mac's real data (2026-11-13)

**Question.** Do the pieces merged in PR #150 (ADR-171 to ADR-183) work on the real
panel, and what numbers do they give? Tasks T-4577, T-4586, T-4589, T-4590, T-4592.

**Sources.** No web search. Only this repository's data on the Mac (research
window 2016-01-01 to 2024-11-30, 2,456 sessions), the 117 stored gate reports under
`data/workspaces/*/reports/`, and the paper books' `state.json`. No gate was run, no
ledger entry was used, the holdout was not read, no paper book was started or stopped.

## Findings

**1. Fast evaluator (T-4586).** The tables build from the real panel (13 fields kept
under `data/derived/feature_store/`). `FastEngine` gives exactly the slow engine's
result on all ten research 176 rules. But **the slow engine no longer reproduces
research 176's stored file** (`data/derived/daily_more.json`, written 2026-11-07).
All ten differ by a few trades:

| Card | trades now / stored | net Sharpe now / stored |
|---|---|---|
| H-0164 | 1,562 / 1,547 | -1.12 / -1.08 |
| H-0165 | 435 / 427 | -1.39 / -1.36 |
| H-0166 | 333 / 337 | -0.97 / -1.04 |
| H-0167 | 703 / 705 | 0.09 / 0.19 |
| H-0168 | 1,061 / 1,077 | 1.92 / 1.91 |
| H-0169 | 287 / 291 | -0.36 / -0.41 |
| H-0170 | 349 / 339 | -0.06 / 0.12 |
| H-0171 | 1,364 / 1,350 | -1.25 / -1.22 |
| H-0172 | 1 / 0 | — |
| H-0173 | 109 / 101 | -0.03 / -0.07 |

Likely cause, not proven: ADR-157 (2026-11-09) added nine weekend sessions to the
panel and stopped entries on short sessions, after the file was stored. So `make
rule-engine-check` fails (1 of 2 tests). It also needs `EULERLAB_NO_CLOUD=0`, because
some 2023 bulk-deal files are pruned locally. No verdict changes: H-0168 is the only
pass, and it still passes.

`make fast-eval-bench`: the fixed-rule grid has only 248 rules, not the 1,000 asked
for. They took 715 s, which is **1,248 an hour (2.9 s each)**. The first rule, with
its tables, took 55 s. A 200-candidate night is about 10 minutes.

**2. Scorecard and firewall (T-4577).** `make scorecard`: AI spend Rs 0 of Rs 1,000;
gate entries this week 10 of 10 (5 PROMOTE); paper books 10 active, 2 stopped, 1
halted. The **experiment store is empty** (0 rules), so the scorecard shows no noise
bar. For the firewall figures I used the 117 stored reports as the search universe,
the same set the gate's family bar uses. That gives 52 families and a noise bar of
**Sharpe 3.05**:

| Card | full Sharpe (stored) | Sharpe to 2023 | deflated Sharpe | holds on 2024 (225 sessions) |
|---|---|---|---|---|
| H-0161 | 2.11 | 2.19 | **0.004** | **no** |
| H-0168 | 1.86 | 1.04 | 0.012 | yes |
| H-0175 | 3.42 | 3.55 | 0.897 | yes |
| H-0187 | 2.60 | 2.66 | 0.164 | yes |

**None of the four reaches deflated Sharpe 0.95.** Only H-0175's raw Sharpe beats
the noise bar. The gate's own figure for H-0187 (0.965) used 28 families; the
universe has since grown to 52 families with a wider spread. H-0161 kept less than
half its Sharpe in 2024 (only the bit is shown, as ADR-172 intends). The selection
period has 225 sessions because the research data ends 2024-11-30 (T-4578).

**3. Evolve (T-4589). Not run.** Every agent has been halted by the guardian since
2026-11-13 04:33 UTC (`data/agents/HALT`): `src/eulerlab/gates.py` changed without the
operator's acknowledgement. The change is commit 09a0024 (ADR-163), a one-line path
refactor by a Claude thread. Only the operator can clear it, with `make agents-resume
REASON=...`. I did not, and did not bypass it. The nightly autopilot is halted too.

**4. Decay monitor (T-4590).** `deploy/ladder.backtest_returns` reads only the
experiment store, which is empty. So the ladder would put every book at "too little
history". I ran `decay.read` with each strategy's stored gate report as the backtest.
I also found that **paper-book returns counted capital moves as returns**:
`forward._returns` read the raw rupee curve. So ₹20,000 moved on 2026-10-16 showed as
+200% in book c9b000 and -20% in 75607e, and ₹50,000 added to illiquid_winners on
2026-10-22 showed as +172%. Fixed on this branch (HISTORY #88). After the fix, all 11
non-stopped books are **healthy**:

| Book | sessions | S / h | live mean / backtest mean (bps a day) | dead edge caught in 250 sessions |
|---|---|---|---|---|
| sharpe_momentum 75607e | 27 | 1.5 / 30.3 | 14.2 / 13.3 | 23% |
| sharpe_momentum c9b000 | 27 | 4.5 / 30.3 | -4.7 / 13.3 | 23% |
| illiquid_winners 093106 | 17 | 2.6 / 37.2 | -19.2 / 8.8 | 11% |
| minervini 65dce0 | 15 | 0.9 / 33.5 | 6.1 / 8.7 | 15% |
| stocks_on_the_move 9fb0f2 | 15 | 0.3 / 33.7 | 50.1 / 8.6 | 15% |
| weinstein fc4b65 | 8 | 0.3 / 33.4 | 16.7 / 12.1 | 18% |
| H-0161 cb097b | 3 | 0.2 / 24.2 | 0 / 6.8 | 50% |
| H-0175 7fd1fc | 3 | 0.3 / 19.4 | 0 / 9.3 | 91% |
| H-0202 5867c3 | 2 | 0.3 / 9.4 | 0 / 11.8 | 100% |
| H-0229 d9f618 | 0 | 0 / 21.8 | — / 5.9 | 67% |
| sharpe_momentum 25375c (halted) | 0 | — | — | — |

"Healthy" here means "not enough evidence yet". On the swing books, a strategy whose
edge had gone completely would be caught within a year only 11-23% of the time.
Before the fix, 75607e read S = 13.5, on its way to "watch" (21.2), from a withdrawal alone.

**5. Knowledge tool (T-4592).** Has short-term reversal after results been tried? Yes,
several times:

- H-0040 (`hypotheses/H-0040.yaml`): fade the gap the morning after results. 1,249
  trades, -5.8 bps net, Sharpe -0.32. Dead (research 153).
- H-0168 (`hypotheses/H-0168.yaml`): fade a 3% results-morning gap open to close.
  +48 bps net, Sharpe 1.91, PROMOTE. Its edge mostly goes when it is measured from
  09:20 (HISTORY #87).
- H-0198 (`hypotheses/H-0198.yaml`): fade a results gap-up after low delivery.
  Sharpe 1.03, not gated (bias check).
- H-0213 (`hypotheses/H-0213.yaml`): long a 3% results gap-down. Sharpe 0.45, failed
  the halves test.
- H-0177 and H-0204 (results gap-down shorts and recoveries): failed.

The opposite direction (follow-through): H-0187 PROMOTE, H-0190 failed. No card is
marked `source.replicates`. **The tool depends on wording.** "short-term reversal
after quarterly results announcement" missed H-0040 and H-0168. "fade results gap
reversal" found them.

**6. Agent evals and ladder.** `make agent-evals`: on_call 100% (15 public, 100%
held out), red_team 100%, generator 80% / 80%. It exits 1. The three generator
failures (02, 09, 13) are intraday price-only rules that the cases expect kept. The
Mac's live lesson store drops them ("124 such tests never cleared the 12.24 bps round
trip"), so the eval reads machine state, not only its cases. Nothing was switched
off. scout and engineer have no baseline. `make ladder SHOW=1`: every rung is empty,
because the ladder has never been stepped.

## Decision

Fix the flow bug (done here). The rest needs the operator: resume the agents, decide
T-4574 with these numbers, and re-store the research 176 reference.

**Confidence.** High for the measured numbers. Medium for the ADR-157 explanation of
the drift.

**Open.** T-4596 to T-4599.
