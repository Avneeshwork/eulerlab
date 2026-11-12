"""Each workspace's own keys (a model key, later a broker's), encrypted at rest (ADR-170).

On one operator's machine a key is a line in `.env`. With several workspaces
that would mean every user spending the operator's model budget, or trading
through the operator's broker. So a workspace other than `default` never
reads the server's environment for a key: it reads its own, stored here, or
is told it has none.

Sealed with Fernet under `EULERLAB_SECRET_KEY`, which lives in the server's
environment and nowhere in the database: a stolen table or backup opens
nothing. Values go in through `put` and come out only through `get`, inside
the server; no API returns one. `names` lists what is set.

The default workspace keeps using `.env`, as before.
"""

from __future__ import annotations

import os
import re

from eulerlab import accounts, db
from eulerlab.env import load_env
from eulerlab.workspace import DEFAULT_ID

KEY_VAR = "EULERLAB_SECRET_KEY"
_NAME = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")


class NoSecretKey(RuntimeError):
    """The server has no `EULERLAB_SECRET_KEY`, so nothing can be sealed or opened."""


def new_key() -> str:
    """A fresh server key, for `.env`. Losing it loses every stored secret."""
    from cryptography.fernet import Fernet

    return Fernet.generate_key().decode()


def _fernet() -> object:
    from cryptography.fernet import Fernet

    load_env()
    key = os.environ.get(KEY_VAR, "").strip()
    if not key:
        msg = f'{KEY_VAR} is not set. Make one with `make account ARGS="secret-key"` and put it in .env'
        raise NoSecretKey(msg)
    return Fernet(key.encode())


def put(name: str, value: str) -> None:
    """Store one secret for the current workspace, replacing any earlier value."""
    principal = accounts.current()
    if principal.workspace_id == DEFAULT_ID:
        msg = "the default workspace's keys live in .env"
        raise ValueError(msg)
    if not _NAME.match(name):
        msg = f"{name!r}: a secret is named like an environment variable (A-Z, 0-9, _)"
        raise ValueError(msg)
    if not value.strip():
        msg = "an empty value is not a secret"
        raise ValueError(msg)
    sealed = _fernet().encrypt(value.strip().encode()).decode()  # type: ignore[attr-defined]
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO workspace_secrets (workspace_id, name, ciphertext, set_by)"
            " VALUES (%s, %s, %s, %s)"
            " ON CONFLICT (workspace_id, name) DO UPDATE SET"
            " ciphertext = EXCLUDED.ciphertext, set_by = EXCLUDED.set_by, set_at = now()",
            (principal.workspace_id, name, sealed, principal.user_id),
        )


def get(name: str) -> str | None:
    """The current workspace's secret, or None. Never the server's environment."""
    workspace_id = accounts.current().workspace_id
    if workspace_id == DEFAULT_ID or not db.configured():
        return None
    with db.connect() as conn:
        row = conn.execute(
            "SELECT ciphertext FROM workspace_secrets WHERE workspace_id = %s AND name = %s",
            (workspace_id, name),
        ).fetchone()
    if not row:
        return None
    return str(_fernet().decrypt(str(row[0]).encode()).decode())  # type: ignore[attr-defined]


def names() -> list[str]:
    """Which secrets the current workspace has set. Names only."""
    workspace_id = accounts.current().workspace_id
    if workspace_id == DEFAULT_ID or not db.configured():
        return []
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT name FROM workspace_secrets WHERE workspace_id = %s ORDER BY name",
            (workspace_id,),
        ).fetchall()
    return [str(r[0]) for r in rows]


def for_env(name: str) -> str:
    """The value of key `name` for whoever is asking: `.env` for the default
    workspace, the workspace's own secret for any other, '' when unset."""
    if accounts.current().workspace_id == DEFAULT_ID:
        load_env()
        return os.environ.get(name, "").strip()
    return get(name) or ""
