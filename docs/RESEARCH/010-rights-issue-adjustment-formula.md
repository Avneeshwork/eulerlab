# 010 — The rights-issue adjustment formula

**Sprint:** 5 · **Date:** 2026-08-19 · **Confidence:** high (two independent
formulations cross-checked algebraically, and the issue-price rule validated
against a real event)

## Question

S-011 left rights issues parsed but unadjusted, because a rights issue cannot
use the bonus/split formula. A bonus is free; a rights issue is a *purchase* at
a set price, so the dilution depends on how far below market that price sits.
What is the correct factor, and where do its inputs come from?

## Finding: NSE's own F&O adjustment formula

NSE adjusts derivative strikes and lot sizes for corporate actions, and
publishes the formulas. As documented for rights:

    Adjustment Factor = (P − E) / P
      P = underlying close price on the last cum date
      E = benefit per share = C / (A + B)
      C = benefit per right   = (P − S) × A
      S = issue price of the rights
      A = rights entitlement (new shares)
      B = existing shares held

Source: Zerodha's summary of the NSE methodology,
<https://support.zerodha.com/category/trading-and-markets/trading-faqs/f-otrading/articles/adjustment-f-o-contracts>,
fetched 2026-08-19. The NSE primary pages
(<https://www.nseindia.com/static/products-services/equity-derivatives-corporate-actions-adjustments>
and <https://www.nseclearing.in/clearing-settlement/equity-derivatives/corporate-actions-adjustment>)
both timed out on fetch, and circular FAOP56050 came back as unreadable
encoded PDF — see "What I could not verify".

## Finding: it is algebraically the theoretical ex-rights price

The textbook quantity is TERP, the theoretical ex-rights price:

    TERP = (B × P + A × S) / (A + B)

These are the same statement. Expanding NSE's:

    P − E = P − (P − S)·A/(A+B)
          = [P(A+B) − (P−S)A] / (A+B)
          = [PA + PB − PA + SA] / (A+B)
          = (PB + SA) / (A+B)
          = TERP

So NSE's adjustment factor is exactly `TERP / P`. Two independent sources
agreeing through algebra is a much stronger check than either alone, and it is
why this is recorded as high confidence despite the primary NSE page not being
fetchable.

## Finding: issue price = face value + premium, validated on a real event

The feed states the *premium*, not the issue price. Indian convention is that
the issue price is face value plus premium. Validated against Reliance
Industries' 2020 rights issue, which was widely reported at **₹1,257 per
share**:

| Feed field | Value |
|---|---|
| `subject` | `Rights 1:15 @ Premium Rs 1247` |
| `faceVal` | `10` |

1247 + 10 = 1257. The rule holds exactly on a large, well-documented event.

## Finding: the two "adjustment factors" point in opposite directions

A genuine trap worth naming. NSE's bonus factor is `(A+B)/B` — a number ≥ 1
that prices are *divided* by. NSE's rights factor is `(P−E)/P` — a number ≤ 1
that prices are *multiplied* by. Mixing the two senses inverts the adjustment.

This codebase uses one convention everywhere: **every factor is a number ≥ 1
that a pre-action price is divided by**. So the rights factor stored is the
reciprocal of NSE's, `P / TERP`.

## Finding: no adjustment when the rights are priced at or above market

If `S ≥ P`, the right to buy confers no benefit — nobody would subscribe at a
premium to the market — and NSE's `C = (P − S) × A` goes zero or negative. The
implementation returns no factor in that case rather than producing a
nonsensical one that would adjust prices upward.

## Decision

Implement `ParsedComponent.rights_multiplier(cum_price, face_value)` returning
`P / TERP`, fold it into both the price-adjusted and total-return factor
stores, and require a close-price lookup for it — a rights factor cannot be
computed from the ratio alone, unlike bonus and split.

## What I could not verify

- **The NSE primary source directly.** Both official pages timed out and the
  circular PDF would not decode. The formula is taken from a broker's summary
  of it, cross-checked against the standard TERP identity. Recorded as
  A-015 with a recheck date rather than treated as settled.
- **Whether NSE uses the close on the last cum date or a VWAP** for `P`. The
  wording says close. This implementation uses the previous close recorded on
  the ex-date's own bhavcopy row, which is that same number.
- **Partly-paid rights.** One observed subject line
  (`"Rights - 4:25 Fully Paid Up Shares ... / 2:25 Partly Paid Up Shares ..."`)
  describes two instruments at once. It does not parse and is counted as
  UNPARSED rather than half-applied.
