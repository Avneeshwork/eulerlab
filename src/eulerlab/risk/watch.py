"""Watch levels for the Risk screen: they warn, they do not act (ADR-071)."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

PATH = Path("config/risk_watch.yaml")


class WatchLevels(BaseModel):
    """Read from `config/risk_watch.yaml`, which the operator owns."""

    model_config = ConfigDict(extra="forbid")

    book_var_pct: float = Field(default=2.0, gt=0, le=100)
    book_drawdown_pct: float = Field(default=10.0, gt=0, le=100)
    deployment_drawdown_pct: float = Field(default=8.0, gt=0, le=100)
    sector_pct: float = Field(default=35.0, gt=0, le=100)


def load(path: Path = PATH) -> WatchLevels:
    """The levels in the file, or the defaults when there is no file."""
    if not path.exists():
        return WatchLevels()
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return WatchLevels.model_validate(raw)
