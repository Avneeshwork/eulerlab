# ADR-020 — Transaction costs are a time-versioned schedule

**Date:** 2026-08-19 · **Sprint:** 9 · **Status:** accepted

**Context.** The cost model has to serve a backtest spanning 2015–2026. STT
rates changed twice inside that window — futures went 0.0125% → 0.02% in
October 2024 and → 0.05% in April 2026 — and the *basis* for STT on option
exercise changed in September 2019, from the full notional settlement value to
intrinsic value only.

**Options.** (a) A constants file with current rates. (b) Current rates plus a
comment about history. (c) A schedule keyed by effective date, queried with
the trade date.

**Choice.** (c), the same shape as the time-versioned lot sizes from Sprint 3.

**Why.** (a) applies 2026 rates to a 2016 trade, wrong by a factor of four on
futures STT. It is worth being precise about the direction: this is *not* a
conservative error that merely understates returns. It overstates costs for
old trades, which kills strategies that would have worked, and it produces a
backtest whose costs bear no relation to what would have been paid.

The exercise-basis change is the sharper case. Before 2019-09-01 STT on an
exercised option was charged on the notional settlement value. On Zerodha's
published example — 50 units, strike 17,300, settlement 17,350 — that is
**₹1,084 on a ₹2,500 profit**, 43% of it, against **₹3.75** under today's
rule. This is the well-known "STT trap" that made in-the-money options worth
abandoning. It applies to the first four and a half years of our own price
history, so a 2015–2019 options backtest that ignores it overstates returns on
every expiry it holds through.

`rates_on()` raises rather than falling back when a date precedes the
schedule, because the alternative is costing a trade with rates from years
later, silently.

**Cost if wrong.** The schedule is data, so a corrected rate is one edited
row and a re-run. The real exposure is A-016: every rate comes from broker and
tax-portal summaries that agree with each other, not from the CBDT
notification — NSE's own STT page and circular FATAX73524 both failed to
fetch. `make check-costs` therefore reports **PARTIAL** rather than green
until it has been reconciled against real contract notes, and deliberately
does not substitute a synthetic figure to make itself pass.
