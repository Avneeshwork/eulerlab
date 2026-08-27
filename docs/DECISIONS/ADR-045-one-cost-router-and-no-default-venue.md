# ADR-045 — One cost router, and no default venue

**Status:** ACCEPTED · 2026-08-26

**Context.** "What does this fill cost" had three answers.

`intraday/bracket._cost` knew crypto, US and NSE-intraday. `backtest/vector._costs_for`
knew US and NSE-**delivery**, and had no crypto branch at all.
`api/server.COSTED_CLASSES` decided separately whether to charge anything. Each
was reasonable where it was written, and together they meant a venue could be
handled correctly in one engine and silently mishandled in the other.

All three took `asset_class` as a bare string defaulting to `"equity"`. That
default produced four separate wrong-number bugs, in sequence:

1. A crypto backtest billed Indian STT, SEBI turnover and stamp duty — charges
   Delta Exchange does not levy.
2. After that was fixed at the leaf, a US backtest billed the same.
3. After *that* was fixed, every **winning** exit still billed Indian STT,
   because two of the six call sites inside `bracket.run` — the target-1 and
   target-2 legs, which are the most common — had kept the default while the
   entry and stop were corrected.
4. A US branch added to the daily engine **never executed once**: none of its
   three callers passed the argument, so every daily run including US was
   charged Indian delivery rates while the routing code above them said
   otherwise.

The fourth was committed while fixing the third.

Each wrong figure was **plausible**. An Indian bill on a US trade is roughly ten
basis points, which looks like a cost. That is what let every one of them
survive, and it is the property worth engineering against rather than the
individual defects.

**Options.**

1. **Fix each site and add tests.** What had already been done three times. It
   does not address why the fourth was possible.
2. **Make the asset class an enum.** Catches typos, not omissions — a defaulted
   enum is exactly as silent as a defaulted string.
3. **One router, and no default anywhere a venue is dispatched on.**

**Choice.** Option 3.

`costs/router.py` owns the question. Venues are an enum. Venues deliberately run
gross of costs — mutual funds — are **named** in `UNCOSTED` rather than falling
out of a missing branch, because "we do not model this" and "nobody wrote the
branch" produce the same zero and mean opposite things. A class the router does
not know raises `UnknownVenue` instead of guessing.

`asset_class` has no default at any dispatch point. Removing it from
`bracket.run` and `vector._costs_for` made mypy name roughly thirty call sites
across nine modules and the tests. Most legitimately mean `"equity"` and now say
so.

**The one caller that mattered was the one that was right.** mypy's first hit
was the NSE Tweezer scanner, where `"equity"` was correct. That is the finding
rather than a footnote: the same default made one call accidentally right and
three others silently wrong, and nothing except being forced to state it
distinguishes those two cases.

**Consequences.**

One default survives, on `paper.run`. It is the **account's** venue rather than
a guess about the data — paper trading is NSE-only today — and that distinction
is what makes a default safe there and unsafe at every level beneath it.

A test asserts the two engines charge identically on venues they share and
differ only on the NSE segment, which is the one difference that is real:
intraday and delivery pay different STT.

**What this does not fix.** Spread and slippage are still modelled on no venue
(A-030), so every net figure remains better than a real fill. The Indian rates
themselves are still from secondary sources and unverified against a contract
note (A-016).
