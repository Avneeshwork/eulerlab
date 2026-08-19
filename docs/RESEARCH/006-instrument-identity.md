# 006 — Which identifier is safe to join on?

**Sprint:** 3 · **Date:** 2026-08-19 · **Confidence:** high (measured against
our own bhavcopy history, not assumed)

## Question

The security master needs a join key. Renames have already broken three
datasets — 10 unresolved symbols in the minute backfill, ~14 in fundamentals,
and a near-miss where a hand-written alias map would have attached the wrong
company's history. Which identifier actually survives?

## Method

Compared cash bhavcopy for **2023-06-15** (legacy format) against
**2026-08-14** (UDiFF), equity series only, and then built the full registry by
walking 47 quarterly snapshots from 2015-01-01 to 2026-07-01.

## Findings

### No single string is permanently stable

| Identifier | Verdict | Evidence |
|---|---|---|
| **Ticker** | unsafe | 131 renames in the 2023→2026 window alone; 400 across the full history. Also *reused*: 149 tickers pointed at a different ISIN in 2026 than 2023 |
| **ISIN** | survives renames, not all corporate actions | ZOMATO and ETERNAL share `INE758T01015`. But 149 tickers changed ISIN |
| **`FinInstrmId`** | unusable | Exists only in UDiFF. **Absent from every pre-2024 file**, so it cannot key a history starting in 2015 |
| **Kite instrument token** | unusable | Kite's own docs state tokens are reused after expiry |

### The 149 ISIN changes are mostly not what they look like

Splitting them by whether the ISIN's first ten characters survived:

| Case | Count | Meaning |
|---|---|---|
| Same issuer prefix, reissued tail | **139** | Split, consolidation or face-value change on the *same* company. `SILVERTUC` went `INE625X01018` → `INE625X01026` |
| Different prefix | **10** | Genuinely different security — and all ten are `INF`-prefixed fund/ETF units, not company equity |

**This corrected an error made mid-analysis.** The 149 were initially read as
"149 tickers that would silently join two different securities". That is wrong
for 139 of them: they are one company whose ISIN was reissued, and treating
them as two would *split one price history in half* — the opposite failure, and
just as damaging.

## Decision

The internal id is derived from the **ISIN issuer prefix** — the first ten
characters, which identify the issuer and survive a reissue. The full ISIN and
the ticker are both stored as *time-versioned attributes*, never as keys.
Recorded as ADR-012.

## A second finding, from building it

An instrument that stops trading leaves its final ticker interval **open**,
because a daily file never announces a delisting — the rows simply stop. Left
unbounded, a security delisted in 2015 keeps claiming its ticker forever and
shadows whoever holds that ticker later, silently resolving to the wrong
company.

Resolution is therefore bounded by the observation window (`first_seen`,
`last_seen`) as well as the ticker history. This was caught by a test, not by
reasoning, and it is the kind of error that produces confident wrong answers
rather than crashes.

## Verified end to end

Walking 47 quarterly snapshots, 2015-01-01 → 2026-07-01:

```
47 files, 86,522 rows, 0 skipped for a malformed ISIN
instruments: 3,038
renamed at least once: 400

ZOMATO/ETERNAL ticker history:
  ZOMATO    2021-10-01 -> 2025-07-01
  ETERNAL   2025-07-01 -> current
```

The registry rediscovered the rename from the data alone, with no alias map.

## A third finding: the rule is right for equity, wrong for funds

Building the full map produced **7,304 renames** from ~400 renamed instruments —
about 18 ticker changes each, which is flapping, not renaming.

Cause: a fund house issues many distinct products under one ISIN issuer prefix.
`INF209KB19` alone covers `ABSLPSE`, `BSLNIFTY` and `SILVER` — three unrelated
ETFs sharing a sponsor. The prefix rule merged them into a single instrument
whose ticker appeared to alternate between names.

Measured: **75 issuer prefixes held more than one ticker on a single day, and
every one of them was `INF`.** No `INE` prefix collided.

So the rule is type-dependent:

| ISIN type | Key | Why |
|---|---|---|
| `INE...` company equity | issuer prefix | A reissue is the same company; keying on the full ISIN would split one price history in two |
| `INF...` fund / ETF unit | **full ISIN** | One sponsor issues many products; the prefix is not an identity |

The asymmetry is deliberate. For funds we cannot distinguish a reissue from a
new product, so we do not guess — over-splitting is the safer error, because a
split history is visible while a merged one is silently wrong.

After the fix: **580 renames**, which is plausible for eleven years.

This is the failure mode ADR-012 recorded under "cost if wrong", and it
materialised within an hour of the decision being written.

## What I could not verify

- **Demergers are not yet modelled.** PEL → PPLPHARMA + PIRAMALFIN is
  one-to-many and cannot be expressed by the issuer-prefix rule, because the
  successors have genuinely different issuer prefixes. The registry currently
  treats them as unrelated instruments, which is *honest* but incomplete.
- The quarterly sample is 47 of 2,868 files. A rename occurring and reversing
  inside one quarter would be missed. The full walk is the next step.
- Nothing here covers derivatives, which have no ISIN in the F&O bhavcopy and
  need a composite key (symbol, expiry, strike, right).
