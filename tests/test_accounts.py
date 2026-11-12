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


# --- isolation (issue #113's test) -----------------------------------------------------------------


def test_two_workspaces_run_the_same_strategy_and_neither_reads_the_other(
    people: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same strategy, different capital, in alpha and beta. Every store the
    issue names (books, the trial ledger, the agent log) shows each workspace
    only its own, through the ordinary readers and through the API."""
    from datetime import date

    from eulerlab.agents import log as agent_log
    from eulerlab.api import deploy_routes
    from eulerlab.deploy import deployments
    from eulerlab.features import trials
    from eulerlab.oms.journal import Journal
    from eulerlab.oms.states import Event, OrderState
    from eulerlab.validation import ledger

    monkeypatch.setattr(deployments, "ROOT", tmp_path / "deployments")
    ledger_path = tmp_path / "derived" / "trial_ledger.jsonl"
    trials_path = tmp_path / "derived" / "trials.jsonl"
    agents_home = tmp_path / "agents"
    store.grant(store.user_id_for("view@x.in"), "beta", "owner")

    def as_(workspace_id: str) -> accounts.Principal:
        return accounts.Principal("u", "", workspace_id, "owner")

    made: dict[str, str] = {}
    for workspace_id, capital in (("alpha", 100_000.0), ("beta", 250_000.0)):
        token = accounts.bind(as_(workspace_id))
        try:
            d = deployments.create("H-0161", mode="paper", capital=capital, start=date(2026, 11, 2))
            made[workspace_id] = d.id
            Journal(d.folder / "orders.jsonl").append(
                f"{workspace_id}-1", Event.CREATED, OrderState.INTENT
            )
            ledger.append(
                kind="backtest", subject=workspace_id, params={}, outcome={}, path=ledger_path
            )
            trials.append(
                trials.Trial(trials.now_iso(), workspace_id, 1, 1, "", "", 1, 0.0, 0.0),
                trials_path,
            )
            agent_log.append("run", "research", {"by": workspace_id}, root=agents_home)
        finally:
            accounts.unbind(token)

    for mine, theirs in (("alpha", "beta"), ("beta", "alpha")):
        token = accounts.bind(as_(mine))
        try:
            books = deployments.all_deployments()
            assert [d.id for d in books] == [made[mine]]
            assert books[0].capital == (100_000.0 if mine == "alpha" else 250_000.0)
            assert Journal(books[0].folder / "orders.jsonl").replay() == {
                f"{mine}-1": OrderState.INTENT
            }
            # Even the other's journal path, if guessed, reads as this workspace's (empty).
            guessed = deployments.ROOT / made[theirs] / "orders.jsonl"
            assert Journal(guessed).read() == []
            assert [e.subject for e in ledger.read(ledger_path)] == [mine]
            assert ledger.count(ledger_path) == 1 and ledger.verify_chain(ledger_path).intact
            assert trials.count(trials_path) == 1
            assert [e.detail["by"] for e in agent_log.read(agents_home)] == [mine]
        finally:
            accounts.unbind(token)

    # And through the API, logged in as each workspace's owner.
    app = _app()
    app.include_router(deploy_routes.router)
    for email, workspace_id in (("owner@x.in", "alpha"), ("view@x.in", "beta")):
        client = TestClient(app)
        _login(client, email)
        listed = client.get("/api/deployments", headers={"X-Workspace": workspace_id}).json()
        assert [d["id"] for d in listed["deployments"]] == [made[workspace_id]]


def test_a_thread_started_by_a_request_runs_as_that_request(people: dict[str, str]) -> None:
    import threading

    seen: list[str] = []
    token = accounts.bind(accounts.Principal("u", "", "beta", "researcher"))
    try:
        thread = threading.Thread(
            target=accounts.carry(lambda: seen.append(accounts.current().workspace_id))
        )
        bare = threading.Thread(target=lambda: seen.append(accounts.current().workspace_id))
        for t in (thread, bare):
            t.start()
            t.join()
    finally:
        accounts.unbind(token)
    assert seen == ["beta", "default"]  # the bare thread fell back to the operator


def test_every_thread_an_api_route_starts_carries_the_principal() -> None:
    """A thread started without `carry` runs as the operator: in another
    workspace's request, that writes into the default workspace's evidence."""
    import re

    api = Path(__file__).resolve().parents[1] / "src" / "eulerlab" / "api"
    # Started at startup, not by a request: these run as the operator on purpose.
    allowed = {"carry", "autoupdate.watch", "telegram_bot.listen", "_preload", "read"}
    loose: list[str] = []
    for path in sorted(api.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"target=([\w.]+)", text):
            if match.group(1) not in allowed:
                loose.append(f"{path.name}: target={match.group(1)}")
        for match in re.finditer(r"\.(submit|map)\((?!carry\()([\w.]+)", text):
            loose.append(f"{path.name}: .{match.group(1)}({match.group(2)}")
    assert not loose, loose
