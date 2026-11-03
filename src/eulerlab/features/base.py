"""What a feature is: a named pure function of one symbol's own history (ADR-127).

Kept apart from `library.py` so a signal the engineering agent coded
(`features/coded/<name>.py`) can import `Feature` without importing the
library, which itself loads the coded signals: importing a coded signal first
would otherwise find it half-loaded and skip it.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from eulerlab.features.panel import PanelRow

FeatureFn = Callable[[Sequence[PanelRow]], float | None]

TRADING_DAYS_PER_MONTH = 21
"""Approximately. Used only for lookback lengths, where being a day out
changes nothing; never for annualising, where it would."""


@dataclass(frozen=True)
class Feature:
    name: str
    fn: FeatureFn
    description: str
    min_history: int

    def __call__(self, history: Sequence[PanelRow]) -> float | None:
        if len(history) < self.min_history:
            return None
        return self.fn(history)
