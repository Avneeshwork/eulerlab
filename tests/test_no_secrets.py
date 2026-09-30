"""`.env.example` must never carry a real value.

This exists because it already happened once: on 2026-08-18 a `git add -A`
swept an edited `.env.example` containing live Zerodha, Telegram and B2
credentials into a commit, which was pushed. The pre-commit `detect-private-key`
hook did not catch it, because API tokens are not PEM private keys.

A committed file with a filled-in value is a published secret. This test makes
that a red build instead of a discovery.
"""

from __future__ import annotations

import subprocess
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


def _live_values() -> dict[str, str]:
    """Every real credential this machine holds, keyed by name.

    Reads `.env`, which is gitignored, so this is empty in CI and on a fresh
    clone. That is the right failure mode: the check can only run where the
    secrets actually are, and it is worth having there.
    """
    env = REPO_ROOT / ".env"
    if not env.exists():
        return {}
    found: dict[str, str] = {}
    for raw in env.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip().strip('"').strip("'")
        # Short values are chat ids, usernames and account numbers rather than
        # authenticators, and they produce false positives against ordinary
        # prose. The guard is for material that grants access.
        if len(value) >= 12:
            found[key.strip()] = value
    return found


def test_no_live_credential_appears_in_a_tracked_file() -> None:
    """No value from `.env` may appear in anything git tracks.

    `test_every_value_in_env_example_is_empty` above guards one file, because
    one file is where the 2026-08-18 leak happened. It was the wrong shape of
    guard: the same Zerodha key was **also** sitting in
    `docs/RUNBOOKS/kite-login.md`, pasted as an example of correct `.env`
    formatting, where a check that reads only `.env.example` could never see
    it. Found on 2026-08-27 by scanning history for the values themselves.

    So the rule is about the values, not about one filename.
    """
    secrets = _live_values()
    if not secrets:
        pytest.skip("no .env on this machine — nothing to check against")

    tracked = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split("\0")

    leaks: list[str] = []
    for name in tracked:
        if not name:
            continue
        path = REPO_ROOT / name
        try:
            if not path.is_file() or path.stat().st_size > 2_000_000:
                continue
            body = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        # The key name, never the value: a failure message is printed by CI.
        leaks.extend(f"{key} in {name}" for key, value in secrets.items() if value in body)

    assert not leaks, (
        "a live credential from .env is sitting in a tracked file: "
        f"{sorted(leaks)}. Replace it with a placeholder and rotate the value — "
        "it is in the git history of every clone."
    )
