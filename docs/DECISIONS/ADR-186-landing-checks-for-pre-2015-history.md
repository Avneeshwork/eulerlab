# ADR-186 — Older index names accepted, and check-landing lists B2 per segment

**Date:** 2026-11-14. **Status:** accepted. Research 194.

- **Context.** The 2000-2014 backfill landed NSE daily files back to 2000 (research 194). Two checks broke on it: the index file check rejected 2012 and early 2013, whose Nifty is named "S&P CNX Nifty", and `make check-landing` listed the whole `nse/` prefix inside one 15-second deadline, which no longer finishes now that the bucket also holds minute bars and every other dataset. It reported INTEGRITY UNVERIFIED on every run.
- **Options.** (a) Raise the deadline. (b) List only the landing's own segment folders, each with its own deadline, and only when a file is absent locally.
- **Choice.** (b), with 60 s a segment. The index check also accepts "S&P CNX Nifty", and `canonical_index` drops a leading "S&P " so "S&P CNX Nifty" becomes "Nifty 50", one series with today's name.
- **Why.** The landing's 24,695 files sit in six folders; listing them takes about 20 s. Raising one deadline would break again as the bucket grows.
- **Cost if wrong.** A segment folder outside the manifest would not be listed, but such a file is not one the check is meant to vouch for.
