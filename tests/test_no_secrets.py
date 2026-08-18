"""`.env.example` must never carry a real value.

This exists because it already happened once: on 2026-08-18 a `git add -A`
swept an edited `.env.example` containing live Zerodha, Telegram and B2
credentials into a commit, which was pushed. The pre-commit `detect-private-key`
hook did not catch it, because API tokens are not PEM private keys.

A committed file with a filled-in value is a published secret. This test makes
that a red build instead of a discovery.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
ENV_EXAMPLE = REPO_ROOT / ".env.example"


def _assignments() -> list[tuple[int, str, str]]:
    found: list[tuple[int, str, str]] = []
    for number, raw in enumerate(ENV_EXAMPLE.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        found.append((number, key.strip(), value.strip()))
    return found


def test_env_example_exists() -> None:
    assert ENV_EXAMPLE.exists(), ".env.example documents the shape of .env and must be present"


def test_every_value_in_env_example_is_empty() -> None:
    filled = [(n, k) for n, k, v in _assignments() if v]
    assert not filled, (
        "`.env.example` is committed, so a value here is a published secret. "
        f"Filled: {filled}. Move the real values to .env (gitignored) and rotate them."
    )


def test_no_commented_out_credentials() -> None:
    """A secret in a comment is still a secret."""
    suspicious: list[int] = []
    for number, raw in enumerate(ENV_EXAMPLE.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line.startswith("#"):
            continue
        body = line.lstrip("#").strip()
        if "=" not in body:
            continue
        key, _, value = body.partition("=")
        if key.strip().isupper() and key.strip() and value.strip().strip("\"'"):
            suspicious.append(number)
    assert not suspicious, f"commented-out credential on line(s) {suspicious} of .env.example"


def test_dotenv_is_ignored_by_git() -> None:
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert ".env" in gitignore


@pytest.mark.parametrize("name", ["ZERODHA_API_SECRET", "B2_APP_KEY", "TELEGRAM_BOT_TOKEN"])
def test_expected_keys_are_documented(name: str) -> None:
    assert name in ENV_EXAMPLE.read_text(encoding="utf-8")
