"""Moved to `eulerlab.strategies.daily.github` (ADR-219).

This module only keeps the old import path working for code written before the
move. New code imports from the new path.
"""

from eulerlab.strategies.daily.github import *  # noqa: F403
from eulerlab.strategies.daily.github import __all__ as __all__
