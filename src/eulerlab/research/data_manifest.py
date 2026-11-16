"""What data a research result was computed on: a content hash of every input (#154, ADR-213).

Research 192 found that stored results no longer reproduce and could only
guess why, because nothing recorded which data produced them. Every
experiment-store row now carries `data_version`, the hash of this manifest:
the SHA-256 of each file the rule engine reads, by name.

    panel        derived/price_panel.jsonl
    delivery     derived/delivery.jsonl
    results      derived/nse_earnings_announcements.jsonl
    t2t          derived/trade_for_trade.jsonl
    index        derived/index_history.jsonl (Nifty 50, India VIX)
    reports      landing/nse_reports/manifest.jsonl (bulk deals, SAST)

Hashing 1.2 GB on every record would cost more than the screen, so each
file's hash is kept in `derived/data_manifest.json` beside its size and
modification time and recomputed only when either changes. A restated file
with the same size and time would be missed; no rebuild here produces one.
A missing file hashes as "absent", so the version still says what was there.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from eulerlab.paths import data_path

INPUTS: dict[str, str] = {
    "panel": "derived/price_panel.jsonl",
    "delivery": "derived/delivery.jsonl",
    "results": "derived/nse_earnings_announcements.jsonl",
    "t2t": "derived/trade_for_trade.jsonl",
    "index": "derived/index_history.jsonl",
    "reports": "landing/nse_reports/manifest.jsonl",
}
CACHE = "derived/data_manifest.json"
CHUNK = 1 << 22


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(CHUNK):
            digest.update(block)
    return digest.hexdigest()


def _read_cache(path: Path) -> dict[str, Any]:
    try:
        found = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return found if isinstance(found, dict) else {}


def manifest(inputs: dict[str, str] | None = None) -> dict[str, str]:
    """Each input's content hash (or "absent"), by name. Rehashes only a changed file."""
    cache_path = data_path(CACHE)
    cache = _read_cache(cache_path)
    out: dict[str, str] = {}
    changed = False
    for name, rel in (inputs or INPUTS).items():
        path = data_path(rel)
        if not path.exists():
            out[name] = "absent"
            continue
        stat = path.stat()
        stamp = f"{stat.st_size}:{stat.st_mtime_ns}"
        held = cache.get(str(path))
        if isinstance(held, dict) and held.get("stamp") == stamp:
            out[name] = str(held["sha256"])
            continue
        out[name] = _sha256(path)
        cache[str(path)] = {"stamp": stamp, "sha256": out[name]}
        changed = True
    if changed:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache, indent=1, sort_keys=True), encoding="utf-8")
    return out


def version(found: dict[str, str] | None = None) -> str:
    """One short hash naming the whole manifest."""
    body = json.dumps(found if found is not None else manifest(), sort_keys=True)
    return hashlib.sha256(body.encode()).hexdigest()[:16]


def stamp() -> dict[str, Any]:
    """Which data and which code made a result (#154): enough to say whether a re-run can match.

    Every experiment-store row and every trial-ledger entry carries this (ADR-213, ADR-216).
    """
    from eulerlab.reports import code_version

    code = code_version()
    return {
        "data_version": version(),
        "code": {"commit": code["commit"], "dirty": code["dirty"]},
    }
