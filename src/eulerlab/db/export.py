"""The database, as files the memory backup can send to B2, and back (T-4562).

`make agents-backup` sends files. With the database on, the trial ledger, the
trials counter, the agent log and the order journals are rows, not files, so
the backup first calls `export`: one JSON-lines file per stream (and per
generation, ADR-166) under `db_export/`, each line a whole row with its
`seq`, `body`, `event_time` and `knowledge_time`, plus `stream_generation.jsonl`.
The backup then sends what changed, by content, as it does for every tree.

Not `pg_dump`. A dump must come from a client of the server's own major
version, which ties the image to the database's version; and a logical copy
of two append-only tables is all there is to keep. The export is also
readable with a text editor, which a dump is not.

`load` is the way back: into an empty database only, in order, so the table's
own triggers re-check that every stream is contiguous as it goes in.
`make db-restore` runs it after `make agents-restore` has fetched the files.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from eulerlab import db
from eulerlab.paths import data_path

EXPORT_DIR = data_path("db_export")
GENERATIONS = "stream_generation.jsonl"
SUFFIX = ".rows.jsonl"


def _write_if_changed(path: Path, text: str) -> bool:
    """Atomic, and untouched when the content is the same."""
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return True


def _iso(value: Any) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def export(target: Path = EXPORT_DIR) -> tuple[int, int]:
    """Write every stream to `target`. Returns (streams, files rewritten)."""
    rows_by_stream: dict[tuple[str, str], list[str]] = {}
    with db.connect() as conn:
        for workspace, kind, stream, seq, body, event_time, knowledge_time in conn.execute(
            "SELECT workspace_id, kind, stream, seq, body, event_time, knowledge_time"
            " FROM append_log ORDER BY workspace_id, stream, seq"
        ):
            row = {
                "kind": kind,
                "seq": seq,
                "body": body,
                "event_time": _iso(event_time),
                "knowledge_time": _iso(knowledge_time),
            }
            rows_by_stream.setdefault((workspace, stream), []).append(
                json.dumps(row, sort_keys=True)
            )
        generations = [
            json.dumps(
                {
                    "workspace_id": w,
                    "stream": s,
                    "generation": g,
                    "reason": r,
                    "started_at": _iso(t),
                },
                sort_keys=True,
            )
            for w, s, g, r, t in conn.execute(
                "SELECT workspace_id, stream, generation, reason, started_at"
                " FROM stream_generation ORDER BY workspace_id, stream, generation"
            )
        ]
    changed = 0
    for (workspace, stream), lines in rows_by_stream.items():
        path = target / workspace / (stream + SUFFIX)
        changed += _write_if_changed(path, "\n".join(lines) + "\n")
    changed += _write_if_changed(
        target / GENERATIONS, "\n".join(generations) + "\n" if generations else ""
    )
    return len(rows_by_stream), changed


def load(source: Path = EXPORT_DIR) -> int:
    """Insert an export into an empty database. Returns the rows loaded."""
    files = sorted(source.rglob("*" + SUFFIX))
    loaded = 0
    with db.connect() as conn:
        row = conn.execute("SELECT count(*) FROM append_log").fetchone()
        if row and int(row[0]):
            msg = "the database already holds rows; restore only into an empty one"
            raise RuntimeError(msg)
        for path in files:
            relative = path.relative_to(source).as_posix()
            workspace, _, stream = relative.partition("/")
            stream = stream.removesuffix(SUFFIX)
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                r = json.loads(line)
                conn.execute(
                    "INSERT INTO append_log (workspace_id, kind, stream, seq, body,"
                    " event_time, knowledge_time) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (
                        workspace,
                        r["kind"],
                        stream,
                        r["seq"],
                        r["body"],
                        r["event_time"],
                        r["knowledge_time"],
                    ),
                )
                loaded += 1
        generations = source / GENERATIONS
        if generations.exists():
            for line in generations.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                g = json.loads(line)
                conn.execute(
                    "INSERT INTO stream_generation (workspace_id, stream, generation, reason,"
                    " started_at) VALUES (%s, %s, %s, %s, %s)",
                    (g["workspace_id"], g["stream"], g["generation"], g["reason"], g["started_at"]),
                )
    return loaded


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not db.configured():
        print(f"{db.ENV_VAR} is not set: the database is off, nothing to export or restore.")
        return 2
    db.migrate()
    if args[:1] == ["--restore"]:
        print(f"restored {load():,} rows from {EXPORT_DIR}")
        return 0
    streams, changed = export()
    print(f"exported {streams} streams to {EXPORT_DIR}; {changed} files changed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
