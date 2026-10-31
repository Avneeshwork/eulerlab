"""The pages of `docs/METRICS/`, read from disk, and lookup by id, name or words.

A page is one Markdown file `docs/METRICS/<family>/<id>.md` with a `# Name`
heading and an "**In one line:**" line. Nothing else is parsed: the page is
returned as written, so what a model reads is exactly what the operator reads.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from eulerlab.agents import knowledge_index

ROOT = Path("docs/METRICS")
MISSES = Path("data/derived/metric_misses.jsonl")
"""Lookups that found no page: the keeper reads them as candidate pages (ADR-104)."""

ONE_LINE = re.compile(r"^\*\*In one line:\*\*\s*(.+)$", re.MULTILINE)
AS_OF = re.compile(r"What is normal \(our data, as of (\d{4}-\d{2}-\d{2})\)")


@dataclass(frozen=True)
class Page:
    id: str
    family: str
    name: str
    one_line: str
    path: str
    text: str

    @property
    def as_of(self) -> str:
        """The date its written "what is normal" line was computed, or ''."""
        found = AS_OF.search(self.text)
        return found.group(1) if found else ""


def pages(root: Path = ROOT) -> list[Page]:
    out: list[Page] = []
    if not root.is_dir():
        return out
    for path in sorted(root.glob("*/*.md")):
        text = path.read_text(encoding="utf-8")
        heading = next(
            (ln[2:].strip() for ln in text.splitlines() if ln.startswith("# ")), path.stem
        )
        line = ONE_LINE.search(text)
        out.append(
            Page(
                id=path.stem,
                family=path.parent.name,
                name=heading,
                one_line=line.group(1).strip() if line else "",
                path=str(path),
                text=text,
            )
        )
    return out


def find(query: str, root: Path = ROOT, limit: int = 3) -> list[Page]:
    """Exact id first, then a name containing the query, then BM25 over the pages."""
    every = pages(root)
    wanted = query.strip().lower()
    if not wanted:
        return []
    exact = [p for p in every if p.id == wanted.replace(" ", "-")]
    if exact:
        return exact
    named = [p for p in every if wanted in p.name.lower()]
    if named:
        return named[:limit]
    entries = [knowledge_index.Entry("metric", p.path, p.name, p.text, 0.0) for p in every]
    hits = knowledge_index.search(query, entries, limit=limit)
    by_path = {p.path: p for p in every}
    return [by_path[h["path"]] for h in hits if h["path"] in by_path]


def record_miss(query: str, path: Path | None = None, now: datetime | None = None) -> None:
    """Append a lookup that found nothing. Best effort: never fails the caller."""
    path = path or MISSES
    at = (now or datetime.now(UTC)).isoformat(timespec="seconds")
    row: dict[str, Any] = {"query": query.strip()[:200], "event_time": at, "knowledge_time": at}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row) + "\n")
    except OSError:
        return


def misses(path: Path | None = None) -> list[dict[str, Any]]:
    path = path or MISSES
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("query"):
            out.append(row)
    return out
