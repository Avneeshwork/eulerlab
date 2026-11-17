"""Intraday signals, one file per signal (ADR-219).

- `papers` — minute-bar signals coded from published papers (US-tested).
- `india` — the signals that cleared the bar, re-declared for NSE.
- `crypto` — minute-level crypto signals.

Each family is a package: `common.py` holds what its signals share, every other
file is one signal, and `__init__.py` lists them in library order.
"""
