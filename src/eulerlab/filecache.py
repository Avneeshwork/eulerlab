"""Keep what a file parsed to until the file changes.

Several read paths re-parsed the same unchanged file on every call: the landing
census 16 times per dashboard snapshot, a strategy's result log once per
strategy row (2026-10-27). A file is re-read when its modification time or size
changes, the same key `api/company_routes._file_stamp` and ADR-077 use, so a
cached value is never older than its file. A same-size rewrite within one mtime
tick would be missed; every writer here appends or replaces through a rename,
which moves the time.

Values are shared between callers and must be treated as read-only.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml


def stamp(path: Path) -> tuple[int, int] | None:
    """(mtime in ns, size), or None when the file does not exist."""
    try:
        info = path.stat()
    except OSError:
        return None
    return info.st_mtime_ns, info.st_size


class FileMemo[T]:
    """`load(path)`, remembered per path until that file's stamp changes."""

    def __init__(self, load: Callable[[Path], T], *, size: int = 512) -> None:
        self._load = load
        self._size = size
        self._held: OrderedDict[Path, tuple[tuple[int, int] | None, T]] = OrderedDict()
        self._lock = threading.Lock()

    def __call__(self, path: Path) -> T:
        current = stamp(path)
        with self._lock:
            held = self._held.get(path)
            if held is not None and held[0] == current:
                self._held.move_to_end(path)
                return held[1]
        value = self._load(path)
        # Stamped before the read: a write during the read leaves a stale stamp
        # and the next call reads again, never the reverse.
        with self._lock:
            self._held[path] = (current, value)
            self._held.move_to_end(path)
            while len(self._held) > self._size:
                self._held.popitem(last=False)
        return value

    def clear(self) -> None:
        with self._lock:
            self._held.clear()


# libyaml's loader where the wheel has it: the same documents, parsed about
# twelve times faster (every YAML file in the repository compared equal under
# both, 2026-11-08). The pure-Python loader is the fallback, never an error.
_YAML_LOADER: Any = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


def parse_yaml(text: str) -> Any:
    """`yaml.safe_load`, through libyaml when it is installed."""
    return yaml.load(text, Loader=_YAML_LOADER)  # a safe loader, C or Python


def _read_yaml(path: Path) -> Any:
    return parse_yaml(path.read_text(encoding="utf-8"))


read_yaml: FileMemo[Any] = FileMemo(_read_yaml, size=4096)
"""A YAML file's contents, parsed once per change of the file.

The strategy list parsed the same hypothesis cards 388 times per request
(2026-11-08), because `rule_engine.card_spec` is asked once per strategy row by
several callers. The value is shared: read it, never change it."""
