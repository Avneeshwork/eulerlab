"""Workspaces: what is shared between tenants and what is emphatically not.

ADR-040. The split is the whole design:

**Shared** — the landing zone and the derived panels. Market data is not
anyone's private property, and duplicating 3.5 GB per tenant to give each their
own copy of the same NSE bhavcopy would be absurd.

**Per workspace** — the trial ledger, strategies, broker credentials, the kill
switch. This is the *evidence* layer, and it is exactly what must not leak: one
tenant's search must not raise another's bar, and one tenant's API key must
never be reachable from another's session.

Sharing the data and isolating the evidence is what makes this cheap to run and
honest to report at the same time.

### The path rule

Every per-workspace path goes through `Workspace`. Nothing else in the codebase
should build a path under `data/workspaces/` by string concatenation, because
the one thing standing between tenant A and tenant B's broker key is that the
id is validated exactly once, here.

### Authentication is a seam, not an implementation

`resolve()` turns a request principal into a `Workspace`. What produces that
principal — a session cookie, an OIDC token, a local single-user default — is
deliberately not decided here. What *is* decided is that resolution is the only
way to obtain a workspace, so no code path can operate on an unauthenticated
one by forgetting to check.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from eulerlab.paths import data_path

ROOT = data_path("workspaces")

SHARED_LANDING = data_path("landing")
SHARED_DERIVED = data_path("derived")
"""Market data, one copy, readable by every workspace.

Deliberately NOT under `ROOT`. A path that cannot be reached from a workspace
id cannot be leaked by getting a workspace id wrong.
"""

DEFAULT_ID = "default"
"""The single-operator workspace. Every existing path keeps working because the
default workspace's ledger is the one already on disk — see `Workspace.ledger`.
"""

_VALID_ID = re.compile(r"^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$")


class WorkspaceError(ValueError):
    """Raised for an id that must never be turned into a path."""


def normalise_id(raw: str) -> str:
    """Turn a proposed name into a safe id, or refuse.

    Refuses rather than sanitising anything ambiguous. A sanitiser that quietly
    turns `../../etc` into `etc` has produced a *valid* id for a request that
    was an attack, and the caller cannot tell the difference. Unicode is
    normalised first so a lookalike character cannot smuggle a separator
    through.
    """
    text = unicodedata.normalize("NFKC", raw).strip().lower()
    text = re.sub(r"[\s_]+", "-", text)
    if not _VALID_ID.match(text):
        msg = (
            f"invalid workspace id {raw!r}: must be 3-40 chars of a-z, 0-9 and "
            f"hyphens, starting and ending alphanumeric"
        )
        raise WorkspaceError(msg)
    if ".." in text or "/" in text:  # belt and braces; the regex already forbids both
        msg = f"invalid workspace id {raw!r}"
        raise WorkspaceError(msg)
    return text


@dataclass(frozen=True)
class Workspace:
    """One tenant's isolated evidence and credentials.

    Frozen: a workspace handed to a request handler must not be mutated into a
    different tenant halfway through.
    """

    id: str
    name: str = ""
    created: str = ""

    @property
    def root(self) -> Path:
        return ROOT / self.id

    @property
    def ledger(self) -> Path:
        """This workspace's trial ledger.

        The default workspace points at the ORIGINAL path. That ledger is
        hash-chained and holds 19 real trials; moving it would break the chain,
        which is precisely the tampering the chain exists to expose. Everyone
        else gets a fresh chain under their own root.
        """
        if self.id == DEFAULT_ID:
            return SHARED_DERIVED / "trial_ledger.jsonl"
        return self.root / "trial_ledger.jsonl"

    @property
    def strategies(self) -> Path:
        return self.root / "strategies"

    @property
    def credentials(self) -> Path:
        """Broker keys. Never in the repo, never in a shared table.

        A separate file per workspace rather than rows in one store, so a query
        bug cannot return another tenant's key — there is no query.
        """
        return self.root / "credentials.json"

    @property
    def kill_switch(self) -> Path:
        return self.root / "KILLED"

    @property
    def results(self) -> Path:
        return self.root / "results"

    def ensure(self) -> Workspace:
        """Create the directories this workspace needs. Idempotent."""
        for path in (self.root, self.strategies, self.results):
            path.mkdir(parents=True, exist_ok=True)
        return self


GLOBAL_KILL_SWITCH = ROOT / "KILLED-ALL"
"""One switch that stops every workspace.

