"""The research library: papers, and the strategies that test them.

One YAML file per paper under `research/papers/`, committed with the code, so
the reason a strategy exists travels with it. Each entry carries the four
things the operator asked every paper to have — a **summary**, the **trade
idea**, the **implementation logic** — plus the **red flags** `CLAUDE.md`
requires of any strategy taken from a paper, and links to what runs it.

A paper is not a strategy. It is the claim; a linked strategy is one reading of
it. Keeping them apart is what lets a failed backtest say "our reading failed"
rather than "the paper is wrong", and lets two readings of one paper sit side
by side. A link is one of:

- `builder` — a rule strategy from the Strategy Builder, saved in a workspace;
- `registered` — a coded strategy in `strategies.REGISTRY`;
- `tweezer` — the Tweezer Bottom scanner, on a stated candle size.

Hypothesis files (`hypotheses/H-NNNN.yaml`) remain the record of what is being
validated; a paper names its hypothesis when it has one.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator

ROOT = Path("research/papers")

Status = Literal["idea", "specified", "backtested", "rejected", "adopted"]


class StrategyLink(BaseModel):
    kind: Literal["builder", "registered", "tweezer"]
    id: str = Field(min_length=1, max_length=80)
    note: str = Field(default="", max_length=400)
    timeframe: int = Field(default=0, ge=0, le=60)
    """For `tweezer`: candle minutes. Ignored otherwise."""


class Paper(BaseModel):
    id: str = ""
    title: str = Field(min_length=3, max_length=200)
    authors: str = Field(default="", max_length=300)
    year: int | None = Field(default=None, ge=1900, le=2100)
    kind: Literal["paper", "report", "book", "note"] = "paper"
    source_url: str = Field(default="", max_length=500)
    pdf: str = Field(default="", max_length=300)
    """Repo-relative path to a local copy, when there is one."""

    added: str = Field(default_factory=lambda: datetime.now(UTC).date().isoformat())
    status: Status = "idea"
    markets: list[str] = Field(default_factory=list, max_length=10)
    summary: str = Field(min_length=1, max_length=6000)
    trade_idea: str = Field(min_length=1, max_length=6000)
    implementation: str = Field(min_length=1, max_length=12000)
    red_flags: list[str] = Field(default_factory=list, max_length=30)
    reported_results: str = Field(default="", max_length=6000)
    """What the source itself claims, copied, so our number can be read
    against theirs. Never our measurement."""

    hypothesis: str = Field(default="", max_length=20)
    strategies: list[StrategyLink] = Field(default_factory=list, max_length=20)

    @field_validator("id")
    @classmethod
    def _slug(cls, value: str) -> str:
        if value and not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,80}", value):
            msg = "id must be lowercase letters, digits and hyphens"
            raise ValueError(msg)
        return value

    @field_validator("hypothesis")
    @classmethod
    def _hypothesis(cls, value: str) -> str:
        if value and not re.fullmatch(r"H-\d{4}", value):
            msg = "hypothesis must look like H-0001"
            raise ValueError(msg)
        return value

    @field_validator("source_url")
    @classmethod
    def _url(cls, value: str) -> str:
        if value and not value.startswith(("https://", "http://")):
            msg = "the source link must start with https://"
            raise ValueError(msg)
        return value

    def with_id(self) -> Paper:
        if self.id:
            return self
        slug = re.sub(r"[^a-z0-9]+", "-", self.title.lower()).strip("-")[:60]
        lead = re.sub(r"[^a-z]+", "", self.authors.split(",")[0].split(" ")[-1].lower())[:20]
        parts = [p for p in (lead, str(self.year or ""), slug) if p]
        return self.model_copy(update={"id": "-".join(parts)[:80].strip("-")})


def _path(paper_id: str, root: Path) -> Path:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,80}", paper_id):
        msg = f"{paper_id!r} is not a paper id"
        raise ValueError(msg)
    return root / f"{paper_id}.yaml"


_LOADER: Any = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
"""libyaml's safe loader when PyYAML was built with it: the same safe subset,
about ten times faster than the pure-Python parser."""

_PARSED: dict[Path, tuple[tuple[int, int], Paper | None]] = {}
"""Each paper as parsed, kept until its file's mtime or size changes. Parsing
all 96 papers was 0.31 s of every 0.33 s Research Library read (2026-10-16)."""


def load(paper_id: str, *, root: Path | None = None) -> Paper | None:
    root = root or ROOT
    try:
        path = _path(paper_id, root)
    except ValueError:
        return None
    try:
        info = path.stat()
    except OSError:
        return None
    stamp = (info.st_mtime_ns, info.st_size)
    cached = _PARSED.get(path)
    if cached is None or cached[0] != stamp:
        raw: Any = yaml.load(path.read_text(encoding="utf-8"), Loader=_LOADER)
        cached = (stamp, Paper.model_validate(raw) if isinstance(raw, dict) else None)
        _PARSED[path] = cached
    # A copy, so a caller that edits its paper cannot change the next reader's.
    return cached[1].model_copy(deep=True) if cached[1] is not None else None


def all_papers(*, root: Path | None = None) -> list[Paper]:
    root = root or ROOT
    if not root.is_dir():
        return []
    out = []
    for path in sorted(root.glob("*.yaml")):
        paper = load(path.stem, root=root)
        if paper is not None:
            out.append(paper)
    return sorted(out, key=lambda p: (p.added, p.id), reverse=True)


def save(paper: Paper, *, root: Path | None = None) -> Path:
    """Write one paper. Long text is kept as YAML block scalars, so the file
    reads like the document it summarises and diffs line by line."""
    root = root or ROOT
    paper = paper.with_id()
    path = _path(paper.id, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = paper.model_dump(exclude_defaults=False)
    tmp = path.with_suffix(".partial")
    tmp.write_text(
        yaml.dump(data, Dumper=_BlockDumper, sort_keys=False, allow_unicode=True, width=88),
        encoding="utf-8",
    )
    tmp.replace(path)
    return path


class _BlockDumper(yaml.SafeDumper):
    pass


def _str(dumper: yaml.SafeDumper, value: str) -> yaml.ScalarNode:
    style = "|" if "\n" in value else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


_BlockDumper.add_representer(str, _str)
