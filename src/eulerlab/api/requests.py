"""The request shapes and the vocabulary they are described in.

`BatchRunRequest` lived in `api/server`, and `api/intraday_runs` needs it — so
extracting the runner would have meant importing the transport module from the
module it was extracted out of, which is a cycle rather than a layering.

Request models are not transport. They are the shape of a question someone can
ask this platform, and both the thing that parses it and the thing that answers
it are entitled to know it.
"""

from __future__ import annotations

from datetime import date
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
    """How far back to run, when no explicit dates are given.

    Kept because most runs want "the last N days" and computing two dates for
    that is friction. `start`/`end` win where both are supplied."""

    start: str = ""
    end: str = ""
    """An explicit window, ISO dates, overriding `days` when both are set.

    `days` alone cannot ask "how did this behave in 2022" — it always ends
    today, so every question is about the recent past. A window that ends in the
    past is how a regime gets tested, and it was unaskable."""

    starting_cash: float = Field(default=1_000_000.0, gt=0)
    """The account the run is sized against.

    Position sizing here is a fraction of equity, so this is not cosmetic: it
    scales every position and therefore every percentage-based cost. It also
    decides whether a capped fee binds — INDmoney's $25 cap is the difference
    between US intraday working and not, and on a small enough account the cap
    never binds at all."""
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


def window_of(request: BatchRunRequest) -> tuple[date | None, date | None]:
    """The explicit window, or `(None, None)` to mean "the last `days` days".

    Both dates or neither. One alone is ambiguous — a start with no end could
    mean "from then until today" or "from then for `days`" — and guessing which
    would silently answer a different question than the one asked.
    """
    if not request.start or not request.end:
        return None, None
    try:
        return date.fromisoformat(request.start), date.fromisoformat(request.end)
    except ValueError:
        # A malformed date falls back to the day count rather than failing the
        # run: the operator gets a result over a window they can see, not a 422.
        return None, None


def universe_label(request: BatchRunRequest) -> str:
    """What to record as the universe. `custom` when instruments were picked."""
    return CUSTOM_UNIVERSE if request.instruments else request.universe


class PruneRequest(BaseModel):
    """Delete local landing files that B2 confirms it holds.

    `dry_run` defaults to True: the button asks first, shows how many files and
    how much disk, and only a second, confirmed call deletes.
    """

    model_config = ConfigDict(extra="forbid")

    dry_run: bool = True


class FeedRequest(BaseModel):
    """Which feed steps to run. Empty `only` runs every step.

    One dataset's Update button sends its own steps and `mirror=False`: the
    mirror relists the whole bucket and takes minutes, which is right for
    Update all data and wrong for refreshing one table.
    """

    model_config = ConfigDict(extra="forbid")

    only: list[str] = Field(default_factory=list)
    mirror: bool = True
