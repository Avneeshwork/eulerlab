"""A local census of the landing zone, so rendering never waits on the bucket.

### Why this exists

`capabilities()` describes what data the platform holds — "10 pairs, 34,051
pair-days of 1m bars". Those numbers came from listing the bucket, which meant
**35 paginated requests for fx alone**, plus 14,280 keys for mutual funds and
1,200 for crypto: roughly fifty thousand remote keys enumerated to render one
table. Measured cold at **43 seconds**.

Caching helped and did not fix it. A cache with a TTL moves the cost rather
than removing it: with a five-minute expiry, one request in every five-minute
window still pays the full 43 seconds, and it is whichever request happens to
arrive first. Intermittent 43-second page loads are harder to diagnose than
consistent ones, not easier — the page looks broken at random.

So the counts are computed **once, by the ingest that changes them**, and read
from a local file at render time. `make daily` already knows when data lands;
that is the moment to count it, not on the operator's next page load.

### What it deliberately does not do

It does not cache *paths*. The instrument pickers need real listings, and a
stale path list would offer instruments that are not there. Only counts and
derived facts live here — the things a description string needs.

A missing manifest is not an error. `capabilities()` falls back to the live
listing and says the count is unmeasured, which is honest and slow, rather than
reporting zero, which would be fast and false.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

PATH = Path("data/derived/landing_manifest.json")

TREES: tuple[tuple[str, str, str], ...] = (
    ("fx", "fx", "*/*/*.jsonl.gz"),
    ("mf", "mf", "history/*.jsonl.gz"),
    ("mf/enriched", "mf", "enriched/*.jsonl.gz"),
    ("crypto", "crypto", "*/*.jsonl.gz"),
    ("news", "news", "*/*.jsonl.gz"),
    ("calendar", "calendar", "*.jsonl.gz"),
)
"""(key, tree, pattern) for each census entry.

The key is separate from the tree because one tree can hold two things worth
counting separately. `mf` holds 14,280 per-scheme NAV histories *and* one dated
enriched snapshot, and collapsing them lost the distinction in a way that
produced a wrong answer rather than a missing one: `newest` came from the
history files, so asking the census for the latest enriched snapshot returned
`154641.jsonl.gz` — a scheme code — where the real file is `2026-08-21.jsonl.gz`.

A count that is merely absent gets noticed. One that is confidently wrong does
not.
"""


@dataclass
class TreeCensus:
    """What one tree holds."""

    files: int = 0
    groups: int = 0
    """Distinct second-level names — pairs for fx, symbols for crypto. Zero
    where the tree has no such level."""

    newest: str = ""

    def to_row(self) -> dict[str, object]:
        return {"files": self.files, "groups": self.groups, "newest": self.newest}


@dataclass
class Manifest:
    built_at: str = ""
    trees: dict[str, TreeCensus] = field(default_factory=dict)

    def census(self, tree: str) -> TreeCensus | None:
        return self.trees.get(tree)


def build(*, allow_cloud: bool = True) -> Manifest:
    """Count every tree. Slow by design — it runs once, in the ingest."""
    from eulerlab.ingest import landing_reader

    out = Manifest(built_at=datetime.now(UTC).isoformat())
    for key, tree, pattern in TREES:
        found = landing_reader.available(tree, pattern, allow_cloud=allow_cloud)
        groups = {parts[1] for parts in (r.split("/") for r in found) if len(parts) >= 3}
        out.trees[key] = TreeCensus(
            files=len(found),
            groups=len(groups),
            newest=max(found).split("/")[-1] if found else "",
        )
    return out


def save(manifest: Manifest, path: Path = PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "built_at": manifest.built_at,
        "trees": {name: c.to_row() for name, c in sorted(manifest.trees.items())},
    }
    tmp = path.with_suffix(".partial")
    tmp.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    tmp.replace(path)
    return path


def load(path: Path = PATH) -> Manifest | None:
    """The manifest, or None when it has never been built.

    None rather than an empty manifest: an empty one would be indistinguishable
    from a landing zone with nothing in it, and the caller must be able to tell
    "not counted" from "counted, zero".
    """
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    out = Manifest(built_at=str(raw.get("built_at", "")))
    for name, row in (raw.get("trees") or {}).items():
        if isinstance(row, dict):
            out.trees[str(name)] = TreeCensus(
                files=int(row.get("files", 0)),
                groups=int(row.get("groups", 0)),
                newest=str(row.get("newest", "")),
            )
    return out


def _main() -> None:
    manifest = build()
    path = save(manifest)
    print(f"landing census -> {path}")
    for name, census in sorted(manifest.trees.items()):
        extra = f", {census.groups} groups" if census.groups else ""
        print(f"  {name:10s} {census.files:>7,} files{extra}")


if __name__ == "__main__":
    _main()
