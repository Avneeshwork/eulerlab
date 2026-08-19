"""A universe list may only be used on periods it could have been known for.

`config/universe_top250.txt` is the top 250 NSE equities by turnover **as of
2024-09-17**. Running a 2015 backtest against it is the textbook survivorship
error: the list is exactly the set of companies that were still liquid and
still listed nine years later, so every name in it has already passed a
survival test that no 2015 investor could have applied.

The bias is large and it flatters. Companies that were delisted, acquired at a
discount, or simply faded out of liquidity are absent, and those are
disproportionately the losers. The backtest then reports the return of holding
only the winners.

The file already records its own `as_of`. What was missing is anything that
refuses to hand it over for the wrong period, which is the same problem the
read API had: a convention that every call site is trusted to honour is not a
guard. `LookaheadError` is raised rather than the list silently filtered,
because a universe that cannot legitimately be used is a bug in the caller.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from eulerlab.bitemporal.store import LookaheadError

_AS_OF = re.compile(r"^#\s*as_of:\s*(\d{4}-\d{2}-\d{2})\s*$")


@dataclass(frozen=True)
class Universe:
    """A symbol list that knows the date it was computed for."""

    symbols: tuple[str, ...]
    as_of: date
    path: Path

    def __len__(self) -> int:
        return len(self.symbols)

    def usable_at(self, when: date) -> bool:
        """Whether this list could have been known at `when`."""
        return self.as_of <= when


def read_universe(path: Path, *, as_of: date) -> Universe:
    """Load a universe, refusing it if it post-dates `as_of`.

    `as_of` is required and keyword-only for the same reason it is on the read
    API: the safe call must not be the longer one.
    """
    text = path.read_text(encoding="utf-8")
    stamped: date | None = None
    symbols: list[str] = []
    for line in text.splitlines():
        if match := _AS_OF.match(line):
            stamped = date.fromisoformat(match.group(1))
        elif (clean := line.strip()) and not clean.startswith("#"):
            symbols.append(clean)

    if stamped is None:
        # An undated list cannot be checked, and an uncheckable list is worse
        # than a wrong one because it looks fine.
        msg = f"{path} has no '# as_of:' header, so its survivorship cannot be checked"
        raise LookaheadError(msg)

    universe = Universe(symbols=tuple(symbols), as_of=stamped, path=path)
    if not universe.usable_at(as_of):
        msg = (
            f"{path.name} was computed as of {stamped} and cannot be used for "
            f"{as_of}: it contains only names that survived until {stamped}. "
            f"Rebuild it as of {as_of} with eulerlab.record.universe."
        )
        raise LookaheadError(msg)
    return universe
