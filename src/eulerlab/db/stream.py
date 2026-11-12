"""An append-only stream of JSON lines, in a file or in Postgres (ADR-165).

The trial ledger and the order journals are both "a file written only at its
end, one JSON object per line, numbered from 1". This is that shape with a
second home. `stream_for(path)` answers which home a path has:

- the database is off (`EULERLAB_DATABASE_URL` unset): `None`, and the caller
  keeps its file code, untouched;
- the database is on and the path is under `EULERLAB_DATA_DIR`: a `Stream`
  named by the path relative to the data directory;
- the path is anywhere else (a test's `tmp_path`, a scratch copy): `None`.

A stream whose file still holds more lines than the database raises
`NotImported`: the switch was made before `make db-import`, and reading the
database then would undercount the trial ledger, which loosens the noise bar.

`Stream.append(build)` takes the stream's last line and the next number and
returns the line to add. It runs under a per-stream advisory lock inside one
transaction, so two processes appending at once get 7 and 8, never two 7s, and
the trial ledger's hash links to the row that really came before it. The
table's own trigger refuses a number that is not the next (migration 001).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from eulerlab import db
from eulerlab.paths import data_dir

Build = Callable[[str | None, int], tuple[str, datetime]]
"""(last line or None, next seq) -> (the new line, its event time)."""


class NotImported(RuntimeError):
    """The database is on but this stream's file was never imported into it."""


@dataclass(frozen=True)
class Stream:
    kind: str
    name: str
    workspace: str = db.WORKSPACE

    def read(self) -> list[str]:
        """Every line, in order."""
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT seq, body FROM append_log WHERE workspace_id = %s AND stream = %s"
                " ORDER BY seq",
                (self.workspace, self.name),
            ).fetchall()
        return [str(body) for _, body in rows]

    def count(self) -> int:
        with db.connect() as conn:
            row = conn.execute(
                "SELECT count(*) FROM append_log WHERE workspace_id = %s AND stream = %s",
                (self.workspace, self.name),
            ).fetchone()
        return int(row[0]) if row else 0

    def append(self, build: Build) -> str:
        """Add one line, built from the line before it, atomically."""
        with db.connect() as conn:
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))", (f"{self.workspace}:{self.name}",)
            )
            last = conn.execute(
                "SELECT seq, body FROM append_log WHERE workspace_id = %s AND stream = %s"
                " ORDER BY seq DESC LIMIT 1",
                (self.workspace, self.name),
            ).fetchone()
            seq = int(last[0]) + 1 if last else 1
            body, event_time = build(str(last[1]) if last else None, seq)
            conn.execute(
                "INSERT INTO append_log (workspace_id, kind, stream, seq, body, event_time)"
                " VALUES (%s, %s, %s, %s, %s, %s)",
                (self.workspace, self.kind, self.name, seq, body, event_time),
            )
        return body

    def append_many(self, lines: list[tuple[str, datetime]]) -> int:
        """Add lines in one transaction, in order (the importer). Returns how many."""
        if not lines:
            return 0
        with db.connect() as conn:
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))", (f"{self.workspace}:{self.name}",)
            )
            row = conn.execute(
                "SELECT coalesce(max(seq), 0) FROM append_log"
                " WHERE workspace_id = %s AND stream = %s",
                (self.workspace, self.name),
            ).fetchone()
            start = int(row[0]) + 1 if row else 1
            with conn.cursor() as cur:
                for offset, (body, event_time) in enumerate(lines):
                    cur.execute(
                        "INSERT INTO append_log"
                        " (workspace_id, kind, stream, seq, body, event_time)"
                        " VALUES (%s, %s, %s, %s, %s, %s)",
                        (self.workspace, self.kind, self.name, start + offset, body, event_time),
                    )
        return len(lines)


def stream_name(path: Path) -> str | None:
    """The path relative to the data directory, or None when it is outside it."""
    try:
        return path.resolve().relative_to(data_dir().resolve()).as_posix()
    except ValueError:
        return None


def stream_for(path: Path, kind: str) -> Stream | None:
    """The database home of this path, or None when it stays a file."""
    if not db.configured():
        return None
    name = stream_name(path)
    if not name:
        return None
    stream = Stream(kind, name)
    if path.exists():
        in_file = sum(1 for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip())
        if in_file and stream.count() < in_file:
            msg = (
                f"{name}: the file holds {in_file} lines the database does not;"
                " run `make db-import` before switching the database on"
            )
            raise NotImported(msg)
    return stream


def parse_time(text: str) -> datetime:
    """An ISO time from a line; a naive one is UTC, as every writer here stamps UTC."""
    at = datetime.fromisoformat(text)
    return at if at.tzinfo else at.replace(tzinfo=UTC)
