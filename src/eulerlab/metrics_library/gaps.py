"""What the metrics library is missing or has let go stale (ADR-104).

Four checks, each pure over what it is handed:

- `overdue`: rows of `docs/ASSUMPTIONS.md` whose recheck date has passed.
- `stale_pages`: pages whose written "what is normal" line is older than a limit.
- `uncovered`: sections of a live payload that no page is mapped to.
- `asked_without_page`: lookups the assistant made that found no page, counted.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from eulerlab.metrics_library.catalog import Page

ASSUMPTIONS = Path("docs/ASSUMPTIONS.md")
ROW = re.compile(r"^\|\s*(A-\d{3})\s*\|(.*)\|\s*$")
DATE = re.compile(r"(\d{4}-\d{2}-\d{2})")


@dataclass(frozen=True)
class Overdue:
    id: str
    claim: str
    recheck: str


def overdue(text: str, today: date) -> list[Overdue]:
    """Assumptions whose last column names a date before today. Struck-out rows are skipped."""
    out: list[Overdue] = []
    for line in text.splitlines():
        found = ROW.match(line)
        if not found:
            continue
        cells = [c.strip() for c in found.group(2).split("|")]
        if not cells or cells[0].startswith("~~"):
            continue
        dates = DATE.findall(cells[-1])
        if dates and date.fromisoformat(dates[0]) < today:
            out.append(Overdue(found.group(1), cells[0][:160], dates[0]))
    return out


def stale_pages(pages: Iterable[Page], today: date, max_days: int) -> list[Page]:
    out = []
    for page in pages:
        if page.as_of and (today - date.fromisoformat(page.as_of)).days > max_days:
            out.append(page)
    return out


def uncovered(payload: Mapping[str, Any], mapped: Mapping[str, str], known: set[str]) -> list[str]:
    """Top-level sections of a payload with no page mapped, or mapped to a page that does not exist."""
    out = []
    for section in sorted(payload):
        if section in ("ok", "error"):
            continue
        page = mapped.get(section)
        if page is None:
            out.append(f"{section}: no page mapped")
        elif page != "-" and page not in known:
            out.append(f"{section}: mapped to {page}, which has no page")
    return out


def asked_without_page(rows: Sequence[Mapping[str, Any]], since: str) -> list[tuple[str, int]]:
    """Queries with no page since `since` (ISO), most asked first."""
    counts: Counter[str] = Counter(
        str(r["query"]).strip().lower() for r in rows if str(r.get("knowledge_time", "")) >= since
    )
    return counts.most_common()
