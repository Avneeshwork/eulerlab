# 007 — Is HDFC the same as HDFC Bank?

**Sprint:** 3 · **Date:** 2026-08-19 · **Confidence:** high (primary reporting
on the merger terms)

## Question

The security master listed `HDFC` as having "no successor". The operator asked
whether HDFC is HDFC Bank. It is a good question, because the honest answer is
*neither yes nor no*, and the difference decides whether a data fix is correct
or silently corrupting.

## Findings

**HDFC Ltd merged into HDFC Bank**, effective **2023-07-01**, record date
2023-07-13, at **42 HDFC Bank shares per 25 HDFC Ltd shares** (1:1.68). HDFC
Ltd shareholders ended up with about 41% of HDFC Bank.

Sources (fetched 2026-08-19):
- https://www.hdfc.bank.in/press-release/2023/q2/hdfc-ltd-to-merge-into-hdfc-bank-effective-july-1-2023
- https://www.business-standard.com/finance/news/hdfc-bank-allots-over-311-cr-shares-to-hdfc-ltd-shareholders-in-share-swap-123071400663_1.html

**IDFC Ltd merged into IDFC FIRST Bank**, effective **2024-10-01** per the NCLT
order of 2024-09-25, at **155 shares per 100**.

Source: https://www.idfcfirst.bank.in/merger-of-idfc-ltd-and-idfc-first-bank

## Why this matters more than it looks

HDFC Ltd and HDFC Bank were **two separately listed companies** with two
separate price series. So:

**Aliasing HDFC to HDFCBANK for data would be wrong.** Fetching HDFCBANK to
fill a gap labelled HDFC does not recover HDFC Ltd's history — it substitutes a
different company's prices into a series that claims to be HDFC's. Nothing
downstream would flag it: the data would be well-formed, complete-looking, and
wrong. HDFC Ltd's series genuinely *ends* on 2023-07-01.

**But the merger is essential for portfolio continuity.** A backtest holding
100 HDFC shares on the record date received 168 HDFC Bank shares. Ignoring that
either drops the position or misprices it.

So "no successor" was half-right: correct that no *data* successor exists,
wrong to imply nothing happened.

## Decision

Model three distinct relationships rather than one alias map (ADR-013):

| Kind | Same entity? | Ratio | Safe to alias for data? |
|---|---|---|---|
| **Rename** | yes, same ISIN | none | **yes** — series continues (ZOMATO → ETERNAL) |
| **Merger** | no, absorbed | required | **no** — series ends (HDFC → HDFCBANK, 1.68) |
| **Demerger** | no, split | required, one per successor | **no** — one-to-many |

The ratio is what makes the distinction operational: a rename exchanges
nothing, so it carries no ratio and the code rejects one; a merger or demerger
cannot be recorded without one, because a position could not be carried across
the event.

## Consequence for the stuck symbols

Of the 13 with no ISIN continuity, at least two are mergers with known terms
and are now recorded as such. They remain **correctly absent from the
minute-bar backfill** — there is no history to fetch under the successor's
name — but a portfolio holding them can now be carried across the event.

## Resolution of all 11 unresolved symbols

Researched 2026-08-19. **Four were never delisted at all** — that was a bug in
our code, not a fact about the world.

### Four false delistings: the BE-series bug

`RELINFRA`, `STLTECH`, `DIACABS`, `MTARTECH` are listed today. They trade in
the **BE (trade-for-trade) series**, and Kite names those `TICKER-BE` on NSE
while the bhavcopy uses the bare ticker. `parse_instruments` matched the bare
name only, so all four were reported "not in Kite's current instrument list" —
a false negative indistinguishable from a real delisting.

Fixed: the lookup now strips known series suffixes (`-BE`, `-BZ`, `-SM`, `-ST`,
`-IT`) and prefers the plain listing when both exist. All four now resolve and
their minute history has been fetched.

**This is the more valuable finding of the two.** A wrong alias produces
visibly wrong data; this produced a *silently missing* instrument that looked
like a legitimate corporate event.

### Five genuine successions, now recorded with terms

| Symbol | Event | Effective | Ratio | Source |
|---|---|---|---|---|
| `MINDTREE` | merged into LTI (→ LTIM → LTM) | 2022-11-14 | 73 : 100 | record date 2022-11-24 |
| `TV18BRDCST` | merged into NETWORK18 | 2024-10-03 | 100 : 172 | NCLT-sanctioned |
| `TATAMTRDVR` | **cancellation** into TATAMOTORS | 2024-09-01 | 7 : 10 | DVR conversion record date |
| `PEL` | merged into PIRAMALFIN | 2025-09-23 | 1 : 1 | PEL delisted, 1-for-1 allotment |
| `TATACOFFEE` | merged into TATACONSUM | 2024-01-01 | **disputed** | see below |

### A fourth category was needed

`TATAMTRDVR` is neither a rename nor a merger. Tata Motors DVR ('A' ordinary)
shares were **cancelled** and converted into ordinary shares of the *same*
company at 7 per 10. No second company is involved and the issuer survives, so
it is not a merger; but DVR shares traded at a persistent discount to ordinary,
so the series are not continuous and it is not a rename either.

`SuccessionKind.CANCELLATION` was added for this. Like a merger it requires a
ratio and does not continue the price series.

### Still unresolved, and why

- **`TATACOFFEE`** — sources disagree on the ratio. One states 3 TCPL per 10
  Tata Coffee; another 14 per 55 (0.300 vs 0.255). The event was a demerger
  *plus* an amalgamation, so these are plausibly two legs of one scheme rather
  than a contradiction. **Not recorded until the split is understood** —
  guessing a ratio silently misprices every position carried across it.
- **`DHANI`**, **`JPASSOCIAT`**, **`DIACABS`** (as a historical symbol) — not
  researched individually. `JPASSOCIAT` is in insolvency proceedings, which is
  a suspension rather than a succession, but that is unconfirmed.

## What I could not verify

- Terms for the remaining 11 (DHANI, DIACABS, JPASSOCIAT, MINDTREE, MTARTECH,
  PEL, RELINFRA, STLTECH, TATACOFFEE, TATAMTRDVR, TV18BRDCST). Each needs its
  own citation; none is guessed at.
- `TATAMTRDVR` is likely a *cancellation* rather than a succession — DVR shares
  were extinguished in the Tata Motors restructuring — which may be a fourth
  category. Not modelled until confirmed.
- Whether NSE publishes a machine-readable corporate-action feed that would
  make this systematic rather than hand-cited. Worth checking before adding
  more entries by hand.
