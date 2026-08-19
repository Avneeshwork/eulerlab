# ADR-012 — The internal instrument id is the ISIN issuer prefix

**Date:** 2026-08-19 · **Sprint:** 3 · **Status:** accepted

**Context.** The security master needs a join key that survives eleven years of
history. Renames have already broken three datasets, and a hand-written alias
map was nearly shipped that would have attached the wrong company's data.

**Options.** (a) Ticker. (b) Full ISIN. (c) Exchange `FinInstrmId`. (d) Kite
instrument token. (e) ISIN issuer prefix — the first ten characters.

**Choice.** (e), with the full ISIN and ticker stored as time-versioned
attributes rather than keys.

**Why.** Measured, not assumed (research note 006). Tickers change — 400
renames across the history — and are reused. The full ISIN survives renames
(ZOMATO and ETERNAL share `INE758T01015`) but not corporate actions: 139
observed changes preserved the issuer prefix while reissuing the tail, which is
one company after a split, not two companies. `FinInstrmId` is absent from
every pre-2024 file. Kite's token is documented as reused after expiry.

The issuer prefix is the only part that survived every transition observed.

**Cost if wrong.** Moderate but contained. If two genuinely distinct issuers
ever shared a prefix, their histories would merge — the failure would be silent,
which is why `check-master` asserts prefix uniqueness against observed ISINs
rather than trusting the rule. The reverse error, splitting one company in two,
is what a full-ISIN key would have caused for 139 instruments.

**Known incompleteness.** Demergers are one-to-many (PEL → PPLPHARMA +
PIRAMALFIN) and the successors have different issuer prefixes, so this rule
cannot express them. They remain unlinked, which is honest rather than wrong,
and is tracked as an open item.
