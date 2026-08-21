"""Tenant isolation.

Most of this file is about paths, which sounds dull until you notice that the
only thing standing between tenant A and tenant B's broker credentials is that
a workspace id is validated exactly once. These tests are that validation's
regression suite.

ADR-040 records why the split falls where it does: market data shared, evidence
and credentials isolated.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eulerlab import workspace as ws


@pytest.fixture(autouse=True)
def _isolated_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Never touch the real workspace root from a test."""
    monkeypatch.setattr(ws, "ROOT", tmp_path / "workspaces")
    monkeypatch.setattr(ws, "GLOBAL_KILL_SWITCH", tmp_path / "workspaces" / "KILLED-ALL")


# --- the id is the security boundary ---------------------------------------


@pytest.mark.parametrize(
    "hostile",
    ["../etc", "..", "a/b", "tenant/../other", "/absolute", "....//", "a", "", "   "],
)
def test_a_dangerous_id_is_refused_not_sanitised(hostile: str) -> None:
    """Refusing beats sanitising. A sanitiser that turns `../../etc` into `etc`
    has produced a VALID id for a request that was an attack, and the caller
    cannot tell the difference afterwards."""
    with pytest.raises(ws.WorkspaceError):
        ws.normalise_id(hostile)


def test_a_reasonable_name_becomes_a_safe_id() -> None:
    assert ws.normalise_id("Acme Capital") == "acme-capital"
    assert ws.normalise_id("  Fund_Two  ") == "fund-two"


def test_unicode_lookalikes_cannot_smuggle_a_separator() -> None:
    """NFKC normalisation runs first, so a fullwidth solidus cannot become a
    path separator after validation has already passed."""
    with pytest.raises(ws.WorkspaceError):
        # lookalike for "/", which is exactly the attack being tested.
        ws.normalise_id("a／b")  # noqa: RUF001


# --- what is shared and what is not ----------------------------------------


def test_market_data_is_shared_and_unreachable_from_a_workspace_id() -> None:
    """Duplicating 3.5 GB per tenant would be absurd, and a path that cannot be
    reached from a workspace id cannot be leaked by getting one wrong."""
    assert Path("data/landing") == ws.SHARED_LANDING
    assert not str(ws.SHARED_LANDING).startswith(str(ws.ROOT))


def test_evidence_and_credentials_are_isolated() -> None:
    a = ws.Workspace(id="tenant-a")
    b = ws.Workspace(id="tenant-b")

    assert a.ledger != b.ledger
    assert a.credentials != b.credentials
    assert a.strategies != b.strategies
    assert a.kill_switch != b.kill_switch
    # And none of B's paths sit inside A's tree.
    assert not str(b.credentials).startswith(str(a.root))


def test_the_default_workspace_keeps_the_existing_hash_chain() -> None:
    """That ledger holds 19 real trials and is hash-chained. Moving it would
    break every link, which is exactly the tampering the chain exists to
    expose."""
    assert ws.Workspace(id=ws.DEFAULT_ID).ledger == Path("data/derived/trial_ledger.jsonl")
    assert ws.Workspace(id="tenant-a").ledger != Path("data/derived/trial_ledger.jsonl")


# --- resolution is the only door -------------------------------------------


def test_an_unknown_principal_raises_rather_than_falling_back() -> None:
    """A typo in a tenant id must not silently hand back somebody else's
    evidence. Falling back to the default would do exactly that."""
    with pytest.raises(ws.WorkspaceError, match="no such workspace"):
        ws.resolve("not-a-real-tenant")


def test_no_principal_means_the_single_operator_install() -> None:
    assert ws.resolve(None).id == ws.DEFAULT_ID
    assert ws.resolve("").id == ws.DEFAULT_ID


def test_load_never_creates_a_workspace_as_a_side_effect() -> None:
    assert ws.load("ghost-tenant") is None
    assert not (ws.ROOT / "ghost-tenant").exists()


def test_creating_twice_is_refused() -> None:
    ws.create("Acme Capital")
    with pytest.raises(ws.WorkspaceError, match="already exists"):
        ws.create("Acme Capital")


def test_a_created_workspace_resolves_and_persists() -> None:
    made = ws.create("Acme Capital")
    again = ws.resolve("acme-capital")
    assert again.id == made.id
    assert again.name == "Acme Capital"
    assert (
        json.loads((ws.ROOT / "acme-capital" / "workspace.json").read_text())["id"]
        == "acme-capital"
    )


# --- halting ---------------------------------------------------------------


def test_a_workspace_halt_stops_only_that_workspace() -> None:
    a = ws.create("Tenant A", workspace_id="tenant-a")
    b = ws.create("Tenant B", workspace_id="tenant-b")
    a.kill_switch.write_text(json.dumps({"reason": "daily loss limit"}), encoding="utf-8")

    assert "workspace halted" in ws.halted(a)
    assert ws.halted(b) == "", "one tenant's halt must not stop another"


def test_the_global_switch_outranks_a_workspace_reason() -> None:
    """A platform-wide halt outranks a tenant's own state. Reporting the
    tenant's reason while the platform is down sends them looking in the wrong
    place."""
    a = ws.create("Tenant A", workspace_id="tenant-a")
    a.kill_switch.write_text(json.dumps({"reason": "their own problem"}), encoding="utf-8")
    ws.GLOBAL_KILL_SWITCH.parent.mkdir(parents=True, exist_ok=True)
    ws.GLOBAL_KILL_SWITCH.write_text(json.dumps({"reason": "bad deploy"}), encoding="utf-8")

    reason = ws.halted(a)
    assert "platform halted" in reason
    assert "bad deploy" in reason


def test_an_unreadable_switch_still_reads_as_halted() -> None:
    """Failing to parse must never mean 'clear' — the same rule the order-path
    kill switch follows."""
    a = ws.create("Tenant A", workspace_id="tenant-a")
    a.kill_switch.write_text("{{{ not json", encoding="utf-8")
    assert "halted" in ws.halted(a)


def test_every_workspace_is_listed_including_the_implicit_default() -> None:
    ws.create("Acme", workspace_id="acme-capital")
    ids = {w.id for w in ws.all_workspaces()}
    assert ids == {ws.DEFAULT_ID, "acme-capital"}
