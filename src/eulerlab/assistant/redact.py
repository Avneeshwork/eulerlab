"""Nothing from `.env` leaves the machine inside a question.

The assistant sends text to a hosted model (ADR-064). The tools it can call
return book values and research text, not credentials, so a secret should
never be in a request. This is the second lock: every request body is scrubbed
of every value `.env` holds before it is sent, whatever put it there.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values

from eulerlab.env import ENV_FILENAME, find_repo_root

MIN_LENGTH = 6
"""Shorter values (a `0` switch, a port) are not secrets, and replacing every
`0` in a table of numbers would destroy the answer."""

MARK = "[redacted]"


def secrets(path: Path | None = None) -> list[str]:
    """Every value in `.env`, and what the environment holds under those names."""
    if path is None:
        root = find_repo_root()
        path = (root / ENV_FILENAME) if root else Path(ENV_FILENAME)
    if not path.exists():
        return []
    found: set[str] = set()
    for key, value in dotenv_values(path).items():
        for candidate in (value or "", os.environ.get(key, "")):
            text = candidate.strip()
            if len(text) >= MIN_LENGTH:
                found.add(text)
    # Longest first, so a secret that contains another is replaced whole.
    return sorted(found, key=len, reverse=True)


def scrub(text: str, values: list[str] | None = None) -> str:
    """`text` with every secret replaced by `[redacted]`."""
    for value in secrets() if values is None else values:
        text = text.replace(value, MARK)
    return text
