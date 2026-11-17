"""Moved to `eulerlab.risk.limits.loss_limits` (ADR-219).

This module only keeps the old import path working for code written before the
move. New code imports from the new path.
"""

from eulerlab.risk.limits.loss_limits import *  # noqa: F403
from eulerlab.risk.limits.loss_limits import __all__ as __all__
