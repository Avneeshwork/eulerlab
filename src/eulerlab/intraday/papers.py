"""Moved to `eulerlab.strategies.intraday.papers` (ADR-219).

This module only keeps the old import path working for code written before the
move. New code imports from the new path.
"""

from eulerlab.strategies.intraday.papers import *  # noqa: F403
from eulerlab.strategies.intraday.papers import __all__ as __all__
