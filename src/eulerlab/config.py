"""Typed configuration loading.

Every config file in ``config/`` is parsed into a Pydantic model with
``extra="forbid"``, so a typo in a YAML key is a startup error rather than a
silently-ignored setting that costs money later.

Sprint 0 note: the two configs below exist to reserve keys, not because
anything reads them yet. See ``docs/STUBS.md`` and
``docs/COMPLIANCE_DEFERRED.md``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "config"


class _Strict(BaseModel):
    """Base for every config model: frozen, and unknown keys are an error."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class ExecutionConfig(_Strict):
    """Execution-side limits.

    ``max_orders_per_second`` is the OPS governor. It is deliberately present
    from Sprint 0 even though no EMS exists yet: SEBI's retail algo framework
    treats roughly 10 orders/sec/exchange/client as the boundary of the
    registered-algo regime, so crossing it must be a decision rather than an
    accident. Adding the key now makes the compliance sprint a config change;
    adding it after the EMS exists makes it a redesign.

    # ASSUMPTION: the ~10 OPS threshold is taken from
    # docs/quant_platform_playbook.md s0.1 and is NOT yet verified against the
    # primary SEBI circular. See docs/ASSUMPTIONS.md (A-001).
    """

    max_orders_per_second: int = Field(default=5, gt=0, le=10)


class DeployConfig(_Strict):
    """Where the system runs.

    ``static_ip`` is a placeholder. Indian brokers whitelist one or two static
    IPs per client, which rules out consumer broadband and ephemeral cloud IPs.
    The real value is registered in Sprint 29, before any live order.
    """

    environment: Literal["dev", "sim", "paper", "prod"] = "dev"
    region: str = "ap-south-1"
    static_ip: str | None = None


def load[M: _Strict](model: type[M], name: str, config_dir: Path | None = None) -> M:
    """Load ``config/<name>.yaml`` into ``model``.

    Raises ``FileNotFoundError`` if the file is missing and ``ValidationError``
    if it does not match the model. Both are intentional: a missing or malformed
    config must stop the process, never fall back to a default.
    """
    path = (config_dir or CONFIG_DIR) / f"{name}.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        msg = f"{path} must contain a YAML mapping, got {type(raw).__name__}"
        raise TypeError(msg)
    return model.model_validate(raw)


def load_execution(config_dir: Path | None = None) -> ExecutionConfig:
    return load(ExecutionConfig, "execution", config_dir)


def load_deploy(config_dir: Path | None = None) -> DeployConfig:
    return load(DeployConfig, "deploy", config_dir)
