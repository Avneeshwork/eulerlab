# ADR-013 — Rename, merger and demerger are modelled separately

**Date:** 2026-08-19 · **Sprint:** 3 · **Status:** accepted

**Context.** The security master resolved 21 of 34 stuck symbols by ISIN
continuity and reported 13 as "no successor". The operator asked whether HDFC
is HDFC Bank. It is — economically — but HDFC Ltd and HDFC Bank were two
separately listed companies, and treating that as a rename would substitute one
company's price history for another's.

**Options.** (a) One flat alias map, old symbol to new. (b) Renames only, and
leave everything else unresolved. (c) Three typed relationships with ratios.

**Choice.** (c).

**Why.** (a) is what was nearly shipped in Sprint 1 and is wrong in two
directions: it would substitute HDFC Bank's prices for HDFC Ltd's, and it
cannot express a demerger at all. (b) is safe for data but loses portfolio
continuity — a position in HDFC on the record date really did become 1.68x as
many HDFC Bank shares, and a backtest that ignores that is wrong too.

Only (c) can answer both questions the platform actually asks: *may I read the
successor's history as this instrument's?* (rename only) and *what happened to
a position held across the event?* (ratio).

The ratio is the discriminator, enforced in code: a rename exchanges nothing so
a ratio is rejected; a merger or demerger cannot be constructed without one.

**Cost if wrong.** Low and visible. An unrecorded succession leaves a symbol
unresolved — a gap you can see. The expensive error is the opposite, and it is
the one this prevents: a merger recorded as a rename produces a complete-looking
price series made of two different companies, which no test would catch.
