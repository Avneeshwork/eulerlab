"""The agent network: one runtime, eight agents, and the operator in charge (ADR-085).

Every agent is the same four parts — a definition in `config/agents/`, a
worker module in `agents/workers/`, the operator's brief, and an entry in the
hash-chained agent log — so adding one is a file and a module, not plumbing.

The rule the whole package is built around: language models read, draft and
explain; code decides; the gate judges; the operator approves anything that
spends a trial or money. No agent imports the order path, the gate or the
trial ledger's writer, and a test reads every worker's imports to prove it
(`agents/boundaries.py`).
"""
