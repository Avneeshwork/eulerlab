"""The metrics library (`docs/METRICS/`, ADR-103) as code, and the parts that keep it current (ADR-104).

- `catalog`: the pages, read from disk, and lookup by id or words.
- `normals`: "what is normal" recomputed from held data, for the assistant and the keeper.
- `regwatch`: SEBI, RBI and NSE feeds landed daily and diffed for new circulars.
- `gaps`: what the library is missing or has let go stale.
"""
