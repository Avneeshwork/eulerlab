"""How one instrument becomes another — and why that is three things, not one.

Sprint 1 nearly shipped a single flat alias map. It would have been wrong in
two different directions at once, because "X became Y" covers three distinct
relationships that must not be collapsed:

**Rename** — same legal entity, same ISIN, new ticker. ZOMATO became ETERNAL.
Safe to alias for *data*: the price series is continuous, and fetching under
the new name returns the same instrument's history.

**Merger** — a *different* entity absorbed this one, and shareholders were paid
in the acquirer's stock at a ratio. HDFC Ltd merged into HDFC Bank on
2023-07-01 at 42 HDFC Bank shares per 25 HDFC Ltd shares.

  **A merger must never be treated as a data alias.** HDFC Ltd and HDFC Bank
  were two separately listed companies with two separate price series. Fetching
  HDFCBANK to fill a gap labelled HDFC does not recover HDFC Ltd's history — it
  silently substitutes a different company's prices, and nothing downstream
  would flag it. The pre-merger series simply ends.

  It *is* needed for portfolio continuity: a position in HDFC on the record
  date became 1.68x that many HDFC Bank shares, and a backtest that ignores
  this either loses the position or misprices it.

**Demerger** — one entity split into several, each with its own ISIN and its
own ratio. One-to-many, so an alias cannot express it at all.

The ratio is the field that makes the distinction operational: a rename has no
ratio because nothing was exchanged; a merger and a demerger both do.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from fractions import Fraction


class SuccessionKind(StrEnum):
    RENAME = "rename"
    """Same entity, same ISIN. The price series continues unbroken."""

    MERGER = "merger"
    """Absorbed by a different entity. The price series ENDS here."""

    DEMERGER = "demerger"
    """Split into several entities. The price series ends and several begin."""


@dataclass(frozen=True)
class Succession:
    """One instrument becoming another, with the terms."""

    predecessor: str
    successor: str
    kind: SuccessionKind
    effective: date
    ratio: Fraction | None = None
    """Successor shares received per predecessor share.

    None for a rename, where nothing is exchanged. Required for a merger or
    demerger — without it a position cannot be carried across the event.
    """

    source: str = ""
    """Where the terms came from. These are facts about the world and need a
    citation, per the project's truth rules."""

    def __post_init__(self) -> None:
        needs_ratio = self.kind in (SuccessionKind.MERGER, SuccessionKind.DEMERGER)
        if needs_ratio and self.ratio is None:
            msg = f"{self.kind} {self.predecessor}->{self.successor} needs a ratio"
            raise ValueError(msg)
        if self.kind is SuccessionKind.RENAME and self.ratio is not None:
            msg = "a rename exchanges nothing, so it must not carry a ratio"
            raise ValueError(msg)

    @property
    def continues_price_series(self) -> bool:
        """Whether the successor's history may be read as this instrument's.

        True only for a rename. This is the property that decides whether a
        symbol may be substituted when fetching data, and getting it wrong
        substitutes another company's prices without any error.
        """
        return self.kind is SuccessionKind.RENAME

    def convert_quantity(self, shares: float) -> float:
        """Shares held after the event, for carrying a position across it."""
        if self.ratio is None:
            return shares
        return shares * float(self.ratio)


# Verified against primary reporting, 2026-08-19. These are corporate-action
# facts about the world, so each carries its source per the project's rules.
KNOWN_SUCCESSIONS: tuple[Succession, ...] = (
    Succession(
        predecessor="HDFC",
        successor="HDFCBANK",
        kind=SuccessionKind.MERGER,
        effective=date(2023, 7, 1),
        ratio=Fraction(42, 25),
        source="HDFC Bank press release; record date 2023-07-13, 42 shares per 25",
    ),
    Succession(
        predecessor="IDFC",
        successor="IDFCFIRSTB",
        kind=SuccessionKind.MERGER,
        effective=date(2024, 10, 1),
        ratio=Fraction(155, 100),
        source="IDFC FIRST Bank merger disclosure; NCLT order 2024-09-25, 155 per 100",
    ),
)
