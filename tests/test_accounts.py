"""Accounts and login (ADR-168): off means the operator; on, every /api request proves who it is."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from eulerlab import accounts
from eulerlab.accounts import passwords, store
from eulerlab.accounts import routes as auth_routes
from eulerlab.accounts.middleware import COOKIE, RequireLogin


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(auth_routes.router)

    @app.get("/api/whoami")
    def whoami() -> dict[str, str]:
        p = accounts.current()
        return {"user": p.user_id, "workspace": p.workspace_id, "role": p.role}

    @app.post("/api/research/run")
    def research() -> dict[str, str]:
        return {"ran": accounts.current().workspace_id}

    @app.post("/api/live-money/deploy")
    def live() -> dict[str, str]:
        return {"sent": "orders"}

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"ok": "yes"}

    app.add_middleware(RequireLogin)
    return app


# --- without a database --------------------------------------------------------------------------


def test_the_role_table() -> None:
    assert accounts.allowed("owner", "POST", "/api/live-money/deploy") == ""
    assert accounts.allowed("researcher", "POST", "/api/research/run") == ""
    assert "owner" in accounts.allowed("researcher", "POST", "/api/live-money/deploy")
    assert "owner" in accounts.allowed("researcher", "POST", "/api/agents/ceo/settings")
    assert "owner" in accounts.allowed("researcher", "GET", "/api/kite/callback")
    assert accounts.allowed("viewer", "GET", "/api/research/x") == ""
    assert "read" in accounts.allowed("viewer", "POST", "/api/research/run")


def test_passwords_hash_and_verify() -> None:
    stored = passwords.hash_password("correct horse battery")
    assert passwords.verify_password("correct horse battery", stored)
    assert not passwords.verify_password("wrong horse battery", stored)
    assert stored != passwords.hash_password("correct horse battery")  # salted
    with pytest.raises(ValueError, match="characters"):
        passwords.hash_password("short")


def test_off_every_request_is_the_operator(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(accounts.ENV_VAR, "off")
    client = TestClient(_app())
    assert client.get("/api/whoami").json() == {
        "user": "operator",
        "workspace": "default",
        "role": "owner",
    }
    assert client.post("/api/live-money/deploy").status_code == 200
    assert client.get("/api/auth/me").json()["auth"] == "off"


# --- with a database ------------------------------------------------------------------------------


@pytest.fixture
def people(database: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, str]:
    monkeypatch.setattr("eulerlab.workspace.ROOT", tmp_path / "workspaces")
    monkeypatch.setenv(accounts.ENV_VAR, "on")
    store.add_workspace("Alpha")
    store.add_workspace("Beta")
    for email, workspace_id, role in (
        ("owner@x.in", "alpha", "owner"),
        ("res@x.in", "alpha", "researcher"),
        ("view@x.in", "beta", "viewer"),
    ):
        user = store.add_user(email, "a long password")
        store.grant(user, workspace_id, role)  # type: ignore[arg-type]
    return {"alpha": "owner@x.in"}


def _login(client: TestClient, email: str) -> None:
    r = client.post("/api/auth/login", json={"email": email, "password": "a long password"})
    assert r.status_code == 200, r.text
    assert COOKIE in client.cookies


def test_on_a_request_without_a_login_is_refused(people: dict[str, str]) -> None:
    client = TestClient(_app())
    assert client.get("/api/whoami").status_code == 401
    assert client.get("/api/health").status_code == 200  # the container's health check
    bad = client.post("/api/auth/login", json={"email": "owner@x.in", "password": "nope nope nope"})
    assert bad.status_code == 401


def test_on_roles_decide_and_the_workspace_is_the_members(people: dict[str, str]) -> None:
    owner = TestClient(_app())
    _login(owner, "owner@x.in")
    assert owner.get("/api/whoami").json()["workspace"] == "alpha"
    assert owner.post("/api/live-money/deploy").status_code == 200

    researcher = TestClient(_app())
    _login(researcher, "res@x.in")
    assert researcher.post("/api/research/run").json() == {"ran": "alpha"}
    assert researcher.post("/api/live-money/deploy").status_code == 403
    # Asking for a workspace you are not in is refused, never swapped for yours.
    assert researcher.get("/api/whoami", headers={"X-Workspace": "beta"}).status_code == 401

    viewer = TestClient(_app())
    _login(viewer, "view@x.in")
    assert viewer.get("/api/whoami").json()["role"] == "viewer"
    assert viewer.post("/api/research/run").status_code == 403


def test_on_logout_ends_the_session(people: dict[str, str]) -> None:
    client = TestClient(_app())
    _login(client, "owner@x.in")
    token = client.cookies[COOKIE]
    client.post("/api/auth/logout")
    client.cookies.set(COOKIE, token)  # replaying the old cookie
    assert client.get("/api/whoami").status_code == 401


def test_on_an_api_token_is_bound_to_one_workspace_and_can_be_revoked(
    people: dict[str, str],
) -> None:
    token = store.create_token(store.user_id_for("owner@x.in"), "alpha", "laptop")
    client = TestClient(_app())
    auth = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/whoami", headers=auth).json()["workspace"] == "alpha"
    assert client.get("/api/whoami", headers={**auth, "X-Workspace": "beta"}).status_code == 401
    with pytest.raises(store.AccessDenied):  # a token only for a workspace you are in
        store.create_token(store.user_id_for("owner@x.in"), "beta", "nope")
    store.revoke_token(token)
    assert client.get("/api/whoami", headers=auth).status_code == 401
