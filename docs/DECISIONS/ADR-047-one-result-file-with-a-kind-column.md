# ADR-047 — One result file with a kind column, not two files with one schema

**Status:** ACCEPTED · 2026-08-26

**Context.** Two files held the identical twenty-five-field row, written by the
same dataclass through the same writer:

- `adopted_results.jsonl` — each strategy on its paper's market, with its
  adopted parameters.
- `us_all_results.jsonl` — every strategy on QQQ, including the ten whose papers
  are crypto.

They were separated only by filename. `_best_asset` opened both and took a `max`
across them to decide which market a signal does best on.

That works, and it quietly assumes three things nothing checks: that those two
files are the only ones, that neither is stale relative to the other, and that a
strategy present in one is comparable to itself in the other. There was nothing
to check any of it *in*, because the comparison was encoded as a directory
listing rather than as data.

**Options.**

1. **Leave it.** Two files is not obviously wrong, and the third question —
   the same strategy on a third market — would simply be a third file. That is
   the objection: it is also a third reader, and a three-way `max` written by
   whoever adds it.
2. **One file per strategy.** Turns a readable log into 36 files and makes "every
   result of this kind" a directory walk.
3. **One file, discriminated by a `kind` column.**

**Choice.** Option 3. `strategy_results.jsonl` carries `kind` — `home` or
`us_cross` — so the comparison is a query. `for_strategy()` returns every
measurement of one strategy whatever question it answered, and a third kind
becomes a new value rather than a new file, a new reader and a new `max`.

`merge()` keys on `(kind, strategy_id)`. Re-running the US cross-test must not
disturb a home-market result, and replacing a whole file is precisely how a
subset run wiped twenty strategies — twice, in the same session, once in the
sweep store and once in the results store.

**Consequences.**

`load()` falls back to the two legacy files when the merged one is absent, so
this works before `make migrate-results` has run and keeps working after. The
fallback is deliberately silent: an operator who has not migrated should see
correct data rather than an error about file layout.

The legacy files are left in place. Deleting them is a separate decision from
merging them, and merging is the one that can be verified by reading the output.
