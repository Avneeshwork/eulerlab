# EulerLab

A quant research and execution platform. Single operator, single-person capital,
optimised for correctness and low cost rather than scale.

Markets in rollout order: India equities → India index options → US equities →
US options → crypto → FX.

**Nothing here trades.** See [STATE.md](STATE.md) for what actually works today.

---

## For the operator

```bash
make verify
```

That is the whole job. It prints one table; green means the repo is sound.
Then read the latest `docs/SPRINT_NN_REVIEW.md`, answer any numbered questions,
and say "next sprint".

If anything is red, [docs/RUNBOOKS/verify-is-red.md](docs/RUNBOOKS/verify-is-red.md)
says what to do — mostly: paste the output back and stop.

```bash
make acceptance
```

The other question, when you want it: does each sprint's capability still work
against the real data? `verify` proves the repository is healthy; `acceptance`
proves the system is. Takes a few minutes and spends nothing.

**Two commands cost something and are not run casually.** `make gate` and
`make validate` each write a trial to a permanent, hash-chained ledger, and
every trial raises the statistical bar for every future strategy. Neither is
in `verify` or `acceptance`, deliberately.

## Setup, once

```bash
make install
```

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

## Where things are

| File | What it is |
|---|---|
| [CLAUDE.md](CLAUDE.md) | Operating rules. Read at the start of every session |
| [STATE.md](STATE.md) | One page: where the project is right now |
| [TASKS.md](TASKS.md) | The ledger — every task, its status, the command that proves it |
| [docs/AI_BUILD_PLAN.md](docs/AI_BUILD_PLAN.md) | How this gets built, and how it is verified |
| [docs/quant_platform_playbook.md](docs/quant_platform_playbook.md) | The reference design |
| [docs/GLOSSARY.md](docs/GLOSSARY.md) | Plain English for every term used in a review |
| [docs/STUBS.md](docs/STUBS.md) | Everything currently fake |
| [docs/ASSUMPTIONS.md](docs/ASSUMPTIONS.md) | Everything unverified, with recheck dates |

## The three rules

1. **The repo is the memory.** If it is not in `STATE.md` or `TASKS.md`, it did
   not happen.
2. **The brake is built before the accelerator.** The lookahead firewall and the
   engine self-tests come before any strategy work; the kill switches come
   before the first live order.
3. **The gate is code, and it is the operator's.** `gates.py` and `mandate.yaml`
   are written once, with the operator. After that a strategy that fails the
   gate is dead — no tuning, no resubmission, no arguing with the gate.
