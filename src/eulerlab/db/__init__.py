"""Postgres for state that more than one process or server must share (ADR-165).

**Optional, and off by default.** `EULERLAB_DATABASE_URL` turns it on. Unset,
every store keeps writing its files under `EULERLAB_DATA_DIR`, exactly as on
the operator's Mac before this module existed. That is the whole migration
story for a single machine: nothing changes until the setting is made.

Set, the stores that have a database form (the trial ledger and the order
journals first, `db/stream.py`) read and write Postgres instead, for any path
under the data directory. A path outside it, which is what every test's
`tmp_path` is, stays a file, so the file behaviour stays tested.

The schema is plain SQL in `db/migrations/NNN_name.sql`, applied in order by
`make db-migrate` and recorded in `schema_migrations`. A migration is applied
once and never edited; a change is a new file.

The workspace is `default` until the multi-user work (issue #113) gives each
user their own; the column is already on every row.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

from eulerlab.env import load_env

if TYPE_CHECKING:
    import psycopg

ENV_VAR = "EULERLAB_DATABASE_URL"
WORKSPACE = "default"
"""Every row's `workspace_id` until issue #113."""
MIGRATIONS = Path(__file__).resolve().parent / "migrations"
_NAME = re.compile(r"^(\d{3})_[a-z0-9_]+\.sql$")

_env_loaded = False


def database_url() -> str:
    """The connection string, or '' when the database is off."""
    global _env_loaded
    if not _env_loaded:
        load_env()
        _env_loaded = True
    return os.environ.get(ENV_VAR, "").strip()


def configured() -> bool:
    return bool(database_url())


@contextmanager
def connect(url: str | None = None) -> Iterator[psycopg.Connection[Any]]:
    """One connection, committed on a clean exit and rolled back on an error."""
    import psycopg

    target = url or database_url()
    if not target:
        msg = f"{ENV_VAR} is not set; the database is off"
        raise RuntimeError(msg)
    with psycopg.connect(target, autocommit=False) as conn:
        yield conn


def migrations() -> list[tuple[int, str, str]]:
    """(version, file name, SQL) for every migration, in order."""
    out = []
    for path in sorted(MIGRATIONS.glob("*.sql")):
        match = _NAME.match(path.name)
        if not match:
            msg = f"{path.name}: migrations are named NNN_snake_case.sql"
            raise ValueError(msg)
        out.append((int(match.group(1)), path.name, path.read_text(encoding="utf-8")))
    versions = [v for v, _, _ in out]
    if versions != list(range(1, len(versions) + 1)):
        msg = f"migration numbers must run 1, 2, 3 ... with no gap: {versions}"
        raise ValueError(msg)
    return out


def migrate(url: str | None = None) -> list[str]:
    """Apply every migration not yet applied. Returns the names applied now."""
    applied_now: list[str] = []
    with connect(url) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            " version integer PRIMARY KEY, name text NOT NULL,"
            " applied_at timestamptz NOT NULL DEFAULT now())"
        )
        # One migrator at a time: two containers starting together must not
        # both apply 002.
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('eulerlab.migrate'))")
        done = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
        for version, name, sql in migrations():
            if version in done:
                continue
            conn.execute(sql.encode())
            conn.execute(
                "INSERT INTO schema_migrations (version, name) VALUES (%s, %s)", (version, name)
            )
            applied_now.append(name)
    return applied_now


def main() -> int:
    if not configured():
        print(f"{ENV_VAR} is not set: the database is off and every store uses files.")
        return 2
    names = migrate()
    print("applied: " + ", ".join(names) if names else "up to date: nothing to apply")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
