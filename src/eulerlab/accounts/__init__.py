"""Accounts: who is asking, for which workspace, with which role (ADR-168, issue #113).

**Off by default.** `EULERLAB_AUTH` unset or `off`: every request is the
operator, owner of the `default` workspace, exactly as before accounts
existed. That is the Mac. `EULERLAB_AUTH=on` needs the database
(`EULERLAB_DATABASE_URL`) and makes every `/api` request prove who it is: a
session cookie from `POST /api/auth/login`, or `Authorization: Bearer <token>`
from `make account-token`.

**One place decides.** `accounts.middleware` turns the request into a
`Principal` and puts it in a context variable before any route runs;
`current()` reads it. A route cannot forget to check, because the check
happened before it was called, and `allowed` is the one table of what each
role may do:

- **owner**: everything, including real money, broker logins and members;
- **researcher**: research, backtests, paper books and agents; never real
  money, a broker login or another member's access;
- **viewer**: reads only.

Whatever the role, only the `default` workspace reaches real money, broker
sessions and the shared data jobs (`PLATFORM_ONLY`, `PLATFORM_WRITES`).

The workspace comes from the `X-Workspace` header, else the user's first
membership; a workspace the user is not a member of is refused, never
replaced by another (the rule `workspace.resolve` already keeps).
"""

from __future__ import annotations

import contextvars
import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from eulerlab.env import load_env
from eulerlab.workspace import DEFAULT_ID

ENV_VAR = "EULERLAB_AUTH"
Role = Literal["owner", "researcher", "viewer"]
ROLES: tuple[Role, ...] = ("owner", "researcher", "viewer")

READS = frozenset({"GET", "HEAD", "OPTIONS"})
OPEN = ("/api/health", "/api/auth/login")
"""Paths answered without a login: the container's health check and the login itself."""
OWNER_ONLY = (
    "/api/live-money",
    "/api/kite/login",
    "/api/kite/callback",
    "/api/fyers/login",
    "/api/fyers/callback",
    "/api/accounts",
)
"""Real money, broker sessions and membership: an owner's decisions alone."""
PLATFORM_ONLY = ("/api/live-money", "/api/kite", "/api/fyers")
"""The default workspace alone, read or write: there is one live clock, one
broker session and one real-money book on the server, and they are the
operator's (S-061). An owner of another workspace must not see or act on them."""
PLATFORM_WRITES = ("/api/data/", "/api/cloud/mirror", "/api/strategies/archive")
"""Shared market data, the bucket and the shared strategy library: every
workspace reads them, only the default workspace changes them."""
OWNER_ONLY_SUFFIX = ("/settings",)
"""`/api/agents/{name}/settings`: an agent's model, budget and keys."""


_env_loaded = False


def enabled() -> bool:
    global _env_loaded
    if not _env_loaded:
        load_env()
        _env_loaded = True
    return os.environ.get(ENV_VAR, "").strip().lower() in {"on", "1", "true", "yes"}


@dataclass(frozen=True)
class Principal:
    user_id: str
    email: str
    workspace_id: str
    role: Role


OPERATOR = Principal("operator", "", DEFAULT_ID, "owner")
"""Everyone, when accounts are off: the single operator, as before."""

_current: contextvars.ContextVar[Principal] = contextvars.ContextVar(
    "eulerlab_principal", default=OPERATOR
)


def current() -> Principal:
    """Who the running request is. The operator outside a request or with accounts off."""
    return _current.get()


def bind(principal: Principal) -> contextvars.Token[Principal]:
    return _current.set(principal)


def unbind(token: contextvars.Token[Principal]) -> None:
    _current.reset(token)


def carry[T](fn: Callable[..., T]) -> Callable[..., T]:
    """`fn`, run later in another thread as whoever is asking now.

    A thread does not inherit context variables, so a backtest started by a
    researcher in workspace B would otherwise run as the operator and log its
    trials into the default workspace's ledger. Every thread or pool task a
    request starts goes through this; `tests/test_accounts.py` holds the API
    modules to it.
    """
    context = contextvars.copy_context()

    def run(*args: Any, **kwargs: Any) -> T:
        # A copy per call: a pool may run the same wrapped function in
        # several threads at once, and one Context cannot be entered twice.
        return context.copy().run(fn, *args, **kwargs)

    return run


def workspace_ids() -> list[str]:
    """Every workspace on this install: `default` alone when accounts are off."""
    if not enabled():
        return [DEFAULT_ID]
    from eulerlab import db

    with db.connect() as conn:
        found = [str(row[0]) for row in conn.execute("SELECT id FROM workspaces ORDER BY id")]
    return [DEFAULT_ID, *(w for w in found if w != DEFAULT_ID)]


def for_each_workspace[T](work: Callable[[], T]) -> dict[str, T]:
    """Run `work` once as each workspace's own system user, for scheduled jobs.

    A job the scheduler starts has no request and so runs as the operator; a
    job that must act on every workspace's books (the daily paper run) goes
    through here, and inside `work` every store sees that workspace alone.
    """
    out: dict[str, T] = {}
    for workspace_id in workspace_ids():
        principal = (
            OPERATOR
            if workspace_id == DEFAULT_ID
            else Principal("system", "", workspace_id, "owner")
        )
        token = bind(principal)
        try:
            out[workspace_id] = work()
        finally:
            unbind(token)
    return out


def allowed(role: Role, method: str, path: str, workspace_id: str = DEFAULT_ID) -> str:
    """'' when this role, in this workspace, may make this request, else why not."""
    if workspace_id != DEFAULT_ID:
        if path.startswith(PLATFORM_ONLY):
            return "live trading and broker sessions belong to the platform's own workspace"
        if path.startswith(PLATFORM_WRITES) and method.upper() not in READS:
            return "shared market data is changed only by the platform's own workspace"
    if role == "owner":
        return ""
    if path.startswith(OWNER_ONLY) or path.endswith(OWNER_ONLY_SUFFIX):
        return "only a workspace owner may do this"
    if role == "viewer" and method.upper() not in READS:
        return "a viewer may only read"
    return ""
