"""The landing zone: raw exchange bytes, written once, never modified.

Two rules, and everything here exists to enforce them:

1. **What lands is exactly what the exchange served.** Not re-compressed, not
   re-encoded, not tidied. When a bug is found in the parsing code — and one
   will be — the landing zone is what makes a full rebuild possible. A file we
   have "improved" cannot do that job.
2. **A written file is never modified.** Writes are atomic (temp file, then
   rename) so an interrupt cannot leave a half file, and the result is chmod'd
   read-only so a later bug cannot quietly overwrite history.

The manifest is an append-only JSONL ledger beside the files. It is the resume
point for an interrupted run and the record of *when we learned* each file —
the `knowledge_time` that the bitemporal store will later depend on.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path

MANIFEST_NAME = "manifest.jsonl"
READ_ONLY = 0o444


@dataclass(frozen=True)
class ManifestEntry:
    """One successfully landed file. Append-only; never edited in place."""

    trade_date: str
    segment: str
    file_format: str
    url: str
    path: str
    sha256: str
    size_bytes: int
    rows: int
    inner_name: str
    knowledge_time: str

    @property
    def key(self) -> tuple[str, str]:
        return (self.trade_date, self.segment)

    @classmethod
    def from_json(cls, raw: dict[str, object]) -> ManifestEntry:
        """Parse one manifest line, checking types rather than trusting them.

        A manifest that has been hand-edited or truncated should fail loudly
        here, not produce an entry with a string where an int belongs.
        """

        def text(field: str) -> str:
            value = raw[field]
            if not isinstance(value, str):
                msg = f"manifest field {field!r} should be a string, got {type(value).__name__}"
                raise TypeError(msg)
            return value

        def number(field: str) -> int:
            value = raw[field]
            if not isinstance(value, int) or isinstance(value, bool):
                msg = f"manifest field {field!r} should be an int, got {type(value).__name__}"
                raise TypeError(msg)
            return value

        return cls(
            trade_date=text("trade_date"),
            segment=text("segment"),
            file_format=text("file_format"),
            url=text("url"),
            path=text("path"),
            sha256=text("sha256"),
            size_bytes=number("size_bytes"),
            rows=number("rows"),
            inner_name=text("inner_name"),
            knowledge_time=text("knowledge_time"),
        )


def sha256_of(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def relative_path(trade_date: date, segment: str, file_format: str) -> Path:
    """Layout: <segment>/<YYYY>/<MM>/<YYYY-MM-DD>_<format>.zip

    Partitioned by month so a directory listing stays usable across 11 years,
    and named by ISO date so lexical order is chronological order.
    """
    return Path(
        segment.lower(),
        f"{trade_date.year:04d}",
        f"{trade_date.month:02d}",
        f"{trade_date.isoformat()}_{file_format.lower()}.zip",
    )


class Landing:
    """A landing-zone root plus its manifest."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.manifest_path = root / MANIFEST_NAME
        self._entries: dict[tuple[str, str], ManifestEntry] | None = None

    # --- manifest ---

    def entries(self) -> dict[tuple[str, str], ManifestEntry]:
        """Load the manifest once and cache it."""
        if self._entries is None:
            self._entries = {}
            if self.manifest_path.exists():
                for line in self._read_manifest_lines():
                    entry = ManifestEntry.from_json(line)
                    self._entries[entry.key] = entry
        return self._entries

    def _read_manifest_lines(self) -> Iterator[dict[str, object]]:
        with self.manifest_path.open(encoding="utf-8") as handle:
            for raw in handle:
                stripped = raw.strip()
                if stripped:
                    parsed: dict[str, object] = json.loads(stripped)
                    yield parsed

    def has(self, trade_date: date, segment: str) -> bool:
        """True when this date+segment already landed. The idempotency check.

        Requires the recorded file to still be on disk: a manifest entry whose
        file has been deleted is a gap, and pretending otherwise would let a
        re-run silently skip missing data.
        """
        entry = self.entries().get((trade_date.isoformat(), segment))
        if entry is None:
            return False
        return (self.root / entry.path).exists()

    def append(self, entry: ManifestEntry) -> None:
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        with self.manifest_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(entry), sort_keys=True) + "\n")
        self.entries()[entry.key] = entry

    # --- files ---

    def write(
        self,
        *,
        trade_date: date,
        segment: str,
        file_format: str,
        url: str,
        payload: bytes,
        rows: int,
        inner_name: str,
    ) -> ManifestEntry:
        """Write bytes atomically, make them read-only, and record them.

        The manifest is appended *after* the file is safely in place, so a crash
        can leave a file with no manifest row (harmless — the next run
        re-fetches it) but never a manifest row with no file (which would make
        a re-run skip data it does not have).
        """
        rel = relative_path(trade_date, segment, file_format)
        target = self.root / rel
        target.parent.mkdir(parents=True, exist_ok=True)

        handle, tmp_name = tempfile.mkstemp(dir=target.parent, suffix=".part")
        tmp = Path(tmp_name)
        try:
            with os.fdopen(handle, "wb") as fh:
                fh.write(payload)
                fh.flush()
                os.fsync(fh.fileno())
            os.chmod(tmp, READ_ONLY)
            os.replace(tmp, target)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise

        entry = ManifestEntry(
            trade_date=trade_date.isoformat(),
            segment=segment,
            file_format=file_format,
            url=url,
            path=str(rel),
            sha256=sha256_of(payload),
            size_bytes=len(payload),
            rows=rows,
            inner_name=inner_name,
            knowledge_time=datetime.now(UTC).isoformat(),
        )
        self.append(entry)
        return entry

    def verify(self) -> list[str]:
        """Re-hash every landed file and report anything that changed.

        The landing zone claims immutability; this is what makes the claim
        checkable rather than aspirational.
        """
        problems: list[str] = []
        for entry in self.entries().values():
            path = self.root / entry.path
            if not path.exists():
                problems.append(f"{entry.path}: missing")
                continue
            if sha256_of(path.read_bytes()) != entry.sha256:
                problems.append(f"{entry.path}: checksum changed since it was written")
        return problems
