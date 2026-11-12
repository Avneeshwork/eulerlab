"""Every `/api` request proves who it is before a route runs (ADR-168).

Plain ASGI rather than Starlette's `BaseHTTPMiddleware`, so the principal set
here is the one every route, thread pool included, reads through
`accounts.current()`.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

import anyio

from eulerlab import accounts
from eulerlab.accounts import store

Scope = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[MutableMapping[str, Any]]]
Send = Callable[[MutableMapping[str, Any]], Awaitable[None]]
App = Callable[[Scope, Receive, Send], Awaitable[None]]

COOKIE = "eulerlab_session"


def _headers(scope: Scope) -> dict[str, str]:
    return {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}


def _cookie(header: str, name: str) -> str:
    for part in header.split(";"):
        key, _, value = part.strip().partition("=")
        if key == name:
            return value
    return ""


def identify(headers: dict[str, str]) -> accounts.Principal:
    """The principal these headers prove, or `store.AccessDenied`."""
    wanted = headers.get("x-workspace", "").strip() or None
    auth = headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return store.from_token(auth[7:].strip(), wanted)
    session = _cookie(headers.get("cookie", ""), COOKIE)
    if session:
        return store.from_session(session, wanted)
    msg = "log in first"
    raise store.AccessDenied(msg)


async def _refuse(send: Send, status: int, why: str) -> None:
    body = json.dumps({"detail": why}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/json")],
        }
    )
    await send({"type": "http.response.body", "body": body})


class RequireLogin:
    def __init__(self, app: App) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = str(scope.get("path", ""))
        if (
            scope["type"] != "http"
            or not accounts.enabled()
            or not path.startswith("/api")
            or path.startswith(accounts.OPEN)
        ):
            await self.app(scope, receive, send)
            return
        try:
            # The lookups are blocking database calls: off the event loop.
            principal = await anyio.to_thread.run_sync(identify, _headers(scope))
        except store.AccessDenied as exc:
            await _refuse(send, 401, str(exc))
            return
        why = accounts.allowed(principal.role, str(scope.get("method", "GET")), path)
        if why:
            await _refuse(send, 403, why)
            return
        token = accounts.bind(principal)
        try:
            await self.app(scope, receive, send)
        finally:
            accounts.unbind(token)
