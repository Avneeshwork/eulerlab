# Sprint 05 — corporate actions and adjustment engine
**Status:** COMPLETE, with one build to re-run (S-012)
**Branch:** sprint-05-corporate-actions   **Commits:** 2

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

- **Rights issues are handled properly, not approximated.** A rights issue
  isn't free like a bonus — you *pay* for the new shares — so how much it
  dilutes depends on how far below market the offer price is. Using the
  bonus formula would have been badly wrong. I used NSE's own methodology,
  checked it algebraically against the standard textbook formula (they turn
  out to be the same equation written two ways), and validated the inputs
  against Reliance's 2020 rights issue, which was publicly reported at ₹1,257
  a share — the feed's face value plus premium gives exactly that.

- **The whole thing runs as one command and pays for itself once.** `make
  build-factors` completed a full run in 3½ minutes. It caches every price it
  fetches, so re-running is free.

### Two problems this sprint found and fixed

**1. The instrument join was wrong, and it lied quietly.** NSE's corporate-
actions feed and its price files disagree about the same company's ISIN on
the same day — the feed called Aurobindo Pharma `INE406A01029` on 2017-11-21
while the price file called it `INE406A01037`. Both are correct; the last few
digits get reissued when a company changes its face value. Matching on the
full code silently dropped **21.9% of all price lookups**. It didn't error —
it reported "78% coverage", which reads like sparse data rather than a broken
join. Fixed to join on the internal instrument ID that Sprint 3 built for
exactly this, and locked in with a regression test.

**2. One full build eats 85% of a day's cloud storage allowance.** The free
Backblaze tier permits 2,500 downloads a day; a full build is 2,121 of them.
Running it twice in one session — once to build, once after fixing the join —
exhausted the cap outright. The fix is a cache: every price fetched is written
to disk, an interrupted run resumes where it stopped, and later rebuilds cost
nothing. Written up in `docs/RUNBOOKS/b2-transaction-cap.md`.

**The consequence, stated plainly:** the only completed full run used the
broken join. I deleted its output rather than leave a plausible-looking but
incomplete file on disk, and the corrected re-run is blocked until the daily
cap resets. That is S-012 and it is one command.

## How to check it yourself (2 minutes)

```bash
make verify          # expect: all green, 397 tests
```

```bash
make ingest-corp-actions
```

Expected output: `skipped: 12` (already landed this session, idempotent).

**The one thing to run once the B2 cap resets (tomorrow):**

```bash
make build-factors
```

Expected output: a line reading `0 already cached, 2,121 to download`, about
3½ minutes of progress, then a summary. **The coverage figure is the number
to look at** — it should now be well above the 78.1% the broken join produced.
If it is still near 78%, the fix did not take and I want to know.

## What is fake right now

| Thing | Why | Removed in sprint |
|---|---|---|
| The persisted factor files — S-012 | The only completed full run used the broken ISIN join. Its output was **deleted**, not left on disk, so nothing can read an incomplete factor set. The re-run is blocked by the B2 daily cap | next session, one command |
| Knowledge_time = ex-date, not a real announcement date — ADR-016 | The feed's `caBroadcastDate` field was null on every one of 25,644 rows checked. Conservative by design: understates how early a real trader knew, never overstates it | when a real announcement-date source is found |
| The rights formula's provenance — A-015 | The formula itself is cross-checked and validated, but it came from a broker's summary of NSE's methodology. Both NSE pages timed out and the circular PDF would not decode | T-511 |

## What I could not verify

- **The NSE circular for the rights formula.** Both official pages timed out
  and circular FAOP56050 came back as undecodable PDF. Mitigated by checking
  the broker's version algebraically against the standard TERP identity — they
  are the same equation — and by validating the issue-price rule against
  Reliance's real 2020 numbers. Recorded as A-015, not treated as settled.
- **The corrected build's actual coverage number.** Blocked by the cap. I know
  the join is fixed because the regression test proves the specific real case
  that was failing, but I have not seen the aggregate figure.
- Whether NSE's feed is ever revised after publication (a corrected ratio,
  say). Not answerable from inside this data.
- Partly-paid rights. One observed subject describes fully-paid and
  partly-paid shares in one line; it does not parse and is counted as
  unparsed rather than half-applied.

## Decisions I need from you

1. **Should I spend a session reading the NSE circular itself for the rights
   formula (T-511)?** Option A: no — the formula is already cross-checked two
   ways and validated on a real event, and it affects 1.1% of actions. Option
   B: yes, get the primary source so A-015 can be closed.
   **My recommendation: A.** The algebraic cross-check is stronger evidence
   than a single source would be, and the remaining risk is confined to a
   small fraction of events. Worth revisiting before Sprint 9's cost model.

2. **Is the ex-date-as-knowledge-time assumption (ADR-016) acceptable long
   term?** Option A: leave it — it's conservative, so it under-reacts rather
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
