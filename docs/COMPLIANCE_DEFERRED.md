# COMPLIANCE — deferred, with the trigger that makes each one blocking

Per the build plan (§7), the compliance work moves to Sprints 29–30, immediately
before live capital. This file exists so that "deferred" never quietly becomes
"forgotten".

**Nothing in this project trades today.** Every item below is deferred against
that fact. The moment a real order can be placed, this file becomes the checklist
that gates it.

---

## Kept now, because they are cheap today and expensive to retrofit

| Stub | Where | Cost now | Cost if added later |
|---|---|---|---|
| `algo_id` field, nullable, unused | `src/eulerlab/schemas.py` | 5 minutes | A week of migrations once the OMS, reconciler, event log and attribution all read the order schema |
| `max_orders_per_second: 5` | `config/execution.yaml` | One line of YAML | An EMS redesign — a governor bolted on after the fact is one that can be bypassed |
| `static_ip: null` | `config/deploy.yaml` | Nothing | Nothing structurally, but forgetting it blocks go-live on a broker registration queue |

All three are logged in `docs/STUBS.md` as S-001 to S-003.

---

## Deferred, with triggers

| Deferred item | Becomes blocking at | Why it cannot slip past that point |
|---|---|---|
| Broker framework confirmation + static IP registration | **Sprint 29**, before any live order | Indian brokers whitelist a fixed IP per client; an unregistered IP simply cannot place orders |
| Algo-ID passthrough tested end-to-end | **Sprint 29** | The identifier must be echoed on every placement, modification and cancellation. Untested means unknown |
| CA review: F&O business income, STCG/LTCG, VDA treatment | **Sprint 29** | After-tax Sharpe is the only Sharpe that pays bills. Getting this wrong changes which strategies are worth running, not just the tax return |
| LRS / FEMA position for US trading | Before the US market sprint | Outward remittance is capped per financial year — a hard ceiling on the US book's capacity, so it is a *sizing* input, not paperwork |
| Crypto TDS cost modelling | **Before any crypto strategy is backtested** | 1% TDS per transfer is a per-trade execution cost. A strategy turning over 50× a year pays it 50 times. Backtests that omit it are fiction, so this one is early, not late |
| OPS governor tuned and confirmed per broker | **Sprint 29** | Broker OPS limits differ; the config default of 5 is a guess until confirmed |

---

## The recurring obligation

Once live: re-verify this file against current SEBI/NSE/BSE circulars **quarterly**.
Market-structure and regulatory facts in this project have a short shelf life —
see `docs/ASSUMPTIONS.md` for how little of it is currently verified at all.
