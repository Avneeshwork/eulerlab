# ADR-018 — Options quality runs on EOD chains, and fits them robustly

**Date:** 2026-08-19 · **Sprint:** 7 · **Status:** accepted

**Context.** The build plan verifies Sprint 7 with `make quality-options` "on
your recorded chains" — meaning Sprint 2's intraday recorder, which has been
deferred four times and has never run. There are no recorded chains. What
exists is 2,868 days of F&O bhavcopy, which carries every strike, expiry and
right with a settlement price and open interest.

**Options.** (a) Block Sprint 7 until the recorder runs. (b) Run the checks on
EOD bhavcopy chains. (c) Skip to Sprint 8.

**Choice.** (b), with two consequences recorded below.

**Why.** The no-arbitrage mathematics is identical on a daily snapshot; only
the resolution differs. Blocking would leave the checks unwritten *and* the
data unchecked, and the checks are most of the work — pointing them at
intraday chains later is a source change, not a rewrite.

Two things follow from the data shape and are not incidental:

**Parity is checked against the same-expiry future, not a spot price.** The
legacy F&O file has no underlying column and an index level is not in the cash
bhavcopy either, so a spot-based check could not run on 2015–2024 at all. The
future is in the same file. This is also the correct form: Indian index
options are European and cash-settled, so Black-76 applies, and the forward
already contains the dividend and repo assumptions that a spot model would
have to invent.

**The forward is fitted with Theil-Sen, not least squares.** The fitted line
is the benchmark every parity and intrinsic check is measured against.
Ordinary least squares has a breakdown point of zero, so one corrupted quote
does not merely escape detection — it destroys the instrument used to detect
it. Found by a test: one call planted at ₹1 against a ₹1,000 intrinsic pushed
the OLS discount factor out of range, the fit returned None, and the check
reported nothing. This is the same failure as standard deviation in ADR-017,
in a different disguise, and takes the same answer.

**Cost if wrong.** The resolution limit is real: EOD chains cannot show
intraday arbitrage, which is where most genuine violations live and where the
options recorder would earn its cost. What EOD *can* find is stale marks,
inverted ladders and impossible settlement prices — data defects rather than
trading opportunities, which is what a quality engine is for. If the recorder
ever runs, these checks take its output unchanged.
