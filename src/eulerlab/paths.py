"""Where data lives: one setting, read in one place.

Every module used to spell its own `Path("data/landing/...")`. That works on
the operator's Mac, where every command runs from the repository root, and
fails everywhere else: a container, a server, a second machine, a test that
wants a scratch copy. There were 328 such literals across 201 files.

The rule now: **`EULERLAB_DATA_DIR` names the data directory; nothing else
does.** Unset, it is `data` relative to the working directory, which is
exactly what the literals meant, so the Mac keeps behaving as it did. A
container sets it to its mounted volume. A later per-user deployment sets it
per process.

`tools/hygiene.py` fails on any new `Path("data/...")` literal under `src/`,
so the rule cannot erode quietly.
"""

from __future__ import annotations

import os
from pathlib import Path

from eulerlab.env import load_env

ENV_VAR = "EULERLAB_DATA_DIR"
DEFAULT = "data"

_env_loaded = False


def data_dir() -> Path:
    """The data directory. Read on every call, so a test may set the variable
    after import; the cost is one dictionary lookup."""
    global _env_loaded
    if not _env_loaded:
        # `.env` may name the directory, and a module-level constant is built
        # at import, before any entry point has loaded `.env` (env.py).
        load_env()
        _env_loaded = True
    value = os.environ.get(ENV_VAR, "").strip()
    return Path(value).expanduser() if value else Path(DEFAULT)


def data_path(*parts: str) -> Path:
    """`data_path("landing", "nse")` is what `Path("data/landing/nse")` was."""
    return data_dir().joinpath(*parts)
