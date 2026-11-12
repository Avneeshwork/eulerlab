"""Quarantine: landed files that failed a check, held out of use with the reason shown.

Raw data is immutable (CLAUDE.md), so a bad file is never moved, edited or
deleted. Quarantine is a list beside it — `data/quality/quarantine.jsonl`,
append-only — and every reader that builds from the landing zone asks
`is_held(path)` first. The price panel build does (`features/panel.py`), and
so does the data quality contract, which grades a dataset down while any of
its files is held.

A release is another appended line, with a note saying why the file is fine
after all. Nothing is ever removed from the list, so the history of what was
held and why stays readable.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from eulerlab.paths import data_path

PATH = data_path("quality/quarantine.jsonl")


@dataclass(frozen=True)
class Record:
    path: str
    """Relative to its landing tree, as the manifest writes it."""
    dataset: str
    action: Literal["hold", "release"]
    reason: str
    at: str
    by: str


def _rows(path: Path | None) -> list[Record]:
    path = path or PATH
    if not path.exists():
        return []
    out: list[Record] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            out.append(Record(**{k: row[k] for k in Record.__dataclass_fields__}))
    return out


def _append(record: Record, path: Path | None) -> Record:
    path = path or PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(asdict(record)) + "\n")
    return record


def hold(
    dataset: str, file: str, reason: str, *, by: str = "quality", path: Path | None = None
) -> Record:
    """Hold one file out of use. Holding a file already held adds a second reason."""
    return _append(
        Record(
            path=file,
            dataset=dataset,
            action="hold",
            reason=reason.strip()[:500] or "no reason given",
            at=datetime.now(UTC).isoformat(timespec="seconds"),
            by=by,
        ),
        path,
    )


def release(
    dataset: str, file: str, note: str, *, by: str = "operator", path: Path | None = None
) -> Record:
    if not note.strip():
        msg = "a release needs a note saying why the file is fine"
        raise ValueError(msg)
    return _append(
        Record(
            path=file,
            dataset=dataset,
            action="release",
            reason=note.strip()[:500],
            at=datetime.now(UTC).isoformat(timespec="seconds"),
            by=by,
        ),
        path,
    )


def held(path: Path | None = None) -> dict[tuple[str, str], Record]:
    """(dataset, file) -> the hold record, for files held now."""
    current: dict[tuple[str, str], Record] = {}
    for record in _rows(path):
        key = (record.dataset, record.path)
        if record.action == "hold":
            current.setdefault(key, record)
        else:
            current.pop(key, None)
    return current


def is_held(dataset: str, file: str, path: Path | None = None) -> bool:
    return (dataset, file) in held(path)


def history(path: Path | None = None) -> list[Record]:
    return _rows(path)
