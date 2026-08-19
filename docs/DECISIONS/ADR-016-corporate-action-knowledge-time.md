# ADR-016 — A corporate action's knowledge_time is its own ex-date

**Date:** 2026-08-19 · **Sprint:** 5 · **Status:** accepted

**Context.** The NSE corporate-actions feed (research note 008) gives an
`exDate` for every dividend, bonus, split and rights issue, but the field
meant to carry an announcement date, `caBroadcastDate`, was **null on all
25,644 rows** probed across 2015-2026. There is no earlier date in the feed
than the ex-date itself. The adjustment engine still needs a `knowledge_time`
for every action, because it is built on Sprint 4's bitemporal store, and that
store cannot accept a Record without one.

**Options.** (a) Use `recDate` (record date, usually a day or two after
ex-date) as knowledge_time. (b) Estimate an announcement date as N days before
ex-date, matching the typical regulatory notice period. (c) Use `exDate`
itself.

**Choice.** (c).

**Why.** (a) is worse than doing nothing: it would make an action "knowable"
*after* the date its own price effect already happened, which cannot be used
by a backtest at all — the price series and the metadata explaining it would
be permanently out of order. (b) is a guess with no primary source behind it;
SEBI's notice-period rules vary by action type and have not been read, and a
wrong guess in the *early* direction is exactly the lookahead leak Sprint 4
exists to prevent. (c) is conservative in the correct direction: it may
understate how early a real trader could have known (companies do announce
before the ex-date), but it can never overstate it, and "conservative" here
means "safe to feed into a backtest," not "close to reality."

The consequence is asymmetric and acceptable: a backtest using this data will
under-react to corporate actions relative to a trader with real advance
notice, never over-react. Given the choice between a firewall that is too
strict and one that might leak, too strict is the only one on the table.

**Cost if wrong.** Low. A future sprint that sources real announcement dates
(e.g. from exchange filing timestamps) can tighten `knowledge_time` per action
without changing anything downstream — `factor_as_of` already reads whatever
`knowledge_time` a Record carries; nothing hardcodes "ex-date equals
knowledge."
