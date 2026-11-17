"""Exposure by name and by sector."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from eulerlab.risk.book.holdings import Book

# --- exposure -----------------------------------------------------------------------


def by_name(books: Sequence[Book]) -> list[dict[str, Any]]:
    """Every name held, added up across deployments, largest first."""
    totals: dict[str, dict[str, Any]] = {}
    for book in books:
        for holding in book.holdings:
            row = totals.setdefault(
                holding.symbol, {"symbol": holding.symbol, "value": 0.0, "held_by": []}
            )
            row["value"] += holding.value
            row["held_by"].append(book.id)
    return sorted(totals.values(), key=lambda r: (-abs(r["value"]), r["symbol"]))


def by_sector(
    names: Sequence[Mapping[str, Any]], sectors: Mapping[str, str]
) -> list[dict[str, Any]]:
    totals: dict[str, float] = {}
    for row in names:
        sector = sectors.get(row["symbol"]) or "Unclassified"
        totals[sector] = totals.get(sector, 0.0) + abs(row["value"])
    invested = sum(totals.values())
    return [
        {
            "sector": sector,
            "value": round(value, 2),
            "share": round(value / invested, 6) if invested else 0.0,
        }
        for sector, value in sorted(totals.items(), key=lambda item: (-item[1], item[0]))
    ]
