"""An append-only stream of JSON lines, in a file or in Postgres (ADR-165).

The trial ledger and the order journals are both "a file written only at its
end, one JSON object per line, numbered from 1". This is that shape with a
second home. `stream_for(path)` answers which home a path has:

- the database is off (`EULERLAB_DATABASE_URL` unset): `None`, and the caller
  keeps its file code, untouched;
- the database is on and the path is under `EULERLAB_DATA_DIR`: a `Stream`
  named by the path relative to the data directory;
- the path is anywhere else (a test's `tmp_path`, a scratch copy): `None`.

The stream belongs to the workspace of the request in progress
(`accounts.current()`, ADR-168): the same path in two workspaces is two
streams, and a reader in one cannot reach the other's rows.

A stream can be reset (ADR-166): `Stream.next_generation` starts generation
n + 1, stored under `<name>@<n+1>`, and leaves every earlier generation in
place. `stream_for` returns the current generation. Generation 1 is the plain
name, which is what the importer fills and what the ledger (never reset) uses.

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

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from eulerlab import accounts, db
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
    generation: int = 1

    @property
    def key(self) -> str:
        """The `stream` column: the name, plus `@n` after the first generation."""
        return self.name if self.generation == 1 else f"{self.name}@{self.generation}"

    def next_generation(self, reason: str) -> Stream:
        """Start an empty generation after the current one (a reset). Returns it."""
        with db.connect() as conn:
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                (f"{self.workspace}:{self.name}:generation",),
            )
            n = _current_generation(conn, self.workspace, self.name) + 1
            conn.execute(
                "INSERT INTO stream_generation (workspace_id, stream, generation, reason)"
                " VALUES (%s, %s, %s, %s)",
                (self.workspace, self.name, n, reason),
            )
        return Stream(self.kind, self.name, self.workspace, n)

    def read(self) -> list[str]:
        """Every line, in order."""
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT seq, body FROM append_log WHERE workspace_id = %s AND stream = %s"
                " ORDER BY seq",
                (self.workspace, self.key),
            ).fetchall()
        return [str(body) for _, body in rows]

    def count(self) -> int:
        with db.connect() as conn:
            row = conn.execute(
                "SELECT count(*) FROM append_log WHERE workspace_id = %s AND stream = %s",
                (self.workspace, self.key),
            ).fetchone()
        return int(row[0]) if row else 0

    def append(self, build: Build) -> str:
        """Add one line, built from the line before it, atomically."""
        with db.connect() as conn:
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))", (f"{self.workspace}:{self.key}",)
            )
            last = conn.execute(
                "SELECT seq, body FROM append_log WHERE workspace_id = %s AND stream = %s"
                " ORDER BY seq DESC LIMIT 1",
                (self.workspace, self.key),
            ).fetchone()
            seq = int(last[0]) + 1 if last else 1
            body, event_time = build(str(last[1]) if last else None, seq)
            conn.execute(
                "INSERT INTO append_log (workspace_id, kind, stream, seq, body, event_time)"
                " VALUES (%s, %s, %s, %s, %s, %s)",
                (self.workspace, self.kind, self.key, seq, body, event_time),
            )
        return body

    def append_many(self, lines: list[tuple[str, datetime]]) -> int:
        """Add lines in one transaction, in order (the importer). Returns how many."""
        if not lines:
            return 0
        with db.connect() as conn:
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))", (f"{self.workspace}:{self.key}",)
            )
            row = conn.execute(
                "SELECT coalesce(max(seq), 0) FROM append_log"
                " WHERE workspace_id = %s AND stream = %s",
                (self.workspace, self.key),
            ).fetchone()
            start = int(row[0]) + 1 if row else 1
            with conn.cursor() as cur:
                for offset, (body, event_time) in enumerate(lines):
                    cur.execute(
                        "INSERT INTO append_log"
                        " (workspace_id, kind, stream, seq, body, event_time)"
                        " VALUES (%s, %s, %s, %s, %s, %s)",
                        (self.workspace, self.kind, self.key, start + offset, body, event_time),
                    )
        return len(lines)


def _current_generation(conn: Any, workspace: str, name: str) -> int:
    row = conn.execute(
        "SELECT coalesce(max(generation), 1) FROM stream_generation"
        " WHERE workspace_id = %s AND stream = %s",
        (workspace, name),
    ).fetchone()
    return int(row[0]) if row else 1


def file_lines(path: Path) -> list[str]:
    """A stream file's lines, blank ones skipped and a torn final line dropped.

    A crash mid-write leaves a final line that is not JSON; the event never
    completed (the order journal's own rule), so it is not a line to import.
    """
    if not path.exists():
        return []
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if lines:
        try:
            json.loads(lines[-1])
        except json.JSONDecodeError:
            lines.pop()
    return lines


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
    # Whose stream: the workspace of whoever is asking (ADR-168), so two
    # workspaces writing the same path write two streams. Nothing here takes
    # a workspace as an argument, so no caller can pass the wrong one.
    first = Stream(kind, name, accounts.current().workspace_id)
    # The files are the single-operator install's, from before the switch:
    # only the default workspace's streams were imported from them.
    in_file = len(file_lines(path)) if first.workspace == db.WORKSPACE else 0
    if in_file and first.count() < in_file:
        msg = (
            f"{name}: the file holds {in_file} lines the database does not;"
            " run `make db-import` before switching the database on"
        )
        raise NotImported(msg)
    with db.connect() as conn:
        generation = _current_generation(conn, first.workspace, name)
    return Stream(kind, name, first.workspace, generation)


def parse_time(text: str) -> datetime:
    """An ISO time from a line; a naive one is UTC, as every writer here stamps UTC."""
    at = datetime.fromisoformat(text)
    return at if at.tzinfo else at.replace(tzinfo=UTC)
