# ADR-053: Record the live chain, because the spread is not in the bhavcopy

## Status

Accepted, 2026-10-05.

## Context

The brief was to scrape option data and land three months of it. Three months
of daily option data turned out to be already here — 678 F&O bhavcopy days
back to 2024, and the bhavcopy's columns are a superset of what the scraping
candidates return (research note 060). So the daily question was closed by
reading the files properly rather than by fetching anything.

One thing the bhavcopy genuinely does not have, at all, in any column: **a bid
and an ask**. It records a settlement price, which says where a contract was
marked. It does not say what getting out of it would have cost.

That gap is not cosmetic for this project. Every result here is net of a cost
model, and for options the spread *is* most of the cost — the landed NIFTY
21500 PE quotes 0.85 against 0.90, a 5.6% round trip on a contract whose
settlement price alone looks perfectly tradable.

## Decision

Record NSE's live option chain on a schedule, as its own feed step.

**It is in the daily feed rather than a separate command because it is the one
source that cannot be caught up.** The bhavcopy is published after the close
and can be fetched for any past day. A chain snapshot carries quotes that
exist only while the market is open and are gone the moment it shuts. Every
session the recorder does not run is a session of spreads nobody can recover,
at any effort.

**Called directly, not through `jugaad-data`.** That library wraps the same
two URLs. It has no LICENSE file and GitHub reports none, which makes it
all-rights-reserved by default, and the cookie handling it provides is forty
lines. The dependency bought nothing and cost a licence question.

**One immutable file per snapshot**, named by instant and expiry. Appending to
a daily file would let a re-run corrupt what an earlier one wrote, and landed
data is beyond editing (CLAUDE.md).

**Both timestamps on every record.** For a live snapshot `event_time` and
`knowledge_time` are the same instant, which is precisely the property that
makes a recorded chain worth more than a reconstructed one.

## What it cost to get right

The first version reported all four symbols unavailable while NSE was serving
all four perfectly well. `/option-chain-v3` **requires** an `expiry`
parameter; without one it answers 200 with an empty row set rather than an
error. An empty success reads as "the market has no options today", and
nothing in the response says otherwise. The expiry list now comes from
`/option-chain-contract-info` first, and a test asserts the parameter is on
the request.

## Cost if wrong

This is NSE's website API: undocumented, unsupported, free to change shape or
start refusing without notice. Nothing in the trading path depends on it,
every call is bounded at 10s connect (after S-034), and calls are paced at
1.5s because a recorder that gets itself blocked records nothing. If it breaks
the feed reports that step failed and the other seven still run.
