# STATE — where this project is right now

**Status:** COMPLETE — every code sprint in the build plan (0–28) plus the workbench. In flight: five microstructure rules (T-4285; strategy 5 waits on a FYERS token) and the UI revamp (T-4283).
**Next:** Sprints 29–31 — compliance, then first capital (operator). For micro-05: log in from Instruments → FYERS (or `make fyers-auth`), then `make microstructure-five-futures`.

*Last updated: 2026-10-31. One page, and it stays one page. If it is not here
or in `TASKS.md`, it did not happen.*

---

## New session? Do these three things.

**1. Prove the repository is healthy before believing anything in it.**

```bash
make verify
```

Expect **8 of 8 green**. The test count changes as the suite grows. The `engine` row is the backtester
self-test gate and the `chaos` row is the order-path gate; if either is red,
stop and fix it before running anything, because every number downstream
depends on them.

**2. Read `docs/ARCHITECTURE.md`.** It is the single explanation of how the
system works, including the mathematics. Do not re-derive any of it from the
code.

**3. Know the two files you may not edit.** `mandate.yaml` and
`src/eulerlab/gates.py` are **operator-owned**. Propose changes in writing;
never edit them without an explicit instruction in that session.

---

## What is true today

- **Market brief as a morning note (2026-10-31, ADR-105):** the brief is saved as data and drawn in the AI tab: headline, the three things
  that matter ranked by how unusual they are (each with what it means), levels and if-then, coming up (expiry, ban list, results due), books
  needing you, then the detail folded. Telegram gets 8 lines. Weekends and NSE holidays get a markets-closed note (week in review, week ahead); the after-close note runs in `make daily`.
