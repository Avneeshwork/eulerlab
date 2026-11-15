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
    # Real money and the shared data jobs are the default workspace's, whatever the role.
    assert "platform" in accounts.allowed("owner", "POST", "/api/live-money/deploy", "alpha")
    assert "platform" in accounts.allowed("owner", "GET", "/api/live-money", "alpha")
    assert "platform" in accounts.allowed("owner", "POST", "/api/kite/login", "alpha")
    assert "platform" in accounts.allowed("owner", "POST", "/api/data/feed", "alpha")
    assert accounts.allowed("owner", "GET", "/api/data/status", "alpha") == ""
    assert accounts.allowed("owner", "POST", "/api/backtest", "alpha") == ""


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
    # An owner, but of another workspace: the real-money book is not theirs.
    assert owner.post("/api/live-money/deploy").status_code == 403
    assert owner.post("/api/research/run").status_code == 200

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
    # A pool may run one wrapped function in several threads at once.
    from concurrent.futures import ThreadPoolExecutor

    token = accounts.bind(accounts.Principal("u", "", "beta", "researcher"))
    try:
        with ThreadPoolExecutor(4) as pool:
            got = list(
                pool.map(accounts.carry(lambda _: accounts.current().workspace_id), range(8))
            )
    finally:
        accounts.unbind(token)
    assert got == ["beta"] * 8


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


# --- failed logins (T-4568) --------------------------------------------------------------------------


def test_repeated_wrong_passwords_lock_the_email_for_a_while(people: dict[str, str]) -> None:
    for _ in range(store.MAX_FAILURES):
        with pytest.raises(store.AccessDenied, match="wrong"):
            store.login("owner@x.in", "not the password")
    # Now even the right password is refused, and another account is untouched.
    with pytest.raises(store.AccessDenied, match="too many"):
        store.login("owner@x.in", "a long password")
    assert store.login("res@x.in", "a long password")


def test_many_failures_from_one_address_lock_that_address(people: dict[str, str]) -> None:
    for i in range(store.MAX_FAILURES_PER_ADDRESS):
        with pytest.raises(store.AccessDenied):
            store.login(f"nobody{i}@x.in", "guess guess guess", address="203.0.113.9")
    with pytest.raises(store.AccessDenied, match="too many"):
        store.login("res@x.in", "a long password", address="203.0.113.9")
    assert store.login("res@x.in", "a long password", address="198.51.100.2")


# --- the workspace's gate (ADR-169) -------------------------------------------------------------------


def test_a_workspace_may_tighten_the_gate_and_never_loosen_it(people: dict[str, str]) -> None:
    from eulerlab import gates
    from eulerlab.accounts import gate

    base = gates.load_mandate()
    floor = base["simple"]["min_probabilistic_sharpe"]
    assert gate.effective() == base  # the operator: mandate.yaml as written

    token = accounts.bind(accounts.Principal("u1", "", "alpha", "owner"))
    try:
        assert gate.effective() == base  # no rules of its own yet
        with pytest.raises(gate.Looser, match="loosen"):
            gate.set_rules({"simple.min_probabilistic_sharpe": floor - 0.05})
        with pytest.raises(gate.Looser, match="loosen"):
            gate.set_rules({"statistical.max_pbo": base["statistical"]["max_pbo"] + 0.1})
        for not_theirs in (
            "mode",
            "process.require_signed_evidence",
            "simple.require_positive_each_half",
        ):
            with pytest.raises(gate.Looser, match="platform"):
                gate.set_rules({not_theirs: 1})
        assert gate.own_rules() == {}  # nothing refused was stored
        assert gate.set_rules({"simple.min_probabilistic_sharpe": 0.99}) == 1
        assert (
            gate.set_rules({"simple.min_probabilistic_sharpe": 0.98, "forward_test.min_days": 90})
            == 2
        )
        mine = gate.effective()
        assert mine["simple"]["min_probabilistic_sharpe"] == 0.98
        assert mine["forward_test"]["min_days"] == 90
        assert mine["process"] == base["process"] and mine["mode"] == base["mode"]
    finally:
        accounts.unbind(token)

    token = accounts.bind(accounts.Principal("u2", "", "beta", "owner"))
    try:
        assert gate.effective() == base  # alpha's rules are alpha's alone
    finally:
        accounts.unbind(token)
    assert gates.load_mandate() == base  # mandate.yaml is never written


