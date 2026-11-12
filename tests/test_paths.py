"""`EULERLAB_DATA_DIR` is the one setting for where data lives (paths.py)."""

from __future__ import annotations

from pathlib import Path

import pytest

from eulerlab import paths


def test_default_is_data_relative_to_cwd(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(paths.ENV_VAR, raising=False)
    assert paths.data_dir() == Path("data")
    assert paths.data_path("landing", "nse") == Path("data/landing/nse")
    assert paths.data_path("derived/price_panel.jsonl") == Path("data/derived/price_panel.jsonl")


def test_env_var_wins(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(paths.ENV_VAR, str(tmp_path))
    assert paths.data_dir() == tmp_path
    assert paths.data_path("landing") == tmp_path / "landing"


def test_blank_env_var_means_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(paths.ENV_VAR, "  ")
    assert paths.data_dir() == Path("data")


def test_tilde_is_expanded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(paths.ENV_VAR, "~/eulerlab-data")
    assert paths.data_dir() == Path.home() / "eulerlab-data"


def test_no_src_module_spells_the_data_directory() -> None:
    """The hygiene check that keeps the rule: a literal `data/...` under src/ fails."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "hygiene", Path(__file__).resolve().parents[1] / "tools" / "hygiene.py"
    )
    assert spec is not None and spec.loader is not None
    hygiene = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hygiene)
    assert hygiene.check_data_literals() == []
