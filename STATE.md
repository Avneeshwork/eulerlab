# STATE — where this project is right now

**Status:** COMPLETE — every code sprint in the build plan (0–28) plus the workbench. In flight: the move to a server (ADR-164, T-4548 to T-4556), Postgres for shared state (ADR-165 to ADR-167, T-4557 to T-4562, off by default), multi-user (#113: login and per-workspace records done; gate settings wait on a decision), the first step toward a multi-user platform (issues #111-#132); five microstructure rules (T-4285; strategy 5 waits on a FYERS token).
**Next:** build and start the containers (`docker compose up -d`, T-4553), then the regulatory research for a subscription platform (#112) and the multi-user design (#113). Also: live-price paper from the first session after the jobs are loaded (T-4525), then the pilot decision (T-4528).

*Last updated: 2026-11-12 (server infrastructure, trial ledger in Postgres). One page, and it stays one page: a summary, not a
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
  Ledger: 139 entries.
- **Under the simple gate (research 165):** PROMOTE H-0096, H-0098 (F&O
  ban-day short), H-0001, H-0020, H-0021, H-0022, H-0029; PAPER H-0023 to
  H-0028, H-0065, H-0052. All deploy to paper from Live → Deploy (ADR-142).
  Added 2026-11-07: PROMOTE **H-0103**, selling the BankNifty ATM straddle at
  the open on expiry day (net Sharpe 1.79, 6 of 6 years positive, research
  166, ADR-145); no paper book yet, and BankNifty expiries are monthly now
  (T-4486). PAPER **H-0118** (noon trend-day pullback) and **H-0115** (gap
  fade after a 15-minute turn): stock scalps at Zerodha 5x MIS size, ₹5 lakh
  a trade, net Sharpe 0.84 each (research 168, ADR-146); and **H-0121**
  (the pullback at 13:30) and **H-0124** (tight-range break), research 169.
  PROMOTE **H-0132**, the tug of war at MIS size (short the five liquid
  stocks with the highest 20-session overnight return, long the five lowest,
  09:20-15:10): net Sharpe 1.44, but 2024 lost 37% on margin (research 170).
  At 1x, PROMOTE **H-0146** (the tug of war only where today's gap agrees,
  ₹1 lakh a position): net Sharpe 1.57, 2024 -4% (research 171).
  On non-price data (research 172): PROMOTE **H-0160** (short a 3% rally
  made on low delivery, intraday) and **H-0153** (promoter buys held 20
  days); on every liquid NSE stock, daily bars (research 173), their forms
  H-0161 (9,867 trades 2016-2024, Sharpe 2.29, every year positive; strict
  bar passed except Romano-Wolf) and H-0162 PROMOTE, with stored reports
  (`make library-reports`). H-0161 has a paper book that skips the previous
  evening's ASM/GSM/trade-for-trade stocks (ADR-148); ASM history does not
  exist, so the backtest cannot check it (A-120). Also PROMOTE on every
  liquid NSE stock: **H-0168**, fade a 3% results-morning gap open to close
  (+48 bps net, 1,077 trades 2021-2024, Sharpe 1.91; research 176,
  re-gated after a bug fix, HISTORY #84). H-0161, H-0168 and H-0162 have
  paper books (ADR-148, ADR-149); none started. Research 178: PROMOTE
  **H-0187** (follow a 5% results reaction the next day, +67 bps net, Sharpe
  2.58, deflated 0.965; paper book built) and H-0185 (weak).
  The six earlier stock rules have paper books (`deploy/mis_book.py`, ADR-147); none started
  yet (T-4495). Since 2026-11-07 the operator's scope is NSE cash stocks only.
- **Screener and stock ideas (research 182, ADR-156).** Picking the top 5
  sectors first lowered every model's return; the long-term list is now Stocks
  on the Move (21.5% a year 2016-2026, worst fall -29%), swing A unchanged. The
  brief shows top sectors, both lists, results due with typical moves, fresh
  results reactions, earnings-drift picks and breakouts. Screening runs only.
- **Holdout spent (ADR-143, 2026-11-06).** The operator read 2024-12 to
  2026-10 for these fifteen. 2016-2026: H-0001 Sharpe 1.28-1.55 (drawdown
  -44% to -63%), H-0098 1.72 (drawdown -10%), the other momentum cards
  0.57-1.12 with drawdowns of 35-60%. H-0065 and H-0096 skipped. No unseen data is left;
  paper trading is the only out-of-sample test. **No capital traded.**
- **Running on a server (ADR-163, ADR-164, 2026-11-12).** `EULERLAB_DATA_DIR` is
  the one setting for where data lives (unset: `data` under the repo, as before).
  The fourteen launchd jobs are a table in `eulerlab.jobs`; `make scheduler` runs it
  anywhere, catching up data jobs and skipping clock-tied ones it missed.
  `make health` is the one page. The live book's clock leaves a heartbeat and a
  dead-man switch in the kill-switch process trips the switch when it goes quiet
  (it cannot square off, S-060). `docker compose up -d` runs api, scheduler,
  killswitch and web; validated, not yet built or run (T-4553). The platform is
  to become multi-user, open source with a hosted subscription: issues #111-#132,
  storage design in ADR-165. With `EULERLAB_DATABASE_URL` set (after `make
  db-migrate db-import`), the trial ledger, the trials counter, the agent log
  and the order journals live in Postgres, where edits are refused by the table and a paper reset starts a new
  generation (ADR-166); unset, they stay files (T-4557 to T-4561). The nightly backup exports the
  database to B2 (T-4562); the kill-switch log stays a file (ADR-167).
  Login and roles exist (`EULERLAB_AUTH=on`, ADR-168); books, journals, ledger,
  trials, agent log and agent files are kept apart per workspace, and a
  workspace may tighten the gate but not loosen it (ADR-169, T-4563 to T-4568).
  Results, paper runs and model keys are per workspace too (ADR-170). Real
  money is still the default workspace only (T-4571).
- **Real money, armed from the workbench (ADR-162, 2026-11-09).** H-0194 (fade a
  3% no-news gap, 09:20 to 15:10, MIS) on Angel One: Live & Risk → Deployment,
  amount + leverage + loss cap, type DEPLOY, one session per deploy. Operator's
  size: ₹1,000 at 5x, one name, ₹150 loss cap: a plumbing test. H-0202 is not
  traded: its edge is the opening auction (research 184).
- **Strategies.** About 140 registered; 68 India daily strategies have stored
  reports and are about 3 independent bets (`make strategy-map`, HISTORY #44).
  Each declares its sizing: equal by default, its own weights when it says
  so, or a model (inverse-vol, HRP, min-variance); caps always apply (ADR-122).
  Intraday (research 153-169): 124 tests of day-trading and swing rules; H-0096, the
  BankNifty straddle H-0103, the tug of war H-0132 (5x) and H-0146 (1x) PROMOTE; four MIS stock scalps PAPER. Research 166-167 found Nifty
  and BankNifty futures rules make 1-6 bps gross against 4.4 bps cost, and
  stock fades after NSE queries have no edge. Before that, one passed:
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
- **Research autopilot (ADR-150, 2026-11-08).** Each evening in `make agents-ideas`,
  the autopilot writes about ten new NSE stock rules as engine specs, half
  intraday and half swing (Claude Sonnet, up to 5 requests a night, then Groq,
  then fixed rules). It
  commits them before any run and screens them in research 173's frame with
  bias checks. It gates clean survivors within 10 ledger entries a week, and
  stores a report and starts a paper book for each pass. It writes one
  research note. `intraday/rule_engine.py` reproduces research 176 exactly.
  Run it alone: `make agents-autopilot`. First batch (research 177): H-0174,
  H-0175, H-0178 PROMOTE, but H-0174 and H-0178 are H-0161's bet again
  (HISTORY #85; their paper books stopped); H-0175 paper-trades. A "new bet"
  check now keeps such repeats from the gate.
- **Self-running organisation (ADR-152, ADR-153, 2026-11-08).** Agents read
  lessons (HISTORY, findings, your feedback) on every model request; two are
  enforced as code on the autopilot. A guardian after every run halts every
  agent if `mandate.yaml` or `gates.py` changes, suspends one that makes up
  figures, tells you when one fails three times running, and holds results too good to believe (H-0175).
  `make feedback TEXT=...` turns a rule into a lesson and anything else into a
  head's task. Live-price paper prices H-0161 and H-0175 picks on Kite quotes
  (Angel One's when Kite has no token, ADR-154) at 09:16 and 15:10 and measures the slippage the backtest hides;
  `make readiness` lists what each strategy still lacks for real money. Not
  run on real data yet (T-4524, T-4525).
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
`docs/HISTORY.md` the 80 times this project has been wrong.
