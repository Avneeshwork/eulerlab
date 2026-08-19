"""One place that loads `.env`, with one rule about what wins.

Two real failures motivated this, both on 2026-08-19.

**An empty exported variable silently shadowed the real credential.**
`python-dotenv`'s `load_dotenv` does not replace a variable that already
exists in the environment, and an exported-but-empty `ZERODHA_API_KEY` counts
as existing. A shell that once sourced a `.env` while it held blank
placeholders keeps those blanks for the life of that terminal, so
`make kite-login` reported "ZERODHA_API_KEY is not set" while the file plainly
had a 16-character value in it. The message is accurate about the environment
and completely misleading about the cause, which is the worst kind of error.

**Most entry points never loaded `.env` at all.** Only `kite_login` did. Every
B2 command — `sync-cloud`, `build-master`, `build-factors` — read
`os.environ` directly and therefore only worked if the operator had manually
run `set -a; source .env; set +a` first. That is not a documented step
anywhere, and forgetting it produces "B2_KEY_ID must be set", which reads like
missing credentials rather than a missing shell incantation.

The rule here: **an empty variable is treated as unset, so the file fills it;
a variable with a real value is left alone.** That keeps the normal override
(`B2_KEY_ID=other uv run ...` still works for pointing at a different account)
while removing the footgun, which only ever involved blanks.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values

ENV_FILENAME = ".env"
MARKERS = ("pyproject.toml", ENV_FILENAME)


def find_repo_root(start: Path | None = None) -> Path | None:
    """Walk upward looking for the repository root.

    Searched rather than computed from `__file__` with a fixed number of
    `.parents[]` hops: that arithmetic is silently wrong the moment the
    package is installed non-editable into a venv, and the failure mode is a
    `.env` that is never found rather than an error.
    """
    for base in (start, Path.cwd(), Path(__file__).resolve().parent):
        if base is None:
            continue
        for candidate in (base.resolve(), *base.resolve().parents):
            if any((candidate / marker).exists() for marker in MARKERS):
                return candidate
    return None


def load_env(path: Path | None = None) -> dict[str, str]:
    """Fill missing or empty environment variables from `.env`.

    Returns the names and values actually applied, so a caller can log or test
    what changed. Idempotent and safe to call from several entry points.
    """
    if path is None:
        root = find_repo_root()
        if root is None:
            return {}
        path = root / ENV_FILENAME
    if not path.exists():
        return {}

    applied: dict[str, str] = {}
    for key, value in dotenv_values(path).items():
        if not value:
            continue
        if os.environ.get(key, "").strip():
            # A real value is already set. Leave it: overriding would break
            # the legitimate `VAR=other uv run ...` case.
            continue
        os.environ[key] = value
        applied[key] = value
    return applied


def require(name: str) -> str:
    """Read a required variable, loading `.env` first, or fail with a message
    that names the actual cause rather than just the symptom."""
    load_env()
    value = os.environ.get(name, "").strip()
    if not value:
        msg = (
            f"{name} is not set.\n"
            f"Put it in {ENV_FILENAME} (never .env.example).\n"
            f"If it *is* in {ENV_FILENAME}, this shell has {name} exported as empty, "
            f"which shadows the file - run `unset {name}` or open a new terminal."
        )
        raise SystemExit(msg)
    return value
