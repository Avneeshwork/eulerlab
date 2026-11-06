# STATE — where this project is right now

**Status:** COMPLETE — every code sprint in the build plan (0–28) plus the workbench. In flight: five microstructure rules (T-4285; strategy 5 waits on a FYERS token) and the UI revamp (T-4283).
**Next:** Sprints 29–31 — compliance, then first capital (operator). For micro-05: log in from Instruments → FYERS (or `make fyers-auth`), then `make microstructure-five-futures`.

*Last updated: 2026-11-04. One page, and it stays one page: a summary, not a
log. What was built and when is in `docs/HISTORY.md` and `docs/DECISIONS/`;
what is open is in `TASKS.md`.*

---

## New session? Do these three things.

1. **`make verify`** — expect **8 of 8 green**. If `engine` (backtester
   self-test) or `chaos` (order path) is red, stop and fix it first.
2. **Read `docs/ARCHITECTURE.md`.** It explains the system and the maths.
3. **Do not edit `mandate.yaml` or `src/eulerlab/gates.py`.** They are
   operator-owned. Propose changes in writing.

---

## What is true today

- **The gate (ADR-140, 2026-11-06).** The operator switched it to `simple`:
  net positive overall, in each half and at 2x costs; probabilistic Sharpe
  >= 0.95; positive in >= 60% of years. The strict bar (deflated Sharpe
  against 28 idea families, Romano-Wolf over Nifty, stress retention) is kept
  in `mandate.yaml` as `mode: strict`. A strategy that misses that but is
  profitable (PSR >= 0.80) gets **PAPER**: paper trading only (ADR-141).
  Ledger: 67 entries.
- **One promotion so far:** H-0096 (intraday), under the simple gate. The
  single holdout read is unspent. **No capital has ever been traded.**
