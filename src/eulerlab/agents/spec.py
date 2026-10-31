"""What an agent is allowed to be: its definition file, and the operator's switches.

Definitions live in `config/agents/<name>.yaml` and are committed, so what an
agent may do is reviewable in a diff. The control room's switches (on/off, a
lower daily budget) are written to `data/agents/settings.json` instead: the
operator turning an agent off is an operating decision, not a code change.

**Settings can only narrow a definition.** A switch can turn an agent off or
lower its budget; it cannot raise the budget above the definition's ceiling
or widen what the agent may write. Widening needs a reviewed edit to the YAML.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

CONFIG_DIR = Path("config/agents")
ROOT = Path("data/agents")
"""Everything agents write: outputs, briefs, the log, decisions, settings."""


def home(root: Path | None = None) -> Path:
    """`root`, or `ROOT` read now, so a test can point every agent at a folder."""
    return root if root is not None else ROOT


NAME_PATTERN = r"^[a-z][a-z0-9_]{1,31}$"


class AgentSpec(BaseModel):
    """One agent's definition. Unknown keys are refused, so a typo cannot pass."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(pattern=NAME_PATTERN)
    title: str = Field(min_length=3, max_length=80)
    job: str = Field(min_length=10, max_length=400)
    """What it does, in a sentence the operator reads on the control room."""

    worker: str = Field(pattern=r"^eulerlab\.agents\.workers\.[a-z_]+$")
    """The module with its `run(context)` function."""

    enabled: bool = True
    schedule: str = ""
    """When the launchd job runs it, in words (`tools/schedule_daily.py`)."""

    uses_model: bool = False
    provider: str = ""
    """A provider in `config/llm.yaml`. Empty means `research_agent`, then `assistant`."""

    daily_requests: int = Field(default=0, ge=0, le=1000)
    """The most model requests it may make in one IST day. 0 = no model at all."""

    never: list[str] = Field(default_factory=list)
    """What it can never do, in words, shown on the control room."""

    needs_approval: bool = False
    """Whether its items wait in the inbox for the operator."""

    options: dict[str, Any] = Field(default_factory=dict)
    """Worker-specific settings, validated by the worker itself."""

    @field_validator("provider")
    @classmethod
    def _provider_needs_model(cls, value: str) -> str:
        return value.strip()


class Settings(BaseModel):
    """The operator's switches for one agent. Only ever narrows the definition."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    daily_requests: int | None = Field(default=None, ge=0)


class Effective(BaseModel):
    """A definition with the operator's switches applied."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    spec: AgentSpec
    enabled: bool
    daily_requests: int
    switched: Literal["definition", "operator"]


def load_specs(directory: Path = CONFIG_DIR) -> dict[str, AgentSpec]:
    """Every definition, by name. A file whose name differs from its `name` is refused."""
    specs: dict[str, AgentSpec] = {}
    if not directory.is_dir():
        return specs
    for path in sorted(directory.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        spec = AgentSpec.model_validate(raw)
        if spec.name != path.stem:
            msg = f"{path} defines {spec.name!r}; the file must be named after the agent"
            raise ValueError(msg)
        specs[spec.name] = spec
    return specs


def _settings_path(root: Path) -> Path:
    return root / "settings.json"


def read_settings(root: Path | None = None) -> dict[str, Settings]:
    root = home(root)
    path = _settings_path(root)
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(raw, dict):
        return {}
    return {str(k): Settings.model_validate(v) for k, v in raw.items() if isinstance(v, dict)}


def write_setting(
    name: str,
    *,
    enabled: bool | None = None,
    daily_requests: int | None = None,
    root: Path | None = None,
    specs: dict[str, AgentSpec] | None = None,
) -> Effective:
    """Change one switch. Raises if the agent does not exist."""
    root = home(root)
    known = specs if specs is not None else load_specs()
    if name not in known:
        msg = f"no agent named {name!r}. Agents: {', '.join(sorted(known))}"
        raise KeyError(msg)
    current = read_settings(root)
    entry = current.get(name, Settings())
    if enabled is not None:
        entry.enabled = enabled
    if daily_requests is not None:
        entry.daily_requests = daily_requests
    current[name] = entry
    path = _settings_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps({k: v.model_dump(exclude_none=True) for k, v in current.items()}, indent=2),
        encoding="utf-8",
    )
    tmp.replace(path)
    return effective(known[name], entry)


def effective(spec: AgentSpec, settings: Settings | None) -> Effective:
    """The definition narrowed by the switches: off wins, the lower budget wins."""
    enabled = spec.enabled
    budget = spec.daily_requests
    switched: Literal["definition", "operator"] = "definition"
    if settings is not None:
        if settings.enabled is not None and settings.enabled != spec.enabled:
            # Turning on an agent its definition leaves off is a code decision.
            enabled = spec.enabled and settings.enabled
            switched = "operator"
        if settings.daily_requests is not None and settings.daily_requests < budget:
            budget = settings.daily_requests
            switched = "operator"
    return Effective(spec=spec, enabled=enabled, daily_requests=budget, switched=switched)


def all_effective(
    root: Path | None = None, specs: dict[str, AgentSpec] | None = None
) -> dict[str, Effective]:
    root = home(root)
    known = specs if specs is not None else load_specs()
    settings = read_settings(root)
    return {name: effective(spec, settings.get(name)) for name, spec in known.items()}
