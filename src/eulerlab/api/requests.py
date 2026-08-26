"""The request shapes and the vocabulary they are described in.

`BatchRunRequest` lived in `api/server`, and `api/intraday_runs` needs it — so
extracting the runner would have meant importing the transport module from the
module it was extracted out of, which is a cycle rather than a layering.

Request models are not transport. They are the shape of a question someone can
ask this platform, and both the thing that parses it and the thing that answers
it are entitled to know it.
"""

from __future__ import annotations

from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

from eulerlab.strategies import AssetClass

IST = ZoneInfo("Asia/Kolkata")
"""Market time. The intraday window is defined in the market's day, not the
server's."""

ALL_INSTRUMENTS = "all"
"""Every symbol in the panel."""

CUSTOM_UNIVERSE = "custom"
"""Recorded when instruments were hand-picked rather than taken from a batch."""


class BatchRunRequest(BaseModel):
    """A batch of screening runs."""

    model_config = ConfigDict(extra="forbid")

    strategies: list[str] = Field(default_factory=list)
    days: int = Field(default=800, ge=60, le=3000)
    tier: Literal["A", "B"] = "B"
    universe: str = ALL_INSTRUMENTS
    """Which instruments the strategy may choose from. Part of the cache key
    and of the stored result's configuration, because the same strategy over
    nifty50 and over the whole panel are two different answers."""

    asset_class: str = AssetClass.EQUITY.value
    """Which panel to run against.

    Explicit rather than inferred, because a universe run has no instruments to
    infer from. Mixing classes in one run is refused: a cross-section that ranks
    a Binance pair against a mutual fund NAV is comparing series with different
    calendars, different cost treatment and no shared notion of a trading day.
    """

    instruments: list[str] = Field(default_factory=list)
    """A hand-picked list, which overrides `universe` when non-empty.

    Batches are a convenience, not the only way in: a question like "does this
    work on these eleven banks" is a legitimate backtest and was previously
    unaskable.
    """

    use_cache: bool = True
    workspace: str = ""
    """Which tenant's results this run belongs to. Empty means the default
    single-operator workspace (ADR-040)."""


def universe_label(request: BatchRunRequest) -> str:
    """What to record as the universe. `custom` when instruments were picked."""
    return CUSTOM_UNIVERSE if request.instruments else request.universe
