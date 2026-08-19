# Sprint 05 — corporate actions and adjustment engine
**Status:** COMPLETE
**Branch:** sprint-05-corporate-actions   **Commits:** 1

## What now works (plain English, no jargon)

- **A raw price history has fake crashes in it, and now there's a fix.** If a
  stock does a 1:1 bonus (shareholders get a free extra share for every one
  they hold), the price halves overnight — not because anyone lost money, but
  because there are now twice as many shares. Left alone, that shows up in a
  backtest as a 50% loss that never happened. The same thing happens, smaller,
  every time a stock pays a dividend. This sprint builds the fix: an
  adjustment factor, computed per stock per date, that removes those fake
  jumps so the price series reads as what an investor actually experienced.

- **The data behind it is real, not a placeholder.** I pulled NSE's
  corporate-actions history for 2015 through today — 25,713 individual
  events — parsed the free-text descriptions into structured numbers, and ran
  the adjustment math against real cases. TCS's well-known 2018 bonus shows up
  correctly: a price from before it is adjusted by exactly 2x, a price from
  after it by exactly 1x.

- **The parser doesn't guess.** NSE's own descriptions are messy — "Bonus
  1:1", "Rs- 70/-" (typo), "62..50" (double decimal typo), "Interest Payment"
  (no number at all). 94.3% of the events that plausibly affect price parsed
  cleanly. The rest are flagged as unparsed rather than silently dropped or
  given a made-up value — a wrong number would misprice every position that
  ever held the stock; a missing one just misses a data point, and it's
  visible.

- **It cannot leak the future, because it's built on last sprint's firewall.**
  Every adjustment factor is computed through the `as_of`-required bitemporal
  store from Sprint 4. Querying a price from before an action happened
  correctly shows no effect of that action, even if the store also holds
  data from years later.

## How to check it yourself (2 minutes)

```bash
make verify          # expect: all green, 373 tests
```

```bash
make ingest-corp-actions
```

Expected output: `skipped: 12` (already landed this session, idempotent).

```bash
make test-lookahead
```

Expected output: `36 passed` (unchanged from Sprint 4 — this sprint added its
own separate test files rather than touching that suite).

## What is fake right now

| Thing | Why | Removed in sprint |
|---|---|---|
| Total-return (dividend) factor for the full 2015-2026 history — S-010 | Built and unit-tested (16 tests with injected close prices), but the real run needs a ~2.2 GB close-price index streamed from B2, which this session did not execute — a time/cost tradeoff, not a correctness gap | when the operator runs `build_close_index` |
| Rights-issue price adjustment — S-011 | Parsed (ratio + premium) but not folded into either factor. The correct formula needs the issue price and market price at ex-date, not just the ratio — a bonus-style formula would be wrong. 276 of 25,713 actions (1.1%) | not scheduled |
| Knowledge_time = ex-date, not a real announcement date — ADR-016 | The feed's `caBroadcastDate` field was null on every one of 25,644 rows checked. Conservative by design: understates how early a real trader knew, never overstates it | when a real announcement-date source is found |

## What I could not verify

- Whether any corporate action's `recDate` (record date) predates its own
  `exDate` for a small subset of rows, which would allow a slightly tighter
  knowledge_time. Not checked; ex-date is the safe default regardless.
- Whether NSE's feed itself is ever revised after publication (a corrected
  ratio, say). Not something this data can answer from the inside.

## Decisions I need from you

1. **Run the total-return build now, or leave it for when it's actually
   needed?** Option A: run `make build-close-index` (not yet wired to a make
   target — 2,869 files, several minutes, ~2.2 GB from B2) this week so the
   total-return series is real end-to-end. Option B: leave it as tested-but-
   unrun until a strategy actually needs dividend-adjusted returns.
   **My recommendation: B.** Nothing downstream depends on it yet, and running
   it now would be work done ahead of a measured need, which `CLAUDE.md`'s
   cost discipline says to avoid.

2. **Is the ex-date-as-knowledge-time assumption (ADR-016) acceptable long
   term, or worth a dedicated research pass to find real announcement
   dates?** Option A: leave it — it's conservative, so it under-reacts rather
   than leaks. Option B: spend a session searching for exchange filing
   timestamps that would give a real, earlier knowledge_time.
   **My recommendation: A for now**, revisit only if a strategy's backtest
   turns out to be sensitive to exactly when a dividend was knowable.

## Reading added for you

- No new topic. This sprint is the concrete payoff of "Survivorship &
  lookahead bias," already read for Sprint 4 — the same discipline applied to
  a different kind of leak (an action instead of a universe list).

## Next sprint

Not yet planned. Candidates from the open task list: T-506 (rights-issue
pricing), T-508 (run the total-return build), or moving on to the next major
build-plan phase. Bring whichever the operator wants prioritized.
