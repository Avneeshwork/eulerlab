"""Daily strategies, one file per strategy, grouped by where they came from.

- `published` — the ten classic factors from the literature (docs/RESEARCH/017).
- `india_papers` — rules from papers on Indian equities (`research/papers/`).
- `evidence` — momentum and reversal refinements with published evidence.
- `github` — daily rules from public GitHub repositories (research 113).
- `events` — earnings-event strategies on NSE's dated announcements.
- `screener` — the stock screener's long-term and swing models (ADR-136).

Each family is a package: `common.py` holds what its strategies share, every
other file is one strategy (its rule and its library entry), and `__init__.py`
lists them in library order. `published.BUILDERS` is the table of every daily
builder, which the registry and the batch runner read (ADR-219).
"""
