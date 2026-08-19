"""Data quality engine: what is wrong with the data we collected.

`make quality` runs every check and prints counts by severity. Findings that
are already understood are suppressed by name against their `docs/STUBS.md`
entry, never by widening a threshold — see `findings.py` for why.
"""