def test_a_stored_rule_the_platform_has_since_passed_falls_back_to_the_platform() -> None:
    from eulerlab.accounts import gate

    base = {"simple": {"min_probabilistic_sharpe": 0.95}}
    assert gate.tighten(base, {"simple.min_probabilistic_sharpe": 0.97})["simple"] == {
        "min_probabilistic_sharpe": 0.97
    }
    assert base["simple"]["min_probabilistic_sharpe"] == 0.95  # the input is not changed


def test_only_an_owner_sets_the_gate_through_the_api(people: dict[str, str]) -> None:
    app = _app()
    app.include_router(auth_routes.gate_router)
    researcher = TestClient(app)
    _login(researcher, "res@x.in")
    assert researcher.get("/api/gate/rules").json()["workspace"] == "alpha"
    body = {"rules": {"simple.min_probabilistic_sharpe": 0.99}}
    assert researcher.post("/api/accounts/gate", json=body).status_code == 403
    owner = TestClient(app)
    _login(owner, "owner@x.in")
    assert owner.post("/api/accounts/gate", json=body).json()["own"] == body["rules"]
    # Below the mandate's own floor (0.50 since ADR-198), so it loosens the gate.
    loose = {"rules": {"simple.min_probabilistic_sharpe": 0.4}}
    assert owner.post("/api/accounts/gate", json=loose).status_code == 422


# --- agents' files (T-4569) ---------------------------------------------------------------------------


