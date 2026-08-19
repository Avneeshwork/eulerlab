# 008 — Is there a machine-readable corporate-actions feed?

**Sprint:** 3 · **Date:** 2026-08-19 · **Confidence:** high (endpoint queried
directly, date handling verified)

## Question

Eleven unresolved symbols each needed a hand-written citation. Before adding
more by hand, is there a systematic source?

## Finding: yes, and it honours dates

`nseindia.com/api/corporates-corporateActions?index=equities&from_date=DD-MM-YYYY&to_date=DD-MM-YYYY`

Verified 2026-08-19. Returns structured JSON with `symbol`, **`isin`**,
`subject`, `exDate`, `recDate`, `faceVal`, `series`, plus book-closure and
no-delivery windows.

**The date parameters work**, unlike the FII/DII endpoint which silently
ignored them (research note 004). Jun–Jul 2023 returned 520 rows with exDates
correctly inside the window; July 2023 alone returned 343.

Breakdown for July 2023:

| Type | Count |
|---|---|
| Dividend | 242 |
| Meetings and other | 82 |
| Bonus | 10 |
| Split | 3 |
| Rights | 4 |
| **Demerger** | **2** |

The `isin` field matters most: it joins directly to the security master's key
rather than to a ticker, so corporate actions attach to the right instrument
across a rename.

## Finding: it does NOT contain mergers that delist the target

Searching July 2023 for the HDFC merger — a ₹13-lakh-crore event with a known
2023-07-01 effective date — returns **nothing**. No HDFC row of any kind.

Demergers *are* present (`RELIANCE`, ex 2023-07-20, the Jio Financial split;
`SAREGAMA`, ex 2023-07-27).

The asymmetry makes sense: a company delisting *through* a merger stops being
an NSE equity, so the event is recorded against the acquirer or as a delisting
notice, not as a corporate action on the disappearing company. The feed answers
"what happened to this listed security", and after a merger the target is no
longer one.

**So this feed does not close the merger gap.** Those still need per-case
citation, and this is now known rather than assumed.

## Decision

Two separate uses:

1. **Sprint 5 (corporate actions / adjustment engine)** — this is the source.
   Dividends, bonuses, splits and rights all arrive structured, dated, and
   keyed by ISIN. That is most of what an adjustment engine needs, and it means
   Sprint 5 does not have to scrape.
2. **Merger successions** — not available here. Continue recording per case
   with a citation (ADR-013), and treat the absence as a known limitation
   rather than a search that has not been done yet.

## What I could not verify

- How far back the feed reaches. Only 2023 and the current window were tested.
- Whether `subject` is reliably parseable. It is free text: "Bonus 1:2",
  "Rights 1:1 @ Premium Rs 1.30/-", "Dividend - Rs 23 Per Share". Ratios can
  probably be extracted with care, but that is Sprint 5's problem and it will
  need a fallback for unparseable strings.
- Whether a separate delisting or amalgamation feed exists elsewhere on NSE.
  Not searched.
