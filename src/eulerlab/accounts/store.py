"""Users, workspaces, memberships, sessions and API tokens, in Postgres (migration 003)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from eulerlab import db, workspace
from eulerlab.accounts import ROLES, Principal, Role
from eulerlab.accounts.passwords import hash_password, new_token, token_hash, verify_password

SESSION_DAYS = 14


class AccessDenied(PermissionError):
    """The credentials are wrong, ended, or do not reach this workspace."""


def add_workspace(name: str, *, workspace_id: str = "") -> str:
    """Register a workspace on disk (`workspace.create`) and in the database."""
    identifier = workspace.normalise_id(workspace_id or name)
    if workspace.load(identifier) is None:
        workspace.create(name, workspace_id=identifier)
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO workspaces (id, name) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (identifier, name.strip() or identifier),
        )
    return identifier


def add_user(email: str, password: str, *, name: str = "") -> str:
    user_id = uuid.uuid4().hex
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO users (id, email, name, password_hash) VALUES (%s, %s, %s, %s)",
            (user_id, email.strip().lower(), name, hash_password(password)),
        )
    return user_id


def user_id_for(email: str) -> str:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT id FROM users WHERE email = %s", (email.strip().lower(),)
        ).fetchone()
    if not row:
        msg = f"no user {email!r}"
        raise LookupError(msg)
    return str(row[0])


def grant(user_id: str, workspace_id: str, role: Role) -> None:
    if role not in ROLES:
        msg = f"role must be one of {ROLES}"
        raise ValueError(msg)
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO memberships (user_id, workspace_id, role) VALUES (%s, %s, %s)"
            " ON CONFLICT (user_id, workspace_id) DO UPDATE SET role = EXCLUDED.role",
            (user_id, workspace_id, role),
        )


def _principal(conn: object, user_id: str, wanted: str | None) -> Principal:
    """The user's role in the wanted workspace, else in their first one."""
    rows = conn.execute(  # type: ignore[attr-defined]
        "SELECT u.email, m.workspace_id, m.role FROM users u"
        " JOIN memberships m ON m.user_id = u.id"
        " WHERE u.id = %s AND u.disabled_at IS NULL ORDER BY m.created_at, m.workspace_id",
        (user_id,),
    ).fetchall()
    if not rows:
        msg = "this account belongs to no workspace"
        raise AccessDenied(msg)
    for email, workspace_id, role in rows:
        if wanted is None or workspace_id == wanted:
            return Principal(user_id, str(email), str(workspace_id), role)
    msg = f"not a member of workspace {wanted!r}"
    raise AccessDenied(msg)


MAX_FAILURES = 5
"""Wrong passwords for one email inside `WINDOW` before logins for it are refused."""
MAX_FAILURES_PER_ADDRESS = 20
WINDOW = timedelta(minutes=15)


def _too_many(conn: Any, email: str, address: str) -> bool:
    since = datetime.now(UTC) - WINDOW
    by_email = conn.execute(
        "SELECT count(*) FROM login_failures WHERE email = %s AND at > %s", (email, since)
    ).fetchone()
    if by_email and int(by_email[0]) >= MAX_FAILURES:
        return True
    if not address:
        return False
    by_address = conn.execute(
        "SELECT count(*) FROM login_failures WHERE address = %s AND at > %s", (address, since)
    ).fetchone()
    return bool(by_address and int(by_address[0]) >= MAX_FAILURES_PER_ADDRESS)


def login(email: str, password: str, *, address: str = "") -> str:
    """A new session token for these credentials. Shown once; stored hashed.

    Five wrong passwords for an email, or twenty from one address, inside
    fifteen minutes and further tries are refused without checking the
    password, so a guesser gets a handful of tries, not thousands. The right
    password does not clear the count: an attacker must not be able to reset
    it by logging in to an account of their own.
    """
    email = email.strip().lower()
    with db.connect() as conn:
        if _too_many(conn, email, address):
            msg = "too many failed logins; try again in 15 minutes"
            raise AccessDenied(msg)
        row = conn.execute(
            "SELECT id, password_hash FROM users WHERE email = %s AND disabled_at IS NULL",
            (email,),
        ).fetchone()
        ok = bool(row) and verify_password(password, str(row[1]))  # type: ignore[index]
        if ok:
            token = new_token()
            conn.execute(
                "INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (%s, %s, %s)",
                (token_hash(token), row[0], datetime.now(UTC) + timedelta(days=SESSION_DAYS)),  # type: ignore[index]
            )
            return token
        # Recorded and committed here: raising inside this block would roll it back.
        conn.execute(
            "INSERT INTO login_failures (email, address) VALUES (%s, %s)", (email, address)
        )
    msg = "wrong email or password"
    raise AccessDenied(msg)


def logout(token: str) -> None:
    with db.connect() as conn:
        conn.execute(
            "UPDATE sessions SET ended_at = now() WHERE token_hash = %s AND ended_at IS NULL",
            (token_hash(token),),
        )


def from_session(token: str, wanted: str | None) -> Principal:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT user_id FROM sessions WHERE token_hash = %s"
            " AND ended_at IS NULL AND expires_at > now()",
            (token_hash(token),),
        ).fetchone()
        if not row:
            msg = "the session has ended; log in again"
            raise AccessDenied(msg)
        return _principal(conn, str(row[0]), wanted)


def create_token(user_id: str, workspace_id: str, name: str) -> str:
    """An API token bound to one workspace, with the user's role there."""
    token = new_token()
    with db.connect() as conn:
        _principal(conn, user_id, workspace_id)  # must already be a member
        conn.execute(
            "INSERT INTO api_tokens (token_hash, user_id, workspace_id, name)"
            " VALUES (%s, %s, %s, %s)",
            (token_hash(token), user_id, workspace_id, name),
        )
    return token


def revoke_token(token: str) -> None:
    with db.connect() as conn:
        conn.execute(
            "UPDATE api_tokens SET revoked_at = now() WHERE token_hash = %s AND revoked_at IS NULL",
            (token_hash(token),),
        )


def from_token(token: str, wanted: str | None) -> Principal:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT user_id, workspace_id FROM api_tokens"
            " WHERE token_hash = %s AND revoked_at IS NULL",
            (token_hash(token),),
        ).fetchone()
        if not row:
            msg = "unknown or revoked API token"
            raise AccessDenied(msg)
        if wanted is not None and wanted != row[1]:
            msg = f"this token is for workspace {row[1]!r}, not {wanted!r}"
            raise AccessDenied(msg)
        return _principal(conn, str(row[0]), str(row[1]))
