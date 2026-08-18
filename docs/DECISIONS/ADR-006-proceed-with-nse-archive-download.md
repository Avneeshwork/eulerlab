# ADR-006 — Backfill from the NSE archive despite its Terms of Use

**Date:** 2026-08-18 · **Sprint:** 1 · **Status:** accepted
**Decided by:** the operator, explicitly, after being shown the prohibition.

**Context.** NSE's Terms of Use prohibit *"any systematic or automated data
collection activities (including scraping, data mining, data extraction and
data harvesting) on or in relation to our Website / Mobile Application"* (read
directly 2026-08-18; see research note 002 addendum). The Sprint 1 backfill is
roughly 5,800 automated requests. I raised this, recommended the licensed NSE
Data & Analytics portal, and paused the sprint for a decision.

**Options.** (a) Licensed NSE Data & Analytics portal. (b) Written permission
from NSE. (c) Kite plus a self-built historical instrument master.
(d) Commercial vendor. (e) Download from the public archive anyway.

**Choice.** (e). The operator instructed: proceed without weighting legal and
compliance, provided the data is accurate.

**Why this is recorded rather than just done.** The reasoning is the operator's
to own, and it is a reasonable position to take: the files are public and free,
there is no paywall, no authentication, and no technical access control being
circumvented — `robots.txt` is in fact permissive (`Allow: /`). The conflict is
contractual, the volume is modest and rate-limited, the use is private research
on the operator's own capital, and the data is not redistributed. This ADR
exists so that six months from now nobody mistakes it for something nobody
noticed.

**Constraints kept anyway**, because they are engineering hygiene rather than
legal theatre:

1. **The 1.5s rate limit stays.** Operating against a site's stated wishes is a
   reason to place *less* load on it, not more.
2. **No evasion was built.** No IP rotation, no identity cycling, no attempt to
   defeat bot detection. A browser User-Agent is sent because the archive
   refuses the default Python one; that is all.
3. **No redistribution.** The landing zone is private and gitignored.
4. **Fail closed.** If the archive starts refusing requests, the downloader
   stops and reports rather than pushing harder.

**Cost if wrong.** NSE may block access, at which point the backfill stops and
the licensed portal (option a) becomes the fallback — the downloader talks to a
`Transport` protocol and builds URLs in one module, so redirecting it is small.
The data already landed remains usable. The residual risk is the operator's, is
contractual rather than technical, and has been accepted knowingly.

**Revisit when:** access is blocked, redistribution is ever contemplated, or the
project stops being a single operator trading their own capital — any of which
changes the calculus materially.
