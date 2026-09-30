# ADR-046 — One reader for eight evidence stores

**Status:** ACCEPTED · 2026-08-26

**Context.** Results and trials accumulated into eight places, each added for a
good reason and none aware of the others:

| file | holds |
|---|---|
| `derived/trial_ledger.jsonl` | validated hypotheses, hash-chained |
| `derived/trials.jsonl` | every configuration evaluated |
| `derived/sweeps.jsonl` | parameter grids and their candidates |
| `derived/strategy_results.jsonl` | each strategy per market (ADR-047 merged two files here) |
| `derived/walk_results.jsonl` | walk-forward and PBO |
| `workspaces/*/results/*.jsonl` | runs executed from the interface |
| `workspaces/*/reports/*/*.json` | the detail behind one run |

The noise bar is computed from "how many configurations have ever been
evaluated". **Two** of those files answer that question — the hash-chained
ledger of 19 validated results and the append-only log of 388 configurations —
and `research/budget.price_search` was reading only the first.

So a 180-trial parameter sweep left the bar at Sharpe 1.88 when the search it
had just performed put it at 2.78. Every result the platform held was being
judged against a bar that had never been charged for the search that found it,
and the understatement was an order of magnitude.

**Nothing was wrong with either file.** Both were correct and both were
maintained. What was missing was anyone whose job it was to know both existed.

**Options.**

1. **Fix `budget` to read both.** Necessary and insufficient: it is the same
   decision made once more, in one more place, by whoever happens to notice.
2. **Consolidate into one store.** The stores hold genuinely different things —
   a hash-chained validated result is not an append-only trial count — and
   merging them would lose the distinctions the gate depends on.
3. **A reader that enumerates every store and says which count.**

**Choice.** Option 3. `evidence.py` writes nothing. It lists every store with
its row count and a `counts_toward_bar` flag, and `make evidence` renders it.

The flag is the load-bearing part. Getting it wrong in either direction is a
defect — too few flatters every result on the platform, too many blocks work
that should pass — so each store states its answer rather than having it
inferred from where it lives.

A test holds `evidence.bar_denominator()` equal to `budget.searches_run()`. A
ninth store that should count and is not wired into `budget` now fails loudly
instead of quietly lowering the bar.

**Consequences.**

The bar moved from 1.88 to 2.78 the moment both files were counted. Nothing sat
between those values, so no result lost its standing — which is luck rather
than vindication, and would not have been true with a different set of results.

**The module then committed the same class of error against itself.** Its census
used `rglob("*.json")`, which does not match `.jsonl`, so thirty-nine workspace
runs reported as zero — a census missing a store, inside the module written to
stop exactly that. Caught by reading the output rather than trusting it, which
is the only reason it is a line here instead of a fifth bug.
