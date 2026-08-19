# Sprint 04 — bitemporal read API and lookahead firewall
**Status:** COMPLETE
**Branch:** sprint-04-lookahead-firewall   **Commits:** 3

## What now works (plain English, no jargon)

- **The research API cannot return data from the future.** Every read takes an
  `as_of` date. It is required, and it must be named — you cannot forget it and
  you cannot put it in the wrong slot. The filtering happens inside the store,
  so there is no unfiltered method to reach past. This is the "brake before the
  accelerator" from the build plan.

- **A 2024 stock list can no longer be used on a 2015 backtest.** That is the
  survivorship error you were asked to be able to explain: a list of today's
  liquid companies contains only the ones that survived, so a backtest using it
  reports the return of holding winners you could not have picked. The universe
  files already recorded the date they were built for; nothing enforced it.
  Now loading one for an earlier date raises instead of quietly succeeding.

- **I found a serious problem with our own data and fixed it.** Every landed
  file records a field called `knowledge_time`. I had assumed it meant "when
  this became knowable". It does not — it means "when I downloaded it". The
  median gap is **1,820 days**. The earliest download timestamp across all
  7,378 NSE files is 2026-08-18, i.e. yesterday. Any backtest filtering on that
  field would have returned **nothing at all**, for all eleven years.

  Worse than the empty result is the obvious fix: someone hits an empty frame,
  loosens the filter, and now the backtest sees everything instantly. The
  failure mode of this bug is a leak.

  It is now three separate times — when it happened, when anyone could have
  known it, when we fetched it — and a backtest reads the middle one.

- **Data is labelled by whether it is genuinely point-in-time.** Only **4 of
  7,378** NSE files were captured on the day they were published. For the other
  7,374 we hold whatever the archive serves today. The timing is honest; the
  content might silently be a later correction. That is unrecoverable from the
  data, so it is carried in the type as `Vintage.FINAL` rather than assumed
  away.

## How to check it yourself (2 minutes)

```bash
make verify          # expect: all green
```

```bash
make provenance
```

Expected output: a table showing `live 4` and `final 7374`, a median backfill
lag around 1,819 days, and a line stating that filtering on the download
timestamp would make every date before 2026-08-18 return nothing.

```bash
make test-lookahead
```

Expected output: `36 passed`. Each test is one attack on the firewall — reading
a future record, a revision reaching backwards, walking forward past a
revision, passing `as_of` in the wrong position, assembling a result set by
hand outside the store, and the symbol-rename leak this project actually hit in
Sprint 1.

## What is fake right now

| Thing | Why | Removed in sprint |
|---|---|---|
| The 20:00 IST publication hour (A-014) | No NSE circular has been read for it. Chosen deliberately late so the error withholds data rather than leaking it | Before any intraday strategy |
| `Vintage.FINAL` content for 7,374 files | Unrecoverable, not a stub. We hold today's version of old files and cannot know if it was corrected | Never — only future live capture fixes this |
| The store holds records in memory | Correct and fast enough for the current volume; it is the interface that matters, not the backing | When a dataset exceeds memory |

## What I could not verify

- **The exact publication hour for `cm` and `fo`.** There is no same-day
  capture for either segment, so there is no evidence at all — only the
  deliberately-late assumption. Participant OI is different: one same-day
  capture at 19:09 IST bounds it, and that measurement is what corrected my
  first wrong guess.
- **Whether NSE ever silently corrected a historical bhavcopy.** Not knowable
  from data we hold. It is why `Vintage` exists.

## Decisions I need from you

1. **Should the publication hour be researched properly, or left as a
   conservative assumption?** Option A: leave it. A daily strategy is
   unaffected — the data is knowable the same evening either way, and the
   assumption is late enough to be safe. Option B: I read NSE circulars and pin
   the real hour per segment. **My recommendation: A for now, B before Sprint 9
   (the cost model) or before any intraday strategy.** The cost of being wrong
   today is zero for daily work, and B spends a session on something that only
   matters once we trade intraday.

2. **Do you want the four `live` captures treated differently from the 7,374
   backfilled ones in research?** Option A: no — use everything, the timing is
   honest. Option B: allow a strategy to require `Vintage.LIVE`, which today
   means it can only run on the last two days. **My recommendation: A**, with
   the flag kept so that in a year's time — when live captures outnumber
   backfilled ones for recent periods — the option already exists.

## Reading added for you

- **Survivorship & lookahead bias** (MUST, 20 min) — already on your list for
  this sprint. The universe guard is the concrete version of it: read
  `src/eulerlab/bitemporal/universe.py`, the module docstring is the whole
  argument in one paragraph.
- **Bitemporal data modelling** (SHOULD, 30 min) — now upgraded from "explains
  why every table has two dates" to "explains why our two dates were the wrong
  two". `docs/DECISIONS/ADR-015` is the short version.

## Next sprint

Sprint 5 — corporate actions and the adjustment engine. The NSE corporate
actions feed found in research note 008 is the source for dividends, splits,
bonuses and rights, keyed by ISIN. It is silent on mergers that delist the
target, which is why Sprint 3's succession model exists and has to be joined to
it rather than replaced by it.
