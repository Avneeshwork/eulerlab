"""The config loader must fail loudly. A typo'd key that silently defaults is
how a governor ends up switched off in production.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from eulerlab.config import (
    DeployConfig,
    ExecutionConfig,
    load,
    load_deploy,
    load_execution,
)


def test_real_execution_config_loads() -> None:
    cfg = load_execution()
    assert cfg.max_orders_per_second == 5


def test_real_deploy_config_loads() -> None:
    cfg = load_deploy()
    assert cfg.environment == "dev"
    assert cfg.region == "ap-south-1"
    # The compliance stub: present, reserved, deliberately empty until Sprint 29.
    assert cfg.static_ip is None


def test_unknown_key_is_an_error(tmp_path: Path) -> None:
    (tmp_path / "execution.yaml").write_text(
        "max_orders_per_second: 5\nmax_order_per_second: 500\n", encoding="utf-8"
    )
    with pytest.raises(ValidationError, match="max_order_per_second"):
        load(ExecutionConfig, "execution", tmp_path)


def test_ops_governor_cannot_exceed_the_regulatory_threshold(tmp_path: Path) -> None:
    (tmp_path / "execution.yaml").write_text("max_orders_per_second: 50\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        load(ExecutionConfig, "execution", tmp_path)


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load(ExecutionConfig, "execution", tmp_path)


def test_empty_file_uses_defaults(tmp_path: Path) -> None:
    (tmp_path / "deploy.yaml").write_text("", encoding="utf-8")
    assert load(DeployConfig, "deploy", tmp_path).environment == "dev"


def test_non_mapping_file_raises(tmp_path: Path) -> None:
    (tmp_path / "deploy.yaml").write_text("- a\n- b\n", encoding="utf-8")
    with pytest.raises(TypeError, match="mapping"):
        load(DeployConfig, "deploy", tmp_path)


def test_config_is_frozen() -> None:
    cfg = load_execution()
    with pytest.raises(ValidationError):
        cfg.max_orders_per_second = 9  # type: ignore[misc]
