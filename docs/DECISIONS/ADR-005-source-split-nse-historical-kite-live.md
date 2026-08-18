# ADR-005 — NSE archives for history, Kite for live; two sources, no more

**Date:** 2026-08-18 · **Sprint:** 1 · **Status:** accepted

**Context.** The operator set a data-source policy: use Zerodha wherever it can
serve the need, keep the total to one primary and one fallback, and do not let
sources proliferate. Sprint 1 needs survivorship-free equity and F&O end-of-day
history back to 2015. Research note 002 tested whether Kite Connect can supply
it.

**Options.** (a) Kite for everything. (b) NSE archives for everything, dropping
Kite until Sprint 2. (c) Split by data *type*: NSE archives for historical
backfill, Kite for live.

**Choice.** (c). Operator confirmed 2026-08-18.

**Why.** Kite's cost is not the obstacle — the pricing page confirms historical
candles are included at ₹500/month, so ADR-004 stands. The obstacle is
structural: Kite's instruments dump is *"generated once everyday"* and lists
what is tradable now. Backfilling eleven years from a present-tense instrument
list silently omits every delisted company and every expired contract, which is
survivorship bias by construction — the exact defect this platform exists to
prevent, and one that no care in the downloader can undo. Kite also documents
expired-contract history for *futures* only, and warns that *"exchanges may
reuse instrument tokens for different derivative instruments after each
expiry"*, so its token is unsafe as a historical key. A bhavcopy is the opposite
shape: one file per trading day containing everything that traded, survivors and
casualties alike. Option (b) was rejected because it defers the Kite account
lead time and would push Sprint 2, whose recorder genuinely needs a live feed.

**This still honours the policy.** Two sources total. Kite remains primary
everywhere it can actually serve — live quotes, streaming, option chains from
Sprint 2 — and is displaced only for historical backfill.

| Data | Primary | Fallback |
|---|---|---|
| Historical EOD, 2015 → | NSE archives | Kite historical API, recent dates only |
| Live / intraday / option chains | Kite Connect | none (NSE is not a live source) |

**Cost if wrong.** Low. The downloader talks to a `Transport` protocol and
builds URLs in one module, so swapping or adding a source is contained. The
expensive mistake would be the other direction: a year of backtests built on a
survivor-only universe, discovered late, with every result needing to be thrown
away.

**Revisit when:** NSE's archive becomes unavailable or its terms forbid bulk
access (A-010), or the Sprint 6–7 quality engine finds anomalies that a single
historical source cannot adjudicate.
