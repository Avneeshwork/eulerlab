"""Can the backup actually be restored? Download a few landed files from B2 and check their hashes.

`make sync-cloud VERIFY=1` compares the SHA-256 recorded as each object's
metadata. That proves what was uploaded, not that the bytes come back. This
downloads a small sample — a different one each day, picked from the date so
it is reproducible — and hashes what arrives against the manifest. Three files
a night is a few megabytes and a handful of B2 transactions out of the daily
2,500.
"""

from __future__ import annotations

import hashlib
import json
import random
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from eulerlab.ingest import cloud
from eulerlab.paths import data_path

MANIFEST = data_path("landing/nse/manifest.jsonl")
STORAGE = Path("config/storage.yaml")


@dataclass(frozen=True)
class Restored:
    path: str
    ok: bool
    detail: str


def sample(manifest: Path, n: int, *, day: date) -> list[dict[str, str]]:
    if not manifest.exists() or n <= 0:
        return []
    rows = [json.loads(x) for x in manifest.read_text(encoding="utf-8").splitlines() if x.strip()]
    rows = [r for r in rows if r.get("sha256") and r.get("path")]
    picker = random.Random(day.toordinal())
    return [
        {"path": str(r["path"]), "sha256": str(r["sha256"])}
        for r in picker.sample(rows, min(n, len(rows)))
    ]


def check(
    n: int = 3,
    *,
    day: date | None = None,
    manifest: Path = MANIFEST,
    get: Callable[[str], bytes] | None = None,
) -> list[Restored]:
    """Download `n` sampled files and compare their hashes. Never raises for one file."""
    picked = sample(manifest, n, day=day or date.today())  # noqa: DTZ011 - the IST day is close enough for a sample
    if not picked:
        return []
    if get is None:
        config = cloud.load_storage_config(STORAGE)
        store = cloud.S3ObjectStore(config)
        prefix = config.prefix

        def get(path: str) -> bytes:
            return store.get(f"{prefix}{path}")

    out: list[Restored] = []
    for row in picked:
        try:
            payload = get(row["path"])
        except Exception as exc:
            out.append(Restored(row["path"], False, f"could not download: {type(exc).__name__}"))
            continue
        same = hashlib.sha256(payload).hexdigest() == row["sha256"]
        out.append(
            Restored(row["path"], same, "matches" if same else "bytes differ from the manifest")
        )
    return out
