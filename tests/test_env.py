"""Loading `.env`, and the empty-variable shadowing that broke `make kite-login`."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from eulerlab.env import find_repo_root, load_env, require


def _write_env(tmp_path: Path, text: str) -> Path:
    path = tmp_path / ".env"
    path.write_text(text, encoding="utf-8")
    return path


# --- the bug this module exists for ---


def test_an_empty_exported_variable_does_not_shadow_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reported failure. `make kite-login` said "ZERODHA_API_KEY is not
    set" while .env held a 16-character value, because a shell that had once
    sourced a blank .env kept exporting the blank, and load_dotenv refuses to
    replace a variable that already exists.
    """
    monkeypatch.setenv("ZERODHA_API_KEY", "")
    path = _write_env(tmp_path, "ZERODHA_API_KEY=realkey123\n")

    load_env(path)

    assert os.environ["ZERODHA_API_KEY"] == "realkey123"


def test_a_whitespace_only_variable_is_also_treated_as_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ZERODHA_API_KEY", "   ")
    load_env(_write_env(tmp_path, "ZERODHA_API_KEY=realkey123\n"))
    assert os.environ["ZERODHA_API_KEY"] == "realkey123"


def test_a_real_exported_value_still_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`B2_KEY_ID=other uv run ...` must keep working - only blanks are
    treated as unset, so a deliberate override is never stolen."""
    monkeypatch.setenv("B2_KEY_ID", "deliberate")
    load_env(_write_env(tmp_path, "B2_KEY_ID=fromfile\n"))
    assert os.environ["B2_KEY_ID"] == "deliberate"


def test_a_missing_variable_is_filled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SOME_NEW_VAR", raising=False)
    load_env(_write_env(tmp_path, "SOME_NEW_VAR=value\n"))
    assert os.environ["SOME_NEW_VAR"] == "value"


def test_an_empty_value_in_the_file_is_not_applied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A blank placeholder in .env must not overwrite a real exported value."""
    monkeypatch.setenv("PLACEHOLDER_VAR", "real")
    load_env(_write_env(tmp_path, "PLACEHOLDER_VAR=\n"))
    assert os.environ["PLACEHOLDER_VAR"] == "real"


def test_what_was_applied_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APPLIED_A", raising=False)
    monkeypatch.setenv("APPLIED_B", "already")
    applied = load_env(_write_env(tmp_path, "APPLIED_A=x\nAPPLIED_B=y\n"))
    assert applied == {"APPLIED_A": "x"}


# --- robustness ---


def test_a_missing_env_file_is_not_an_error(tmp_path: Path) -> None:
    assert load_env(tmp_path / "absent.env") == {}


def test_load_env_is_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("IDEMPOTENT_VAR", raising=False)
    path = _write_env(tmp_path, "IDEMPOTENT_VAR=v\n")
    load_env(path)
    assert load_env(path) == {}  # second call changes nothing
    assert os.environ["IDEMPOTENT_VAR"] == "v"


def test_the_repo_root_is_found_by_marker_not_by_parent_arithmetic() -> None:
    """Counting `.parents[N]` breaks silently when the package is installed
    non-editable; searching for pyproject.toml does not."""
    root = find_repo_root()
    assert root is not None
    assert (root / "pyproject.toml").exists()


# --- the error message names the real cause ---


def test_require_explains_the_shadowing_case(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ "is not set" alone sent me looking in the wrong place. The message has
    to mention the exported-empty case, because that is what actually
    happened."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    monkeypatch.setenv("MISSING_THING", "")

    with pytest.raises(SystemExit) as excinfo:
        require("MISSING_THING")

    message = str(excinfo.value)
    assert "MISSING_THING" in message
    assert "unset MISSING_THING" in message


def test_require_returns_the_value_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRESENT_THING", "yes")
    assert require("PRESENT_THING") == "yes"
