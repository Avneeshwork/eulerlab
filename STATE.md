# STATE — where this project is right now

**Status:** COMPLETE — every code sprint in the build plan (0–28) plus the workbench. Nothing is in flight.
**Next:** Sprints 29–31 — compliance, then first capital. Operator's work, not a coding task.

*Last updated: 2026-08-20. One page, and it stays one page. If it is not here
or in `TASKS.md`, it did not happen.*

---

## New session? Do these three things.

**1. Prove the repository is healthy before believing anything in it.**

```bash
make verify
```

Expect **8 of 8 green, about 1,890 tests**. The `engine` row is the backtester
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

---

## The commands that matter

```bash
make verify        # is the repo sound?      7 checks, ~998 tests
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
