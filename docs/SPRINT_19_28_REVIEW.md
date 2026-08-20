# Sprints 19–28 — the order path: OMS, EMS, reconciler, kill switches, paper trading
**Status:** COMPLETE
**Branch:** sprint-19-28-oms-paper   **Commits:** see below

Built as one block, at the operator's instruction ("build everything left and
then we test end to end everything"), because 19–24 and 25–28 are one system:
paper trading is not a separate thing you can build without an OMS, and an OMS
with nothing driving it cannot be tested end to end.

---

## What now works (plain English, no jargon)

**Orders survive the process being killed.** The system writes down what it
intends to do, forces it to disk, and only then talks to the broker. If it dies
at any point after that, the next start-up finds the order, asks the broker what
became of it, and picks up correctly — whether the order landed or not. Two of
the eleven chaos scenarios genuinely `kill -9` a real subprocess mid-order to
prove this, rather than simulating a crash.

**"We don't know" is a state the system can be in.** A timeout is not treated as
a failure or as a success. The order goes to `UNKNOWN` and stays there until the
broker answers. There is no timeout after which it gives up and guesses, because
guessing wrong in either direction costs money — retry and you double-send,
assume success and you are short a position you think you own.

**Sending the same order twice sends it once.** The order id is derived from what
the order *means*, so a retry produces the same id and is recognised. Two
defences: the system checks its own records first, and the broker rejects a
duplicate id if it somehow gets through.

**Nothing exceeds five orders a second, ever.** Not on average — in any
one-second window. The limit is read from `config/execution.yaml`, not written
into the code.

**There is a stop button that the trading system cannot un-press.** Anything can
trip it. Clearing it needs a credential the trading process never loads and a
command run by hand. It also trips itself on a daily loss limit, too many orders,
a run of rejections, an oversized position, or too many unresolved orders.

**The broker is believed, not us.** A reconciler compares our position book
against the broker's and reports every disagreement. It corrects our record and
**never places an order** to make the broker agree with us.

**Paper trading is the backtest with a broker in the middle.** Not a second
system — literally the same loop, with one component swapped. With a frictionless
broker it reproduces the backtest **to the paisa**, which is the check that stops
the two drifting apart.

**The reality gap is broken down into causes.** Slippage, cost, trades not made,
trades only paper made, and positions that ended up different. The split closes
to the paisa.

---

## How to check it yourself (2 minutes)

```bash
make verify          # expect: 7 of 7 green, ~922 tests
```

```bash
make chaos
```
Expected: eleven scenarios, all PASS, including `killed before the send` and
`killed after the send` — those two really do `SIGKILL` a subprocess.

```bash
make attribution FRICTIONLESS=1 DAYS=800
```
Expected: `gap  0.00`. Exactly zero, not "small". Paper and backtest share one
loop, so any difference at all would be a defect.

```bash
make reconcile-book
```
Expected: `no breaks`, `0 orders still UNKNOWN`.

---

## What is fake right now

| Thing | Why | Removed in sprint |
|---|---|---|
| The only broker is a simulator (S-015) | No live adapter exists. Nothing here says anything about real fills, latency or rejection reasons | 29 |
| Paper fills are instant and complete (S-016) | Real orders rest and fill in pieces. `ACKNOWLEDGED` and `PARTIALLY_FILLED` are modelled but the paper broker never produces them | 29 |
| Costs in paper are our own model (S-017) | A simulator issues no contract note, so "cost model error" in the reality gap is zero **by construction** | 29, blocked on T-906 |
| The reality-gap residual is an identity (S-018) | Both books are ours, so the split closes by arithmetic. The build plan's "residual under 10%" is about a *live* shortfall and cannot exist yet | 25–28 live |
| Kill-switch separation is by code, not by OS (S-019) | One machine, one user: a process can delete the trip file. Real separation is a different host and a second broker key | 29 |
| Kill-switch limits are chosen, not measured (S-020, A-018) | Round numbers, conservative against 1–2% of capital. None derived from an observed distribution | after ~4 weeks of paper history |

---

## What I could not verify

