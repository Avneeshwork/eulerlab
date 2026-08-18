# ADR-008 — Build the tradable universe from our own turnover, not an index list

**Date:** 2026-08-18 · **Sprint:** 1 · **Status:** accepted

**Context.** The operator asked for "Nifty 250". NSE publishes *Nifty
LargeMidcap 250* and *Nifty Smallcap 250*, but no plain "Nifty 250", so the name
had to be interpreted. More importantly, any published constituent list is
available only as it stands *today*.

**Options.** (a) Fetch a published constituent list and use it across all
history. (b) Source point-in-time index membership from a vendor. (c) Derive the
universe from the bhavcopy history already landed, ranking by liquidity as of a
given date.

**Choice.** (c). Top *N* by median daily traded value over a trailing window
ending at an explicit `as_of` date, from the cash-market bhavcopy.

**Why.** (a) is survivorship bias in its purest form: today's list applied to
2021 data silently omits every company that fell out of the index *because it
did badly*, and the resulting backtest is selected on hindsight. (b) is correct
and costs money we are not spending. (c) uses data we already hold that records
what actually traded on each day, casualties included, and is reproducible from
the landing zone with no external dependency.

Median rather than mean, because one block deal should not promote an otherwise
illiquid name into the tradable set. Equity series only (`EQ`, `BE`), or ETFs
and debt series crowd out actual stocks.

**The guard is the load-bearing part.** The naive implementation produced a
wrong answer that looked entirely right: ranking "the 60 most recent files"
while the backfill was still at 2023 mixed five days of 2026 with fifty-five of
2023 and returned a top-250 containing HDFC, which had merged out of existence
years earlier. Nothing in the output looked suspicious — a company that should
not exist was the only tell. `rank_by_liquidity` therefore refuses any window
containing a gap over 10 days: generous enough for Diwali and long weekends,
tight enough to catch a backfill that has not reached the requested period.

Every written universe file records its `as_of` date. A universe without one is
a bias waiting to be reused on the wrong period.

**Cost if wrong.** Low. The ranking is one function over the landing zone, so
changing the rule — different window, different statistic, a real index list if
we ever buy point-in-time membership — re-runs in seconds and changes nothing
downstream except the symbol list.
