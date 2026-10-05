# ADR-052: Options analytics written from the mathematics, not extracted

## Status

Accepted, 2026-10-05.

## Context

The brief was to build OpenAlgo's seventeen options tools, and then — when it
was pointed out that OpenAlgo is open source — to extract their code if that
helped.

OpenAlgo is **AGPL-3.0**. Code copied from it makes the copying work a
derivative that must itself be AGPL, and §13 adds the network clause: run it
somewhere others can reach and you must offer them the complete source. This
repository is private and holds a trading edge. Taking that licence on is a
decision with consequences that are very hard to reverse, and it would be a
strange one to make by accident in the course of adding a chart.

It is also unnecessary. Max pain is a sum of intrinsic payouts. The put-call
ratio is a division. Black-76 is from 1976 and the Greeks are its partial
derivatives. Gamma exposure is gamma times open interest. None of this is
OpenAlgo's invention or their expression of it — it is textbook mathematics
that anyone may implement.

## Decision

Everything written from the mathematics. No code, no structure and no comments
taken from OpenAlgo. The only thing used from them is the *list of tools*,
which is a factual observation about what a product offers.

Writing it rather than copying it also let the implementation suit this
platform's data, which theirs would not have:

- **The forward is fitted from put-call parity**, not taken from a future.
  Index futures are monthly and the options are weekly, so about three chains
  in four have no exact-expiry future; the fit also returns the discount
  factor, which was otherwise hardcoded to 1.0 and shifting every vol.
- **Untraded contracts are dimmed, never hidden or dropped.** Their price is
  NSE's settlement model output rather than a transaction. The arbitrage
  checks run `traded_only` for the same reason.
- **The gamma sign convention is named, not folded in.** Dealers being long
  calls and short puts is an assumption about who holds the other side of the
  open interest, and the bhavcopy does not say. A profile with the wrong sign
  marks support and resistance at exactly the wrong strikes.
- **Max pain is labelled a description, not a forecast**, on the screen.
- **Greeks return `None` at expiry and at zero vol**, not zero. Delta is
  genuinely discontinuous there and gamma unbounded, so a zero would be a
  convention — and one that gets averaged into a portfolio total as "no
  exposure".

## What was built, and what was not

Built: the chain, Greeks (delta, gamma, vega, theta), the IV smile, max pain
with its whole curve, the gamma profile with its flip, the put-call ratio by
open interest and by volume, and the five no-arbitrage checks surfaced.

Not built, and recorded as S-037: six tools whose meaning depends on intraday
measurement (live OI tracker, straddle roll, straddle PnL simulator, live
chain with bid/ask) and two needing an order path (basket builder, live
portfolio). The chain recorder does not exist and there is no live broker
adapter. A daily series of an intraday quantity is a different number wearing
the same name, so none were approximated.

## Cost if wrong

The Greeks are pinned by identity tests — parity on delta, gamma and vega
equal across rights, and each one checked against a numerical derivative of
the price — so an error there fails a test rather than sitting in a total.
