# ADR-042 — The results mirror merges; it never overwrites

**Status:** ACCEPTED · 2026-08-21

**Context.** Results must live in the cloud as well as on disk. The obvious
implementation is to upload `workspace/results/*.jsonl` after each run and
download it on another machine. That is last-writer-wins, and on an append-only
log it silently destroys data: two machines each append a run, each uploads,
and the second upload deletes the first machine's run from the only shared copy.

The loss is not merely of a number. `results.py` reports a best result together
with `runs`, the count of configurations it beat, because max-of-N is a biased
estimator and the denominator is what makes the figure interpretable. A mirror
that drops runs deflates that denominator and makes every result look *better
attested than it is* — the specific failure this project exists to prevent.

**Options.**
1. Last-writer-wins on whole files. One line of code, loses runs.
2. One object per run instead of one per strategy. No merge needed, but turns a
   readable local file into thousands of objects and a LIST-heavy read path.
3. Merge on pull: union the two logs, then push the union.

**Choice.** Option 3. `pull` downloads the bucket's copy, unions it with the
local file, and rewrites local; `push` then uploads the union. `mirror` runs
them in that order, so both copies converge on the union rather than on
whichever machine spoke last.

Runs are identified by `(configuration, at)` — **not** by whole-line equality.
The same run serialised on two machines can differ in a float repr, and
whole-line equality would count it twice, inflating `runs` in the opposite
direction. Torn lines are dropped rather than propagated: a half-written row is
not a result, and copying one would spread the damage to every machine.

**Why local stays the source of truth.** The upload happens after the local
record and never in place of it, so a network outage cannot turn a completed
backtest into a failed one. The outcome travels back in the job result, so it
is not silent either — the interface can say the mirror is behind.

**Cost if wrong.** The union is monotonic: it can only grow, so a bug in the
identity key makes the count too high rather than too low. That is the safe
direction here — an inflated denominator makes results look *worse* attested
than they are, and the honest failure is the one that does not flatter. The real
exposure is clock skew: `at` is the writing machine's wall clock, so two
genuinely different runs of one configuration written in the same second on two
machines would merge into one. Single-operator today; if it matters, the fix is
a per-machine identifier in the key rather than a timestamp.
