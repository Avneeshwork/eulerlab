# Sprint 3 — Security master

**Status:** PARTIAL
**Branch:** sprint-03-security-master   **Commits:** 8

The identity and succession layers are built and verified against eleven years
of real data. The sprint's own acceptance command, `make check-master`, is not
built — so this is honestly partial, not complete.

---

## What now works (plain English, no jargon)

- **The system knows that ZOMATO and ETERNAL are the same company**, and worked
  it out from the data rather than being told. It found **580 renames** across
  2015–2026 by following ISIN continuity.
- **Ask what was true on a past date and get the past answer.** Every attribute
  is stored as an interval, so a lot size in March 2019 returns March 2019's
  value, not today's.
- **A delisted company stops claiming its ticker.** Daily files never announce
  a delisting — the rows just stop — so without this a dead 2015 instrument
  would shadow whoever holds that ticker now.
- **Corporate events are modelled as four different things**, because
  collapsing them was actively dangerous: a rename continues the price series,
  a merger ends it, a demerger splits it, a cancellation extinguishes a share
  class. Each carries a cited ratio.

## How to check it yourself (2 minutes)

```bash
make verify      # expect: 5 of 5 green, 247 tests
```

`make check-master` is the command this sprint was supposed to deliver and it
does not exist yet. That is the main reason for the PARTIAL.

## What is fake right now

| Thing | Why | Removed in sprint |
|---|---|---|
| Lot-size history | The field is populated from `NewBrdLotQty` but has never been checked against a known past value | 3 (remaining work) |
| F&O instruments | Not in the master at all — derivatives have no ISIN, so they need a composite key | 3 (remaining work) |
| Trading calendar | Not built | 3 (remaining work) |

## Data issues fixed

| Issue | Before | After |
|---|---|---|
| Participant-OI gaps | 7 missing days | **0** |
| Unresolvable minute symbols | 34 | **2** (`DHANI`, `JPASSOCIAT`) |
| Minute coverage | 411 symbols, 173M bars | **420 symbols, 184M bars** |
| Spurious renames | 7,304 | **580** |

## Three mistakes, and what each cost

1. **My ISIN regex demanded 13 characters.** An ISIN is 12. It rejected a real
   ISIN outright — caught immediately by a test, which is the cheap kind.
2. **The issuer-prefix rule merged unrelated ETFs.** A fund house issues many
   products under one prefix, so `INF209KB19` swallowed ABSLPSE, BSLNIFTY and
   SILVER into one instrument whose ticker appeared to flap — inflating renames
   to 7,304. Caught because the number was implausible, not because anything
   failed. This was the exact "cost if wrong" written into ADR-012 hours
   earlier.
3. **Four symbols were reported delisted that were never delisted.**
   `RELINFRA`, `STLTECH`, `DIACABS`, `MTARTECH` trade in the BE series, which
   Kite names `TICKER-BE`. My lookup matched the bare ticker. **This is the
   worst of the three**: a wrong alias produces visibly wrong data, but a
   missing instrument looks exactly like a legitimate corporate event.

## What I could not verify

- **`TATACOFFEE`'s ratio.** Sources give 3:10 and 14:55 for a
  demerger-plus-amalgamation. Deliberately unrecorded — a guessed ratio
  silently misprices every position carried across the event.
- **`DHANI` and `JPASSOCIAT`.** Not researched. `JPASSOCIAT` is probably an
  insolvency suspension rather than a succession, but that is unconfirmed.
- **Lot-size history.** Populated but never checked against a known value, so
  A-002 remains open.
- **Whether 580 renames is right.** It is plausible for eleven years and far
  better than 7,304, but nothing independently confirms the count.

## Decisions you made

| Decision | Recorded in |
|---|---|
| Skip the F&O recorder, go to Sprint 3 | `TASKS.md` |
| Fix all data issues, search the web for causes | this sprint |

## Reading added for you

- **Lookahead and survivorship bias** (MUST, 60 min) — now overdue. Sprint 4
  builds the firewall and you approve it. This sprint produced four fresh
  examples of survivorship bias in the wild.

## Next sprint

Finish Sprint 3: F&O composite keys, the trading calendar, and
`make check-master`. Then Sprint 4 — the bitemporal read API and lookahead
firewall, which is the gate everything downstream depends on.