def test_each_workspace_has_its_own_agents_folder(
    people: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from eulerlab.agents import spec

    monkeypatch.setattr(spec, "ROOT", tmp_path / "agents")
    assert spec.home() == tmp_path / "agents"  # the operator, as before
    token = accounts.bind(accounts.Principal("u", "", "alpha", "owner"))
    try:
        assert spec.home() == tmp_path / "workspaces" / "alpha" / "agents"
        assert spec.home(tmp_path / "x") == tmp_path / "x"  # an explicit folder still wins
    finally:
        accounts.unbind(token)


# --- a named workspace is not proof (T-4569) ---------------------------------------------------------


def test_a_request_cannot_name_its_way_into_another_workspace(people: dict[str, str]) -> None:
    from eulerlab import workspace

    token = accounts.bind(accounts.Principal("u", "", "alpha", "researcher"))
    try:
        assert workspace.resolve(None).id == "alpha"  # nothing named: the one logged in to
        assert workspace.resolve("alpha").id == "alpha"
        with pytest.raises(workspace.WorkspaceError, match="not the one"):
            workspace.resolve("beta")
        with pytest.raises(workspace.WorkspaceError, match="not the one"):
            workspace.resolve("default")
    finally:
        accounts.unbind(token)


def test_off_a_named_workspace_resolves_as_before(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from eulerlab import workspace

    monkeypatch.setenv(accounts.ENV_VAR, "off")
    monkeypatch.setattr(workspace, "ROOT", tmp_path / "workspaces")
    workspace.create("Gamma")
    assert workspace.resolve(None).id == "default"
    assert workspace.resolve("gamma").id == "gamma"


# --- scheduled jobs visit every workspace (T-4569) --------------------------------------------------


def test_a_scheduled_job_runs_once_per_workspace_as_that_workspace(people: dict[str, str]) -> None:
    seen = accounts.for_each_workspace(lambda: accounts.current().workspace_id)
    assert seen == {"default": "default", "alpha": "alpha", "beta": "beta"}
    assert accounts.current().workspace_id == "default"  # and it puts the operator back


def test_off_a_scheduled_job_runs_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(accounts.ENV_VAR, "off")
    assert accounts.for_each_workspace(lambda: 1) == {"default": 1}


# --- each workspace's own keys (ADR-170) ------------------------------------------------------------


def test_a_workspace_key_is_sealed_and_only_its_own_workspace_reads_it(
    people: dict[str, str], database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import psycopg

    from eulerlab.accounts import secrets

    monkeypatch.setenv("ANTHROPIC_API_KEY", "the-operators-key")
    monkeypatch.delenv(secrets.KEY_VAR, raising=False)
    assert secrets.for_env("ANTHROPIC_API_KEY") == "the-operators-key"  # the operator: .env

    token = accounts.bind(accounts.Principal("u1", "", "alpha", "owner"))
    try:
        # Another workspace never falls back to the server's key.
        assert secrets.for_env("ANTHROPIC_API_KEY") == ""
        with pytest.raises(secrets.NoSecretKey):
            secrets.put("ANTHROPIC_API_KEY", "alphas-key")
        monkeypatch.setenv(secrets.KEY_VAR, secrets.new_key())
        with pytest.raises(ValueError, match="named like"):
            secrets.put("lower-case", "x")
        secrets.put("ANTHROPIC_API_KEY", "alphas-key")
        secrets.put("ANTHROPIC_API_KEY", "alphas-new-key")  # replaced, not duplicated
        assert secrets.for_env("ANTHROPIC_API_KEY") == "alphas-new-key"
        assert secrets.names() == ["ANTHROPIC_API_KEY"]
    finally:
        accounts.unbind(token)

    with psycopg.connect(database) as conn:
        stored = conn.execute("SELECT ciphertext FROM workspace_secrets").fetchall()
    assert len(stored) == 1 and "alphas" not in stored[0][0]  # not readable in the table

    token = accounts.bind(accounts.Principal("u2", "", "beta", "owner"))
    try:
        assert secrets.for_env("ANTHROPIC_API_KEY") == "" and secrets.names() == []
    finally:
        accounts.unbind(token)


def test_the_api_lists_key_names_and_never_a_value(
    people: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from eulerlab.accounts import secrets

    monkeypatch.setenv(secrets.KEY_VAR, secrets.new_key())
    app = _app()
    app.include_router(auth_routes.gate_router)
    owner = TestClient(app)
    _login(owner, "owner@x.in")
    r = owner.post("/api/accounts/secrets", json={"name": "ANTHROPIC_API_KEY", "value": "sk-abc"})
    assert r.json() == {"names": ["ANTHROPIC_API_KEY"]} and "sk-abc" not in r.text
    assert "sk-abc" not in owner.get("/api/accounts/secrets").text
    researcher = TestClient(app)
    _login(researcher, "res@x.in")
    assert researcher.get("/api/accounts/secrets").status_code == 403


def test_the_backup_carries_accounts_and_a_restore_brings_them_back(
    people: dict[str, str], server: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import uuid

    import psycopg

    from eulerlab import db
    from eulerlab.accounts import gate, secrets
    from eulerlab.db import export as db_export

    monkeypatch.setenv(secrets.KEY_VAR, secrets.new_key())
    token = accounts.bind(accounts.Principal(store.user_id_for("owner@x.in"), "", "alpha", "owner"))
    try:
        gate.set_rules({"simple.min_probabilistic_sharpe": 0.99})
        secrets.put("ANTHROPIC_API_KEY", "alphas-key")
    finally:
        accounts.unbind(token)
    target = tmp_path / "export"
    db_export.export(target)
    assert "a long password" not in (target / "tables" / "users.jsonl").read_text()
    assert "alphas-key" not in (target / "tables" / "workspace_secrets.jsonl").read_text()

    name = f"t_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(server, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    monkeypatch.setenv(db.ENV_VAR, server.replace("/postgres?", f"/{name}?"))
    db.migrate()
    db_export.load(target)
    assert store.login("owner@x.in", "a long password")  # the same password still works
    token = accounts.bind(accounts.Principal("u", "", "alpha", "owner"))
    try:
        assert gate.own_rules() == {"simple.min_probabilistic_sharpe": 0.99}
        assert secrets.get("ANTHROPIC_API_KEY") == "alphas-key"
    finally:
        accounts.unbind(token)