Separate from the per-workspace switches and checked in addition to them. A
platform-wide problem — a bad deploy, a broker outage, a data corruption — is
not something each tenant should have to notice independently.
"""


def _meta_path(workspace_id: str) -> Path:
    return ROOT / workspace_id / "workspace.json"


def create(name: str, *, workspace_id: str = "") -> Workspace:
    """Register a new workspace. Refuses to overwrite an existing one."""
    identifier = normalise_id(workspace_id or name)
    meta = _meta_path(identifier)
    if meta.exists():
        msg = f"workspace {identifier!r} already exists"
        raise WorkspaceError(msg)

    workspace = Workspace(
        id=identifier, name=name.strip() or identifier, created=datetime.now(UTC).isoformat()
    ).ensure()
    meta.write_text(
        json.dumps(
            {"id": workspace.id, "name": workspace.name, "created": workspace.created},
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return workspace


def load(workspace_id: str) -> Workspace | None:
    """An existing workspace, or None. Never creates one as a side effect."""
    identifier = normalise_id(workspace_id)
    meta = _meta_path(identifier)
    if not meta.exists():
        # The default workspace is implicit: it is the single-operator install
        # that predates tenancy, and demanding it be registered would break
        # every existing path on first run.
        if identifier == DEFAULT_ID:
            return Workspace(id=DEFAULT_ID, name="Default")
        return None
    row = json.loads(meta.read_text(encoding="utf-8"))
    return Workspace(
        id=str(row["id"]), name=str(row.get("name", "")), created=str(row.get("created", ""))
    )


def resolve(principal: str | None) -> Workspace:
    """The only way to obtain a workspace.

    `principal` is whatever authentication produced — a workspace id today, a
    claim from a token later. Resolution being the single entry point is what
    stops a handler operating on an unauthenticated workspace by forgetting to
    check: there is nothing else to call.

    An unknown principal raises. It does NOT fall back to the default
    workspace, because a typo in a tenant id must not silently hand back
    somebody else's evidence.
    """
    if principal is None or not principal.strip():
        return Workspace(id=DEFAULT_ID, name="Default")
    workspace = load(principal)
    if workspace is None:
        msg = f"no such workspace: {principal!r}"
        raise WorkspaceError(msg)
    return workspace


def all_workspaces() -> list[Workspace]:
    """Every registered workspace, plus the implicit default."""
    found: list[Workspace] = [Workspace(id=DEFAULT_ID, name="Default")]
    if ROOT.exists():
        for meta in sorted(ROOT.glob("*/workspace.json")):
            row = json.loads(meta.read_text(encoding="utf-8"))
            if str(row["id"]) != DEFAULT_ID:
                found.append(
                    Workspace(
                        id=str(row["id"]),
                        name=str(row.get("name", "")),
                        created=str(row.get("created", "")),
                    )
                )
    return found


def halted(workspace: Workspace) -> str:
    """Why trading is stopped for this workspace, or an empty string.

    Checks the global switch first. A platform-wide halt outranks a tenant's
    own state, and reporting the tenant's reason while the platform is down
    would send them looking in the wrong place.
    """
    if GLOBAL_KILL_SWITCH.exists():
        try:
            reason = json.loads(GLOBAL_KILL_SWITCH.read_text(encoding="utf-8")).get("reason", "")
        except (json.JSONDecodeError, OSError):
            reason = "unreadable"
        return f"platform halted: {reason}"
    if workspace.kill_switch.exists():
        try:
            reason = json.loads(workspace.kill_switch.read_text(encoding="utf-8")).get("reason", "")
        except (json.JSONDecodeError, OSError):
            reason = "unreadable"
        return f"workspace halted: {reason}"
    return ""
