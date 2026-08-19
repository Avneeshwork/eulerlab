"""Symbol-change map, derived from the registry rather than hand-written.

A hand-written alias map was nearly shipped in Sprint 1 and was wrong on its
first entry: `PEL` was matched to `PPLPHARMA` by name similarity, but Piramal
demerged into two entities and no one-to-one alias can express that. This
module derives the map from observed ISIN continuity instead, so a rename is
only asserted when the same issuer actually traded under both names.

Renames and unresolved instruments are kept apart on purpose. An unresolved
symbol is a real gap in coverage; silently mapping it to a plausible-looking
successor would turn a visible gap into invisible wrong data.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from eulerlab.master.registry import Registry


@dataclass(frozen=True)
class Rename:
    """One ticker becoming another, with the same issuer on both sides."""

    old: str
    new: str
    changed_between: tuple[date, date]
    """The rename happened somewhere in this window.

    Bracketed by the two observations either side of the change, because daily
    files show the new name appearing, never the change itself.
    """


@dataclass
class SymbolMap:
    renames: list[Rename] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    """Symbols with no current successor: delisted, merged away, or demerged.

    Deliberately not guessed at. A demerger's successors have different ISIN
    issuer prefixes, so continuity cannot be established from the data alone.
    """

    def current_name(self, ticker: str) -> str | None:
        for rename in self.renames:
            if rename.old == ticker:
                return rename.new
        return None

    def to_json(self) -> str:
        return json.dumps(
            {
                "renames": [
                    {
                        "old": r.old,
                        "new": r.new,
                        "changed_after": r.changed_between[0].isoformat(),
                        "changed_by": r.changed_between[1].isoformat(),
                    }
                    for r in sorted(self.renames, key=lambda r: r.old)
                ],
                "unresolved": sorted(self.unresolved),
                "note": (
                    "Derived from ISIN continuity in the security master, not "
                    "hand-written. 'unresolved' means no successor could be "
                    "established from the data - usually a delisting or a "
                    "demerger, which is one-to-many and cannot be an alias."
                ),
            },
            indent=2,
        )

    @classmethod
    def from_json(cls, text: str) -> SymbolMap:
        raw = json.loads(text)
        return cls(
            renames=[
                Rename(
                    old=r["old"],
                    new=r["new"],
                    changed_between=(
                        date.fromisoformat(r["changed_after"]),
                        date.fromisoformat(r["changed_by"]),
                    ),
                )
                for r in raw.get("renames", [])
            ],
            unresolved=list(raw.get("unresolved", [])),
        )


def build_symbol_map(registry: Registry, as_of: date) -> SymbolMap:
    """Every ticker that changed, and what it is called on `as_of`."""
    renames: list[Rename] = []
    for instrument in registry.renamed():
        versions = instrument.tickers.versions()
        current = instrument.ticker_at(as_of)
        if current is None:
            continue
        for previous in versions[:-1]:
            if previous.value == current or previous.valid_to is None:
                continue
            renames.append(
                Rename(
                    old=previous.value,
                    new=current,
                    changed_between=(previous.valid_from, previous.valid_to),
                )
            )
    return SymbolMap(renames=renames)


def save(symbol_map: SymbolMap, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(symbol_map.to_json(), encoding="utf-8")


def load(path: Path) -> SymbolMap:
    return SymbolMap.from_json(path.read_text(encoding="utf-8"))
