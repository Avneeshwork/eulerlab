# ADR-080: Market context on the dashboard

- **Context:** the dashboard showed the session, the map and movers, but none of what StockEdge, Finviz and Sensibull lead with (research 120): index trend and valuation, breadth over weeks, sector strength, F&O positioning. EulerLab already lands every input.
- **Options:** (a) add the figures to `/api/snapshot`; (b) a separate `/api/market-context` the page fetches beside it; (c) a composite "mood" score like Tickertape's.
- **Choice:** (b), with each section able to fail on its own, and no composite score. Sector phase uses our own stated rule, not a Relative Rotation Graph.
- **Why:** the snapshot is the first paint and must not wait 3 s for the breadth grid or a bucket read of participant files. A mood score adds a number with no published method and no evidence. The RRG's smoothing is proprietary, so a copy would be a guess presented as the standard.
- **Cost if wrong:** one more request per dashboard visit; if traders want the RRG picture itself, the sector table needs a second calculation, licensed or reverse-engineered.