- **Anything about real execution.** Every number in the paper run comes from a
  broker I wrote. The slippage is the slippage I chose. This sprint verifies the
  order path and the accounting, not the market.
- **The `ACKNOWLEDGED` and `PARTIALLY_FILLED` transitions against a real broker.**
  They are in the state machine and unit-tested; no real venue has exercised them.
- **That five orders per second is the right SEBI threshold** (A-001, T-014).
  Still unverified against the primary circular. The governor enforces whatever
  the config says, so this is a config question, not a code one.
- **Whether the automatic limits fire at sensible levels** (A-018). They fire
  correctly at the levels configured; whether those levels are right is unknown
  until there is a distribution to look at.

---

## Two things worth knowing about how this was built

**A test found a real gap and it was fixed rather than accommodated.** The paper
runner originally recovered unresolved orders only at start-up, so an order that
timed out *during* a run stayed `UNKNOWN` to the end and was silently treated as
a rejection. `test_a_paper_run_recovers_before_it_trades` caught it. The fix is
to query immediately on an ambiguous send — which is what the rule said all
along. There is now a test asserting that a timed-out send which *did* land
still reproduces the backtest exactly, so a timeout costs nothing.

**The state machine was missing a legal transition.** A broker can reject an
order synchronously, inside the send call, before it is ever "sent". The table
had no row for it and the first rejection test crashed. Added as
`INTENT → REJECTED`, kept distinct from `INTENT → UNSENT`: one means the broker
saw it and said no, the other means it never got there.

**Two refactors of already-tested code.** `plan_orders` was extracted from the
Tier B engine so backtest and paper build orders with one implementation, and
the fill step became a pluggable `Executor` for the same reason. Both were
verified by the golden file still matching byte for byte — the refactors changed
no behaviour.

---

## Decisions I need from you

1. **Should `config/killswitch.yaml` become operator-owned, like `mandate.yaml`
   and `gates.py`?** — Option A: yes, add it to the operator-owned list in
   `CLAUDE.md` now. Option B: leave it editable until the limits have been set
   from real paper data, then freeze it. **My recommendation: A.** The argument
   for `mandate.yaml` being yours applies here word for word — these are the
   numbers with the strongest incentive to be quietly loosened on a bad day, and
   "we promised not to touch it" is not a control. The cost of A is that I cannot
   tune them in a later sprint without asking, which is the point.

2. **Do you want a live Kite order adapter written now, or at Sprint 29?** —
   Option A: write it now against the documented API, unused and untested against
   a real account. Option B: wait for Sprint 29, when the compliance items
   (static IP, broker confirmation) make it usable. **My recommendation: B.**
   An adapter that has never met a real broker is a stub with a confident name,
   and `CLAUDE.md` forbids inventing API details. The `BrokerAdapter` protocol is
   five methods, so writing it later costs nothing extra.

3. **T-906 is now blocking more than the cost model.** Twenty real contract notes
   would turn "cost model error" in the reality gap from a structural zero into a
   real number. It remains the cheapest verification in the project and it needs
   you: copy `config/contract_notes.example.json` to `config/contract_notes.json`
   and fill in twenty rows.

---

## Reading added for you

- **Idempotency and deterministic identifiers** (MUST, 20 min) — needed to check
  that a retry cannot double-send. If you can explain why the id is derived from
  the order's *meaning* rather than from a counter, you can audit this sprint.
- **Order state machines and the ambiguity of a timeout** (MUST, 25 min) — the
  three-outcome model is the single most important idea in these sprints.
- **Implementation shortfall** (SHOULD, 30 min) — the framework the attribution
  report is a simplified form of. Needed before the numbers from a live paper run
  mean anything.

---

## Next sprint

Sprints 29–30, the compliance sprint, which is **yours, not mine**: static IP,
broker algo framework confirmation, `algo_id` wired end to end, and a CA review
of F&O business income and STCG/LTCG treatment. Then Sprint 31, first micro-live
capital at 1–2%.

Before any of that, two things I can do on your word: T-1317 (re-run Sprint 8's
IC sweep on corrected prices) and T-1407 (exercise the gate's PROMOTE path,
which has still never been taken).
