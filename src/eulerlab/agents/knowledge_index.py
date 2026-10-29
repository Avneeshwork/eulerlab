"""One searchable index of everything the platform knows: papers, cards, decisions, results, data.

`data/agents/knowledge/index.json`. Rebuilt when any source file is newer
than the index, so a paper added at noon is searchable at noon. Small: a few
hundred entries of title, path and the first 1,500 characters.

Search is plain term scoring (BM25 with the usual constants), no embeddings
and no new dependency. The knowledge agent does not need semantic recall to be
precise; it needs to find the file and then read it, and quote what it read.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

from eulerlab.agents.spec import home

SOURCES: tuple[tuple[str, str, str], ...] = (
    ("paper", "research/papers", "*.yaml"),
    ("hypothesis", "hypotheses", "*.yaml"),
    ("research note", "docs/RESEARCH", "*.md"),
    ("decision", "docs/DECISIONS", "*.md"),
    ("runbook", "docs/RUNBOOKS", "*.md"),
    ("record", "docs", "HISTORY.md"),
    ("record", "docs", "ARCHITECTURE.md"),
    ("record", "docs", "ASSUMPTIONS.md"),
    ("record", "docs", "STUBS.md"),
    ("record", ".", "STATE.md"),
)
EXTRA = (Path("data/quality/grades.json"),)
SNIPPET = 1500
WORD = re.compile(r"[a-z0-9][a-z0-9_\-]{1,}")
STOP = frozenset(
    [
        "the",
        "and",
        "for",
        "with",
        "that",
        "this",
        "from",
        "are",
        "was",
        "were",
        "has",
        "have",
        "not",
        "but",
        "its",
        "their",
        "into",
        "over",
        "than",
        "then",
        "they",
        "them",
        "our",
        "you",
        "any",
        "can",
        "all",
        "one",
        "two",
        "out",
        "per",
    ]
)


@dataclass(frozen=True)
class Entry:
    kind: str
    path: str
    title: str
    text: str
    mtime: float


def _files(base: Path) -> Iterable[tuple[str, Path]]:
    for kind, folder, pattern in SOURCES:
        directory = base / folder
        if directory.is_dir():
            for path in sorted(directory.glob(pattern)):
                yield kind, path


def _title(kind: str, path: Path, text: str) -> str:
    if path.suffix == ".yaml":
        try:
            spec = yaml.safe_load(text) or {}
        except yaml.YAMLError:
            spec = {}
        if isinstance(spec, dict):
            ident = str(spec.get("id") or path.stem)
            title = str(spec.get("title") or "")
            status = str(spec.get("status") or "")
            return f"{ident}: {title}" + (f" ({status})" if status else "")
    for line in text.splitlines():
        if line.startswith("#"):
            return line.lstrip("# ").strip()[:160]
    return path.stem


def _entry(kind: str, path: Path, base: Path) -> Entry:
    text = path.read_text(encoding="utf-8", errors="replace")
    relative = str(path.relative_to(base)) if path.is_relative_to(base) else str(path)
    return Entry(kind, relative, _title(kind, path, text), text[:SNIPPET], path.stat().st_mtime)


def _grade_entries(base: Path) -> list[Entry]:
    out: list[Entry] = []
    for path in EXTRA:
        full = base / path
        if not full.exists():
            continue
        try:
            grades = json.loads(full.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        for g in grades if isinstance(grades, list) else []:
            checks = "; ".join(
                f"{c['name']} {c['state']}: {c['detail']}" for c in g.get("checks", [])
            )
            out.append(
                Entry(
                    "dataset",
                    str(path),
                    f"{g.get('name')}: grade {g.get('grade')}, freshness {g.get('freshness')}",
                    checks[:SNIPPET],
                    full.stat().st_mtime,
                )
            )
    return out


def _quantpedia_entries(base: Path) -> list[Entry]:
    from eulerlab.research import quantpedia

    out: list[Entry] = []
    for e in quantpedia.catalogue(base / quantpedia.LANDING):
        text = (
            f"{e['description']}\nkeywords: {e['keywords']}\nmarkets: {e['markets']}\n"
            f"Sharpe in the paper: {e['sharpe_paper']}; recalculated: {e['sharpe_recalculated']}\n"
            f"paper: {e['paper']}\n{e['abstract']}"
        )
        path = Path(e["path"])
        out.append(
            Entry(
                "quantpedia",
                str(path.relative_to(base)) if path.is_relative_to(base) else str(path),
                f"Quantpedia {e['id']}: {e['name']}",
                text[:SNIPPET],
                path.stat().st_mtime,
            )
        )
    return out


def _index_path(root: Path) -> Path:
    return root / "knowledge" / "index.json"


def newest_source(base: Path = Path()) -> float:
    stamps = [p.stat().st_mtime for _, p in _files(base)]
    stamps += [(base / p).stat().st_mtime for p in EXTRA if (base / p).exists()]
    stamps += [
        p.stat().st_mtime for p in (base / "data/landing/quantpedia").glob("*/strategy/*.json")
    ]
    return max(stamps, default=0.0)


def build(base: Path = Path(), root: Path | None = None) -> list[Entry]:
    root = home(root)
    entries = (
        [_entry(kind, path, base) for kind, path in _files(base)]
        + _grade_entries(base)
        + _quantpedia_entries(base)
    )
    target = _index_path(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps([asdict(e) for e in entries]), encoding="utf-8")
    return entries


def load(base: Path = Path(), root: Path | None = None) -> list[Entry]:
    """The index, rebuilt first if a source changed since it was written."""
    root = home(root)
    target = _index_path(root)
    if not target.exists() or target.stat().st_mtime < newest_source(base):
        return build(base, root)
    raw = json.loads(target.read_text(encoding="utf-8"))
    return [Entry(**row) for row in raw]


def _terms(text: str) -> list[str]:
    return [w for w in WORD.findall(text.lower()) if w not in STOP]


def search(query: str, entries: list[Entry], limit: int = 8) -> list[dict[str, Any]]:
    """Entries ranked by BM25 over title (counted three times) and text."""
    wanted = _terms(query)
    if not wanted or not entries:
        return []
    docs = [_terms(f"{e.title} {e.title} {e.title} {e.text}") for e in entries]
    avg = sum(len(d) for d in docs) / len(docs)
    df: Counter[str] = Counter()
    for d in docs:
        df.update(set(d))
    n = len(docs)
    scored: list[tuple[float, int]] = []
    for index, d in enumerate(docs):
        counts = Counter(d)
        score = 0.0
        for term in wanted:
            tf = counts.get(term, 0)
            if not tf:
                continue
            idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
            score += idf * tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * len(d) / max(avg, 1)))
        if score > 0:
            scored.append((score, index))
    scored.sort(reverse=True)
    out = []
    for score, index in scored[:limit]:
        e = entries[index]
        out.append(
            {
                "kind": e.kind,
                "path": e.path,
                "title": e.title,
                "score": round(score, 2),
                "snippet": e.text[:400],
            }
        )
    return out
