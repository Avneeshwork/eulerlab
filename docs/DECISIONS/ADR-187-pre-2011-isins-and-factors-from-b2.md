# ADR-187 — ISINs for pre-2011 rows by a checked chain, and factors read from B2

**Date:** 2026-11-14. **Status:** accepted for a copy; swapping it into the live panel is the operator's decision. Research 195.

- **Context.** NSE's cash bhavcopy has no ISIN column before late 2011, and every join here is on the ISIN-derived `InstrumentId`. The first rebuild from 2000 wrote rows with an empty ISIN. Separately, `build-factors` globbed the local disk for corporate actions; with every file pruned to B2 it loaded none and wrote both factor files empty (HISTORY, 2026-11-14).
- **Options.** (a) Join old rows to today's master by ticker. (b) Anchor each symbol on its first ISIN-bearing day and walk NSE's own `symbolchange.csv` back from there, leaving out anything ambiguous. (c) Leave pre-2011 rows out of the panel.
- **Choice.** (b), in `master/legacy_isin.py`: a row is mapped only if its symbol chain reaches an anchor with one ISIN, trades with no gap over 60 sessions (A-144), is not taken over by another company's change, and no other symbol maps to the same ISIN that day. Everything else is left out and counted. `build-factors` now reads corporate-action files from the manifest, through `landing_reader` (disk, else B2), refuses to write when it finds none, and takes `--out` so a rebuild can go to a copy.
- **Why.** A ticker join silently merges a renamed or reused symbol into the wrong company. NSE's change list is the exchange's own record, and every rule can be tested.
- **Cost if wrong.** Companies delisted before late 2011 never reach an anchor, so the old years are survivorship-biased. Dividends before late 2011 cannot be priced (the close lookup is by ISIN), so total-return factors miss them; splits and bonuses need no price and are adjusted.