- **Strategies.** About 140 registered; 68 India daily strategies have stored
  reports and are about 3 independent bets (`make strategy-map`, HISTORY #44).
  Each declares its sizing: equal by default, its own weights when it says
  so, or a model (inverse-vol, HRP, min-variance); caps always apply (ADR-122).
  Intraday (research 153-164): 57 tests of minute-bar rules; one passed:
  H-0096, short on the first F&O ban day (+33 bps net a trade, 2015-2024 daily
  version positive 8 of 10 years). Killed by the strict gate, PROMOTE under
  the simple gate (ADR-140, 2026-11-06); holdout unread; to paper (T-4478).
  A ₹1 lakh stock round trip costs 12.24 bps; no price-only rule cleared it.
  Also alive as a screen: the expiry-day Nifty straddle (H-0041, options,
  net Sharpe 0.95; T-4459). NSE reports were backfilled to 2021 for this.
- **Screener.** Workbench → Screener lists what six new models (quality,
  value, F-score, a tree ranker monthly; pullback and breakout weekly) and the
  five best stored strategies would hold today, each with its backtest and a
  forward record of past picks; none is gate-promoted (ADR-136). The long-term
  buy list is the stocks 3 of the top 5 long-term models pick (ADR-138); the
  swing list is chosen among three pre-registered blends (ADR-137).
- **Paper trading** runs forward with operator capital (`make paper-daily`),
  with loss limits that act: reduce-only at 10% drawdown, halt at 20%.
  Live is refused in code until the Kite adapter is proven (S-015).
  Six halted or stopped books were deleted on 2026-11-04 (archived to B2);
  Nifty calm-rise overnight has no book until you start one.
  A gate-promoted strategy is forward-testing once you start its paper
  deployment; it can go live only after meeting the mandate rule
  (ADR-117; mandate `forward_test:` 60 days, half the backtest Sharpe, -25%).
  `make kite-readonly` checks Kite without sending.
- **Data.** NSE equities, F&O, indices, delivery, FII/DII, deals and filings,
  Nifty minutes and option chains; about 4.5 GB mirrored to Backblaze B2,
  which is the store of record. `make daily` refreshes, uploads and prunes.
- **AI agents.** Eight agents on one runtime with budgets, an inbox and a
  hash-chained log; none can reach the order path, gate or ledger. The market
  brief runs before the open, after the close and on closed days; it tells
  the last session, gives reasons for each signal, and forecasts the next
  session's range, close band and odds, scoring each forecast the day after
  (ADR-133). It ends with market and geopolitical news, its tone (a local
  model) and judged impact, and crash odds from history (ADR-134); news rules
  correct the tone and learn from each judgement, and each stock has a news
  tone (ADR-135). The idea lab
  writes and tests about 30 formula cards a day (`make agents-ideas`, ADR-111);
  cards trade only stocks with Rs 1 crore of turnover and a survivor must beat
  Nifty (ADR-112). A doctor checks every agent run and the engineering agent
  proposes fixes on its own branch for you to merge (ADR-113). Approving a lab
  survivor registers, validates and gates it; verdicts show under Gate runs
  (ADR-116). The agents are a company: you are CEO over three
  department heads, who are agents too. You give a head a task on the AI tab's
  Org chart (a family tree); it splits the task with Groq, or fixed rules if
  Groq cannot answer, checks each result, asks Groq to unstick a blocked one, and passes it up for you to close
  (ADR-124, `make agents-work`, `make agents-capabilities`). Goals are still
  proposed (T-4401). Model requests are paced to Groq's free per-minute limit
  (ADR-125); a knowledge question costs about 4 requests and 9,000 tokens.
  The research agent keeps every paper it reads in the library, drafts
  cards from the tradable ones and says why each other was not (ADR-126).
  A card naming a signal the library lacks is coded by engineering (Groq
  first, then Opus) as a pull request for you; once merged the lab tests it (ADR-127).
  Order is research → lab → engineering; the lab tests research's cards and, again
  since 2026-11-04, up to 30 of its own formula ideas a day, and the
  agents' memory goes to B2 every evening (ADR-128, `make agents-restore`).
  Research searches arXiv, OpenAlex, SSRN, NBER, CORE and Semantic Scholar and knows
  a paper under all its links, so none is read or added twice (ADR-129, ADR-131).
  The engineering agent fits Groq's free limit: it sends the failing function, not
  the whole file, and answers with exact edits (HISTORY #78).
  The data agent runs every two hours 06–20 IST and at 22:00: re-runs what is behind, uploads,
  deletes what B2 holds and merges what differs; a watchdog checks every agent's
  runs, tokens and tasks (ADR-132).
  Launchd jobs were not loaded until 2026-11-01 (T-4356); on that
  evening the agents, daily feed, fundamentals and idea lab jobs were loaded.
- **Workbench.** `make workbench` (or `make ui-fast` for the built UI):
  Dashboard, Strategies, Charts, Options, Live & Risk, AI, Tools.

---

## The commands that matter

```bash
make verify        # is the repo sound?      8 checks
make acceptance    # does each capability still work on real data?  11 checks
make workbench     # the UI on :3000, API on :8000
make daily         # refresh data, mirror to B2, prune local
```

**Two commands cost something permanent.** `make gate` and `make validate` each
append a trial to the ledger. Neither is in `verify` or `acceptance`. Do not
run them to check that they work (T-2609).

---

## Waiting on the operator

1. **T-906** — copy `config/contract_notes.example.json` to
   `contract_notes.json` with 20 real contract notes, to check every cost rate.
2. **T-4292** — seven decisions on judging books instead of single rules.
3. **T-4459** — gate H-0041 (expiry-day straddle), check its fills on minute data first, or leave it.
4. **T-4250** — the mandate's `min_t_statistic` is never checked by the gate.

## Known to be wrong, right now

- **Sprint 8's IC figures** come from raw prices (T-1317).
- **Every cost rate** is from secondary sources (T-906). Market impact is not
  modelled (T-907).
- **Optimiser sweeps store no daily returns**, so the family bar and
  Romano-Wolf cannot see them; a tuned strategy can pass too easily (T-4301).
- **Sharpe has no risk-free rate** (A-083, T-4249).

`docs/STUBS.md` lists what is fake; `docs/ASSUMPTIONS.md` what is unverified;
`docs/HISTORY.md` the 67 times this project has been wrong.
