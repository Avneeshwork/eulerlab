"""The sizing rules' names and the risk window every model reads (ADR-122)."""

from __future__ import annotations

from typing import Final, Literal, get_args

import numpy as np
import numpy.typing as npt

Sizing = Literal["equal", "strategy", "inverse_vol", "hrp", "min_variance"]
RULES: Final[tuple[str, ...]] = get_args(Sizing)
MODELS: Final[frozenset[str]] = frozenset({"inverse_vol", "hrp", "min_variance"})

WINDOW: Final = 126
"""Trading days of daily returns behind every risk estimate (six months)."""
MIN_DAYS: Final = 60
"""Fewer common return days than this and a model falls back to equal."""
HISTORY_NEEDED: Final = WINDOW + 1
"""Rows a strategy's `lookback` must give a model: `WINDOW` returns need one more close."""

Matrix = npt.NDArray[np.float64]
