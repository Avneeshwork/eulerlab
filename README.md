# EulerLab

A quant research and execution platform for Indian equity markets, built for
one person trading their own capital. It downloads market history, cleans it,
turns it into features, tests strategies against it, subjects the survivors to
statistics designed to catch self-deception, and — if anything survives — places
the orders.

**Most of the code exists to make a good-looking backtest harder to produce,
not easier.** If you try twenty meaningless strategies, the best of them will
still look excellent. That fact shapes nearly every design decision here.

---

## Start here

```bash
make install     # once
make verify      # 7 checks, ~998 tests — expect all green
make workbench   # the UI on :3000
```

---

## The five documents, and what each is for

They do not overlap. If you are looking for something, this table says where it
is.

| Question | Document |
|---|---|
| **How does it work, and what is the maths?** | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) |
| **Where is the project right now?** | [`STATE.md`](STATE.md) — one page |
| **What is still open?** | [`TASKS.md`](TASKS.md) |
| **What was built, and what did it get wrong?** | [`docs/HISTORY.md`](docs/HISTORY.md) |
| **What are the rules for working here?** | [`CLAUDE.md`](CLAUDE.md) |

Supporting records: [`docs/STUBS.md`](docs/STUBS.md) (everything currently
fake), [`docs/ASSUMPTIONS.md`](docs/ASSUMPTIONS.md) (everything unverified, with
recheck dates), [`docs/DECISIONS/`](docs/DECISIONS) (why each choice was made),
[`docs/RESEARCH/`](docs/RESEARCH) (what sources actually said),
[`docs/RUNBOOKS/`](docs/RUNBOOKS) (what to do when something breaks).

---

## The three rules that keep it honest

1. **The repository is the memory.** If it is not in `STATE.md` or `TASKS.md`,
   it did not happen.
2. **The brake is built before the accelerator.** The lookahead firewall and
   the engine self-tests came before any strategy work; the kill switches came
   before any order path.
3. **The gate is operator-owned.** `mandate.yaml` and `src/eulerlab/gates.py`
   hold the promotion criteria. A strategy that fails is dead — it is not tuned
   and resubmitted.

---

## Where it actually stands

A candidate must clear the bar set by the 27 idea families tested so far,
**Sharpe 0.98** (ADR-108; it was 1.88 under the old ledger count), and beat Nifty
under a Romano-Wolf test. The gate has killed
everything it has ever seen. **No capital has been traded.**

That is not a failure state — it is the apparatus working. But nothing here
should be read as evidence that the system has found an edge.
