# ADR-055: The payoff diagram shows expiry, and only expiry

## Status

Accepted, 2026-10-05.

## Context

A multi-leg payoff diagram was the one piece of OpenAlgo's strategy builder
that this platform could actually build. The rest of that tool fires a basket
at a broker, which needs the live adapter of S-015; the diagram needs nothing
but the chain already on screen.

## Decision

**Expiry payoff only.** A "current value" curve is the obvious next ask and is
deliberately not offered. It would need a vol surface projected forward and a
view on how it moves — a set of assumptions in the shape of a line, and a line
is very persuasive. Intrinsic value at expiry has no assumptions in it at all:
it is arithmetic on the strike and the premium, and it is true whatever vol
does between now and then. The caption says which one it is.

**Priced off the chain on screen.** Changing the day or the expiry reprices
every leg, because a spread that works on today's board is a different trade
on last month's, and a builder that kept yesterday's premiums while the chain
moved would be quietly answering a different question.

**Unbounded is reported as unbounded.** A naked short call loses without
limit. The worst value inside the listed strike range is a fact about where
the chart stops, not about the position, and printing it as "max loss" would
be the most dangerous number on the screen. The curve's slope at each edge
decides which word appears.

**Lot size comes from the bhavcopy, per contract.** It is a time-versioned
field that CLAUDE.md forbids hardcoding, and it is now carried through the
chain endpoint for exactly this.

**Costs are not applied, and the caption says so.** Brokerage, STT and the
bid-ask spread all land against this payoff. The spread in particular can be
several percent on a contract whose settlement price looks perfectly tradable
— the recorder (ADR-053) exists because of that gap. Showing a gross payoff
labelled as such is honest; showing it unlabelled would not be.

## Verification

An at-the-money long straddle on 2026-10-05, hand-computed against the
rendered figures:

| | by hand | rendered |
| --- | --- | --- |
| premium | 82.60 + 79.35 = 161.95 | 82.60, 79.35 |
| breakevens | 22,388 and 22,712 | 22,388 · 22,712 |
| max loss | 161.95 x 65 = Rs 10,527 | −Rs 10,527 |
| max profit | unbounded | unbounded |

And a point off the curve: at a settlement of 23,363 the readout gives
Rs 42,337 against (23,363 − 22,550 − 161.95) x 65 = Rs 42,318, agreeing to the
rounding of the displayed settlement.

## Cost if wrong

The arithmetic is checkable by hand from the two premiums and the strike,
which is why the verification above is in this record rather than only in a
test.
