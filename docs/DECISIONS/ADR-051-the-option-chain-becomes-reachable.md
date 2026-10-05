# ADR-051: The option chain becomes reachable

## Status

Accepted, 2026-10-05.

## Context

Comparing this platform against OpenAlgo's tool list, the obvious gap was
options: they advertise eighteen options tools — chain, Greeks, OI tracker,
max pain, vol surface, GEX, IV smile — and this console had none.

That reading was wrong about the cause. The analysis already existed:

- `options/chain.py` parses F&O bhavcopy into chains
- `options/iv.py` solves Black-76 implied vol
- `options/arbitrage.py` runs five no-arbitrage checks — put-call parity,
  strike monotonicity, butterfly convexity, intrinsic bounds and calendar
  monotonicity, fitted with Theil-Sen rather than least squares

F&O bhavcopy lands every night. What was missing was any way to reach it. The
capability matrix has read *"options 1d — chains parsed, no strategy path"*
since the options-quality sprint, and that was accurate.

## Decision

`/api/options/chain` and an Options tab. No new analysis: the endpoint calls
the same `build_chains`, `implied_vol` and `run_chain_checks` the quality
command already used.

**The forward is fitted from put-call parity before it is taken from the
future.** This was not the first implementation and the first one was wrong in
a way that only showed up on real data. Taking `chain.future.price` works for
monthly expiries and returns `None` for every weekly, because index futures
are monthly and the options are weekly — so roughly three chains in four
priced `forward: None` and showed no implied vol at all. `implied_forward_and_discount`
fits `C - P = DF*F - DF*K` across strikes, which works for any expiry and
returns the discount factor with it. That matters twice: the first version
hardcoded `discount=1.0`, which silently shifted every vol on the screen by an
unknown amount.

Measured after the change: the 2026-10-06 weekly went from 0 to 85 of 116
strikes priced. At the money, call and put IV agree to 0.1 percentage points
(12.1% against 12.0% at strike 22,450, forward 22,461.82), which is the
sanity check that the solver is right.

**Untraded contracts are dimmed, not hidden.** An untraded contract's price is
NSE's settlement model output rather than a transaction, so it means something
different from the number beside it. Rendering both identically is what
invites someone to average them. The arbitrage checks run `traded_only=True`
for the same reason, and the screen says so.

## What was not built

OpenAlgo's other seventeen options tools — max pain, GEX, vol surface, OI
tracker — are mostly views over the same chain this now serves, and are cheap
to add on top of it. They are not here yet because one correct screen is worth
more than six approximate ones, and because each needs its own decision about
what it is claiming.

## Cost if wrong

The endpoint computes nothing the quality command did not already compute, so
a wrong number here is a wrong number there, and `make quality-options` is the
check that would catch it.
