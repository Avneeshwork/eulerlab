# ADR-122: The nightly US step fetches from the first of last month and keeps first knowledge times

- **Context:** `make daily` fetched S&P 500 bars and actions from 2016 every night. With the US tree pruned after each upload, that rewrote ~37,500 files with new `knowledge_time`s and re-uploaded most of them; the run took about 7 hours and its upload did not finish (HISTORY #63).
- **Options:** (a) Keep 2016 and skip the upload of unchanged rows. (b) Fetch a short window and merge into the B2 copy. (c) (b) and keep the first `knowledge_time` of a bar that has not changed.
- **Choice:** (c). Window: the first of last month, so a revision Alpaca makes within a few weeks is still picked up. A pruned month is restored from B2 before merging; one that cannot be fetched is not written.
- **Why:** About 1,000 files a night instead of 37,500, and an unchanged file keeps its size, so the mirror skips it. Restamping a bar we already held was also a point-in-time error.
- **Cost if wrong:** A revision Alpaca makes to a bar older than about five weeks is not picked up by the nightly run. `make us-bars FROM=2016-01-01` refetches everything on demand.
