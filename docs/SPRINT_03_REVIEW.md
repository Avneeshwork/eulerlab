# Sprint 3 — Security master

**Status:** COMPLETE
**Branch:** sprint-03-security-master   **Commits:** 14

All acceptance criteria pass. `make check-master` is green on six checks, and
every one of them is capable of failing — the tests assert that, because a
check that cannot fail is decoration.

---

## What now works (plain English, no jargon)

- **The system knows ZOMATO and ETERNAL are the same company**, and worked it
  out from the data. It found **580 renames** across eleven years by following
  ISIN continuity, with no alias map written by hand.
- **Ask what was true on a past date, get the past answer.** NIFTY's lot size
  was 50 in March 2024, 25 that November, 75 by March 2025 and 65 by 2026.
  Every one of those is returned correctly for its own date.
- **A delisted company stops claiming its ticker**, so a dead 2015 instrument
  cannot shadow whoever holds that ticker now.
- **Corporate events are five distinct things**, because collapsing them was
  actively dangerous: rename, merger, demerger, cancellation, delisting. Each
  carries a cited source and, where a position must be carried across, a ratio.
- **Derivatives have a key that works across both archive eras** — 28,984
  contracts in 2015 and 35,089 in 2026 parsed with zero failures and zero
  duplicate keys.
- **The trading calendar is a record, not a rule.** A day is a trading day
  because a file exists for it.
- **The master is persisted**, so it is an artefact with a build stamp rather
  than a moving target rebuilt on every call.

## How to check it yourself (2 minutes)

```bash
make verify         # expect: 5 of 5 green
make check-master   # expect: 6 of 6 green
```

Expected from `check-master`: 580 renames, all 34 formerly-stuck symbols
accounted for, 10 successions cited, ratios present, past dates returning past
names, and 3,328 instruments persisted.

## What is fake right now

| Thing | Why | Removed in sprint |
|---|---|---|
| `TATACOFFEE` ratio recorded as two legs | Correct, but derived from reporting rather than the scheme document | — |
| `DHANI` succession has no ratio | Recorded `terms_pending`; the per-share ratio was never published in sources checked | when terms surface |
| Broker map covers 71.9% of mappable equities | The rest are SME-platform listings absent from the main-board bhavcopy | when SME data is ingested |

## What I could not verify

- **Whether 580 renames is the true count.** It is plausible for eleven years
  and far better than the 7,304 the first build produced, but nothing
  independent confirms it.
- **The master is built monthly, not daily.** A rename that happened and
  reversed inside one month would be missed. `--cadence daily` exists and reads
  2,800 files instead of 140; it has not been run.
- **Token reuse has never actually been observed.** The detector finds none in
  a single snapshot, which is expected — reuse shows up across time, and we
  have only mapped one date.

## Four mistakes, and what each cost

1. **My ISIN regex demanded 13 characters.** An ISIN is 12. It rejected a real
   ISIN outright. Caught by a test within a minute — the cheap kind.
2. **The issuer-prefix rule merged unrelated ETFs.** One fund house issues many
   products under a shared prefix, so `INF209KB19` swallowed three unrelated
   ETFs into one instrument whose ticker appeared to flap, inflating renames to
   7,304. Caught because the number was implausible, not because anything
   failed. This was the exact "cost if wrong" written into ADR-012 hours
   earlier.
3. **Four symbols were reported delisted that never were.** They trade in the
   BE series, which Kite names `TICKER-BE`; my lookup matched the bare ticker.
   **The worst of the four** — a wrong alias produces visibly wrong data, but a
   missing instrument looks exactly like a legitimate corporate event.
4. **The broker map reported 7,485 unmapped instruments.** They were mostly
   bonds: Kite files debentures and ETF NAV feeds under `instrument_type=EQ`.
   Comparing an equity master against a list that is 60% debt is not a finding,
   and a check that cries wolf gets ignored.

## A fifth mistake, caught by CI

The `persisted` check depended on `data/master/instruments.json`, but `data/`
is gitignored — so it passed locally and failed in CI, where the file does not
exist. That directly contradicted the stated reason for choosing JSON over
Parquet: *diffable in git review*. An artefact nothing can review is not
diffable.

The master is now committed. It is 1.4 MB of curated output, not raw data, and
downstream code joins on it — so a fresh clone can resolve symbols without
rebuilding from B2, and a change to any instrument's history shows up in
review.

## Decisions you made

| Decision | Recorded in |
|---|---|
| Internal id from the ISIN issuer prefix | ADR-012 |
| Succession is several relationships, not one alias | ADR-013 |
| Supplied the DHANI, JPASSOCIAT and TATACOFFEE terms | research notes 007 |

## Reading added for you

- **Lookahead and survivorship bias** (MUST, 60 min) — now due. Sprint 4 builds
  the firewall and you approve it. This sprint produced five concrete examples
  of survivorship bias in the wild, which is unusually good preparation.

## Next sprint

**Sprint 4 — bitemporal read API and lookahead firewall.** The gate everything
downstream depends on: an `as_of` that is structurally incapable of returning
data from the future, plus an adversarial test suite that tries to break it.