- **Metrics library (2026-10-31, ADR-103):** `docs/METRICS/`, 116 pages: every platform metric plus macro, policy, institutions, events and market structure,
  traps and example answers, plus `HOW_TO_ANSWER.md`. Wired into the knowledge agent and the assistant (`explain_metric`); kept current by the knowledge keeper agent (ADR-104), which recomputes normals daily, watches SEBI/RBI/NSE circulars and drafts page updates for approval. Found: Sharpe has no
  risk-free rate (A-083, T-4249) and the gate never checks `min_t_statistic` (HISTORY #42, T-4250).
- **Market brief answers first (2026-10-31, ADR-100):** the brief opens with the Trader's read: bottom line, a seven-row
  scorecard with what is normal for each signal, Nifty's levels and ranges, what would change the read, the books.
  Thresholds in `config/trader_read.yaml` (proposals, A-082). Telegram gets the read only; the assistant has `market_read`.
- **Formula language (2026-10-31, ADR-097, research 131):** a card can name `feature: "formula:<text>"`, e.g. `neg(ts_mad(ret(1), 62))`;
  parsed and interpreted, never executed. The 10 library features rewritten as formulas match exactly. Phase 1 of the
  self-improving agent plan; whether discovery-window searches count as trials is your call (T-4230).
- **FII/DII cash flows (2026-10-29/30, ADR-098, ADR-099):** `make fii-dii` captures NSE's evening figure in `make daily` and
  `make india-live`; first live run 2026-10-30. `make fii-dii-history` backfilled 265 days (2025-10-01 to 2026-10-29) from Trendlyne
  against its terms, by operator decision; agrees with NSE, Groww and stockezee within 0.05 crore. Shown on Dashboard → Big money.
- **Market microdata (2026-10-30, ADR-095, research 130):** `make nse-reports` lands bulk/block deals, short selling, F&O ban,
  SLBM, MTF, insider and SAST filings, and pledge/IPO/Nifty 50 list snapshots; a year back (insider from May 2026). `make
  index-minute`: 5 years of NIFTY 50, BANK and VIX minutes. `make depth-day` records Kite five-level depth (snapshots, not every
  order; S-052), launchd job `depth` not loaded. All in B2, SHA-256 checked, local deleted. Past order books are paid only (T-4223).
  Dashboard → India → **Deals & filings** shows them (ADR-096, `make market-reports`, run inside `make nse-reports`).
- **Loss limits that act (2026-10-29, ADR-092):** a paper book goes reduce-only (sells only) at a 10% drawdown and halts at 20%
  (`config/loss_limits.yaml`, defaults not yet chosen by you); Reduce only / Resume buying on each card.
- **Workbench redesign (2026-10-29, ADR-090, 091):** four colours (blue, green, red, amber), rounded corners, one look file
  (`web/app/terminal/theme.css`). AI tab opens on Live: what each agent is doing now, step by step. `make agent` works again (HISTORY #34).
- **AI agent network (2026-10-29, ADR-085 to 087):** eight agents on one runtime with budgets, briefs, an inbox
  and a hash-chained log; none can import the order path, gate, ledger writer, env or a shell. Workbench **AI** tab and
  Telegram `instruct`/`outlook`/`inbox`. One data quality contract grades 18 datasets (`make data-quality`); backtests refuse a
  low-grade panel. Trade desk tickets and a version lock on every deployment. Quantpedia sync needs a key (T-4182).
  No agent has run live with a model yet; launchd jobs not loaded (T-4179).
  Code checks every figure in a knowledge answer or brief commentary against what the model was given; `make agent-eval`
  switches off an agent that shows a made-up figure (ADR-088). The idea lab may spend up to **5 trials a week** testing
  the research agent's drafts (IC screen, then backtest, before the holdout), each logged and raising the bar (ADR-089).
- **Paper agent (2026-10-29, ADR-084):** `make paper-agent TOPIC=...` searches arXiv and OpenAlex, drafts a
  library entry and an H-card per new paper with Groq `openai/gpt-oss-120b`, and stages them in
  `research/agent_drafts/`. `make paper-agent-approve DRAFT=...` moves one into `hypotheses/` as a draft. It never
  backtests or logs a trial. Not yet run live (T-4171). Dead and weak models removed from `config/llm.yaml` (HISTORY #33).
- **Quality and speed pass (2026-10-27):** all uncommitted work committed; `make verify` 8 of 8.
  Engines agree again (Tier A got Tier B's cash and delisting rules, HISTORY #28). FX now pays its
  recorded spread (it paid nothing, HISTORY #30). Panel: 2.6 → 1.85 GB, read about 8 s from a
  columnar copy in `data/cache/` (was 37 s). After a restart: `/api/data` 37 s → under 1 s,
  instruments 12 s → 0.15 s. Warm: dashboard 0.68 → 0.18 s, strategy table 0.22 → 0.07 s,
  company page 2 ms for tickers no rename touched. T-4139 measured (HISTORY #28); T-4155 closed. Open: T-4156.
  Second pass: first snapshot 3.9 → 2.0 s (the rest is live quotes), `/api/data` 0.3 s → 0.02 s, test suite 153 → 119 s.
- **Dashboard market context (2026-10-27, research 120, ADR-080):** breadth (% above 20/50/200-day, new highs and lows), index trend and
  valuation, sector strength against Nifty, FII/DII/Pro/Client index-futures long share, Nifty PCR/IV/max pain, delivery spikes.
  Context only; none has passed the gate. Expiry-day option chains read a settled contract (HISTORY #31, fixed).
  Then split into four India tabs with a Market pulse (ADR-081). No generated text: gauges and charts, every explanation behind an (i) button (ADR-082). Trend and Participation now use published rules (Faber 10-month; 200-day share, ADR-083).
- **Indian data from the close (2026-10-26, ADR-079):** `make india-live` retries the Indian steps from 15:31
  until the bhavcopy and minute bars are in. Coverage reads **missing** from 15:31. Minute-built bars stand in until the
  bhavcopy lands. They are not used by the panel or the paper books. F&O stocks' minute bars end at 15:14 since the
  closing auction began on 3 Aug (HISTORY #29, T-4137). Neither launchd job (15:31, 19:30) is loaded on this Mac yet (T-4138).
- **Quality and speed (2026-10-16, ADR-077):** all work committed. Intraday screens share
  `screen_common` (−356 lines, same numbers). `/api/window` <1 ms (was 1.1 s), options history
  5 ms warm (was 3.2 s), Research Library 43 ms (was 0.33 s), B2 status 3 ms, dashboard reopened 0.35 s.
  Fixed: a test that wrote into `.git/config` (HISTORY #22); snapshot deadlines that did not bound (#23).
  Angel env keys are now `ANGEL_*`; the superseded cash-flow branch is deleted.

- **Paper deployment cash flows (ADR-076):** complete (T-4124). Flows are dated
  against the last decided close; replay applies them on the next decision.
  State and Telegram use contributed capital and time-weighted return; Paper
  trading shows pending and completed flows. Focused tests and all 8 `make
  verify` checks passed.

- **Data:** 23,230 objects / 4.45 GB mirrored to Backblaze B2. Local landing is
  pruned to ~6.6 MB after every ingest — B2 is the storage of record. Panel
  covers 2,869 trading days. Last ingest 2026-08-20, CLEAN.
- **Market history (2026-10-07):** the price panel now has open, high and low
  for every day from 2015. Every NSE index (177, incl. India VIX and the
  sectorals) with P/E, P/B and yield, delivery % per stock, the trading
  calendar, 144 real Nifty expiries and daily Nifty futures are in
  `data/derived/` (research 065). Nothing reads delivery yet (T-3997).
- **ETFs now pay their own STT** (0.001% on the sale) in both engines; until
  2026-10-07 they paid a share's 0.1% each side (HISTORY #18).
- **The engine agrees with itself** to 1.4 × 10⁻¹⁶ between Tier A and Tier B,
  and a frictionless paper run reproduces the backtest exactly (gap 0.00).
- **The gate has killed everything it has seen** — H-0001 plus three
  deliberately overfit acceptance strategies. It has never promoted anything.
- **19 trials are logged.** The noise bar is **Sharpe 1.88**. The best result
  this project has produced is **1.27**.
- **No capital has ever been traded.** Paper deployments trade forward with an
  operator-set capital (`make paper-daily`, Live & Risk → Paper trading, ADR-060);
  live is refused in code until the Kite adapter is proven (S-015, T-4022).
  Both books are traded through 2026-10-08. `make daily` now updates them
  right after the bhavcopy, so a failed sync or a slow step cannot hold them back (T-4030).
- **Data:** Tools → Instruments → **Update all data** brings every dataset up to
  date and its Data coverage table (`make coverage`) shows what is missing (ADR-061).
  The price panel and paper books update by themselves when new NSE data lands (ADR-062).
- **MCX iCOMDEX (2026-10-15, research 082):** 1.81M one-minute candles landed for seven
  indices and were mirrored with SHA-256 checks to `nse/mcx_indices/` in B2. Kite has no
  minute history for five of the 12 indices in the supplied list; the Instruments
  update reports the available series and records those gaps instead of filling them.
- **Intraday (2026-10-11):** two papers run on NIFTYBEES minute bars (research 071).
  Both lose after NSE intraday charges of 4 bps a round trip. The noise-area rule has
  a stable gross edge of 3 bps a trade; nothing on the cash ETF can carry it.
  The Nifty gap paper is coded as written (research 072): best case Sharpe 0.64 on the future.
- **Five Indian intraday rules (2026-10-13, research 076):** 26 settings on NIFTYBEES and the
  100 largest stocks; 25 lose after costs. All ten recent strategies were re-run; no verdict moved.
  Their papers are in the Research Library (58 papers), each linked to its stored result.
- **Two US stock rules (2026-10-13, research 078):** end-of-day reversal and the opening half-hour
  repeating, on the 100 largest stocks. Neither exists here before costs; both rejected.
- **Nightly job (ADR-070):** `make daily` takes one dataset at a time: download, upload to B2, delete locally.
  Fundamentals is weekly (Sunday 10:00) and on demand: `make fundamentals-update`. No full run yet.
- **Risk on the deployed book (ADR-071):** Live & Risk has Risk overview, Performance and Stress & exposure:
  VaR from today's holdings over 250 days, where the risk sits, limits with headroom. It warns; it does not act.
  The overnight future's gap risk is included (ADR-072); the Deploy dialog shows the book's VaR before and after.
- **Archive (ADR-069):** a strategy can be put away from the Strategies page and restored; it hides only.
- **Telegram (ADR-063, ADR-068):** deployments report their orders; the bot answers 22 words
  (money, market, one stock, results, the machine) and plain questions. It cannot trade or stop anything.
- **Gap strategy (2026-10-12):** paper-deployable through its own overnight book (ADR-066); the
  pre-close signal is scheduled for 15:20 on weekdays.
- **Kite login on Instruments (2026-10-12):** link to Zerodha, paste the address back; minute bars
  then update from their own button. Not yet tried with a real login.
- **Speed (2026-10-12):** dashboard first paint 0.45 s (was 6-9 s), on the newest prices seen, not the last close (ADR-067); panel read 19 s (was 51 s),
  preloaded at startup. Use `make ui-fast` for the built UI. Table in ARCHITECTURE.
- **Company pages (ADR-065):** `/terminal/company/<SYMBOL>` for 2,361 companies, from the
  screener.in files, the price panel and tagged news. No analyst data, estimates or DCF: not held.
- **Assistant (ADR-064):** floating button on every screen; OpenRouter free model with zero
  retention forced on every request; eleven read-only tools. Working: answered real questions
  correctly on 2026-10-12. Free limit is 50 requests a day.
- **MCX instruments (ADR-075):** `make mcx-instruments` fetches Kite's daily MCX instrument CSV,
  lands it immutably under `data/landing/mcx/`, and mirrors the separate `nse/mcx/` B2 prefix.
  First live snapshot on 2026-10-15: 15,946 rows; raw CSV and manifest confirmed in B2.
- **Research Library AI (ADR-073, ADR-074):** model picker loads current free OpenRouter ZDR choices; pasted source drafts paper fields and paper pages generate sandboxed code for Tier B. Code/results are shown but not saved. Provider locks remain; not yet checked in the UI.

---

## The commands that matter

```bash
make verify        # is the repo sound?      8 checks
make acceptance    # does each capability still work on real data?  11 checks
make workbench     # the UI on :3000, API on :8000
make montecarlo    # drawdown path risk and the Sharpe confidence interval
make daily         # refresh data, mirror to B2, prune local
```

**Two commands cost something permanent.** `make gate` and `make validate` each
append a trial to the ledger and raise the bar for every future candidate.
Neither is in `verify` or `acceptance`, deliberately. Do not run them to check
that they work — that has already happened once by accident (T-2609).

---

## What to do first, if you are picking this up

Three things are cheap, unblock other work, and are all currently waiting:

1. **T-1317** — recompute Sprint 8's IC on corrected prices. Its published
   figures came from raw prices over a 3-year panel and are known wrong. This
   also settles whether H-0002 is worth registering.
2. **T-906** — reconcile the cost model against 20 real contract notes. Needs
   the operator: copy `config/contract_notes.example.json` to
   `contract_notes.json`. Still the cheapest verification in the project.
3. **T-1407** — exercise the gate's PROMOTE path with a known-good synthetic
   candidate. The gate has never promoted anything, so that path has never run.

---

## Known to be wrong, right now

- **Sprint 8's IC figures** — raw prices, 3-year panel (T-1317).
- **Every cost rate** — sourced secondarily, never checked against a contract
  note (T-906, A-016). Market impact is not modelled at all (T-907).
- **The options chain recorder was never built.** Every day it does not run is
  history that cannot be purchased later.
- **Excess kurtosis ≈ 155** on one configuration, unexplained (T-1310).

`docs/STUBS.md` lists everything currently fake. `docs/ASSUMPTIONS.md` lists
everything unverified with a recheck date. `docs/HISTORY.md` lists the eleven
times this project has been wrong so far.
