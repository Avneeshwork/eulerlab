# STATE — where this project is right now

**Status:** COMPLETE — every code sprint in the build plan (0–28) plus the workbench. In flight: five microstructure rules (T-4285; strategy 5 waits on a FYERS token) and the UI revamp (T-4283).
**Next:** Sprints 29–31 — compliance, then first capital (operator). For micro-05: log in from Instruments → FYERS (or `make fyers-auth`), then `make microstructure-five-futures`.

*Last updated: 2026-11-01. One page, and it stays one page: a summary, not a
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

- **The bar.** The gate and every screen use the same bar: the best of
  **27 idea families**, measured spread 0.48, **Sharpe 0.98** (ADR-108). A
  candidate must also beat Nifty under Romano-Wolf (critical about 0.95).
  The ledger holds 19 validated trials.
- **The gate has killed everything it has seen.** It has never promoted
  anything. **No capital has ever been traded.**
- **Strategies.** About 140 registered; 68 India daily strategies have stored
  reports and are about 3 independent bets (`make strategy-map`, HISTORY #44).
- **Paper trading** runs forward with operator capital (`make paper-daily`),
  with loss limits that act: reduce-only at 10% drawdown, halt at 20%.
  Live is refused in code until the Kite adapter is proven (S-015).
- **Data.** NSE equities, F&O, indices, delivery, FII/DII, deals and filings,
  Nifty minutes and option chains; about 4.5 GB mirrored to Backblaze B2,
  which is the store of record. `make daily` refreshes, uploads and prunes.
- **AI agents.** Eight agents on one runtime with budgets, an inbox and a
  hash-chained log; none can reach the order path, gate or ledger. The market
  brief runs before the open, after the close and on closed days. The idea lab
  writes and tests about 30 formula cards a day (`make agents-ideas`, ADR-111);
  cards trade only stocks with Rs 1 crore of turnover and a survivor must beat
  Nifty (ADR-112). A doctor checks every agent run and the engineering agent
  proposes fixes on its own branch for you to merge (ADR-113). Launchd jobs are
  not all loaded on the Mac yet (T-4138, T-4179, T-4323).
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
3. **T-4250** — the mandate's `min_t_statistic` is never checked by the gate.

## Known to be wrong, right now

- **Sprint 8's IC figures** come from raw prices (T-1317).
- **Every cost rate** is from secondary sources (T-906). Market impact is not
  modelled (T-907).
- **Optimiser sweeps store no daily returns**, so the family bar and
  Romano-Wolf cannot see them; a tuned strategy can pass too easily (T-4301).
- **Sharpe has no risk-free rate** (A-083, T-4249).

`docs/STUBS.md` lists what is fake; `docs/ASSUMPTIONS.md` what is unverified;
`docs/HISTORY.md` the 52 times this project has been wrong.
