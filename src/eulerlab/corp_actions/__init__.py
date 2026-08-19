"""Corporate actions: dividends, bonuses, splits and rights, and the
adjustment factors that make a raw price series comparable across them.

See `docs/RESEARCH/008-nse-corporate-actions-feed.md` for the source, and
`docs/DECISIONS/ADR-016-corporate-action-knowledge-time.md` for why every
action's knowledge_time is conservatively its ex-date rather than an
announcement date the feed does not provide.
"""
