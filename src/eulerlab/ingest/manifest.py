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
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from eulerlab.filecache import FileMemo
from eulerlab.paths import data_path

PATH = data_path("derived/landing_manifest.json")

TREES: tuple[tuple[str, str, str], ...] = (
    ("fx", "fx", "*/*/*.jsonl.gz"),
    ("mf", "mf", "history/*.jsonl.gz"),
    ("mf/enriched", "mf", "enriched/*.jsonl.gz"),
    # The daily AMFI snapshot; pruned locally, so coverage needs its census.
    ("mf/navall", "mf", "navall/*.jsonl.gz"),
    ("crypto", "crypto", "*/*.jsonl.gz"),
    ("news", "news", "*/*.jsonl.gz"),
    ("calendar", "calendar", "*.jsonl.gz"),
    # US, added when the Alpaca ingest landed. A tree absent from this list is
    # invisible to the capability matrix and the instrument counts, which read
    # the census rather than the bucket — so 71 million minute bars would have
    # sat in B2 while the US tab reported holding nothing.
    ("us/bars", "us", "bars/*/*.jsonl.gz"),
    ("us/minute", "us", "minute/*/*.jsonl.gz"),
    ("us/sp500", "us", "sp500/*.jsonl.gz"),
    ("us/actions", "us", "actions/*.jsonl.gz"),
    ("us/news", "us", "news/*.jsonl.gz"),
    ("delta", "delta", "candles/*/*.jsonl.gz"),
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

    latest: str = ""
    """The latest date named by any key — `2026-10-07`, or `2026-10` for trees
    filed by month. Not `newest`, which is the largest *file name*: for crypto
    that is `ZROUSDT-1m-…`, the last symbol alphabetically, whatever its date.
    The Instruments coverage table reads this (T-4032)."""

    ids: tuple[str, ...] = ()
    """The leaf names in this tree, for the few trees that need them.

    Empty for almost every tree, and deliberately so: `us/minute` alone is
    15,952 keys and storing them all would turn a small census into a large one
    for no reader.

    `mf/history` needs them. It is the one landed tree whose leaf names cannot
    be recovered from disk after a prune — fund history is flat
    (`mf/history/119551.jsonl.gz`), so there are no directories left behind, and
    the instrument picker had to enumerate 14,280 bucket keys, 18.7 seconds, to
    learn which schemes have data. `build()` already walks every key, so
    recording them here costs nothing it was not already paying."""

    def to_row(self) -> dict[str, object]:
        row: dict[str, object] = {
            "files": self.files,
            "groups": self.groups,
            "newest": self.newest,
            "latest": self.latest,
        }
        if self.ids:
            row["ids"] = list(self.ids)
        return row


@dataclass
class Manifest:
    built_at: str = ""
    trees: dict[str, TreeCensus] = field(default_factory=dict)

    def census(self, tree: str) -> TreeCensus | None:
        return self.trees.get(tree)


ID_TREES: frozenset[str] = frozenset({"mf"})
"""Trees whose leaf names are recorded, not just counted.

The key is `"mf"`, which is what `TREES` calls the fund-history tree — not
`"mf/history"`, which is what its *pattern* suggests. Written wrong the first
time, which is the third occurrence of that mistake in this codebase: a name
that does not match what the manifest records reads as "no such tree" and falls
through to the bucket, silently and slowly. ADR-046 is about the same shape.

Only where the names cannot be recovered any other way. Every other landed tree
keeps a directory per symbol, which survives a prune and answers "which symbols
exist" for free; fund history is flat, so pruning leaves nothing and the bucket
is the only source."""


_DAY = re.compile(r"(?<!\d)(\d{4}-\d{2}-\d{2})(?!\d)")
_MONTH = re.compile(r"(?<!\d)(\d{4}-\d{2})(?![\d-])")


def latest_date(keys: Iterable[str]) -> str:
    """The latest day any key names, else the latest month, else ""."""
    days: list[str] = []
    months: list[str] = []
    for key in keys:
        name = key.rsplit("/", 1)[-1]
        days.extend(_DAY.findall(name))
        months.extend(_MONTH.findall(name))
    if days:
        return max(days)
    return max(months) if months else ""


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
            latest=latest_date(found),
            ids=(
                tuple(sorted(r.split("/")[-1].split(".")[0] for r in found))
                if key in ID_TREES
                else ()
            ),
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
    _LOADED.clear()
    return path


def load(path: Path = PATH) -> Manifest | None:
    """The manifest, or None when it has never been built.

    None rather than an empty manifest: an empty one would be indistinguishable
    from a landing zone with nothing in it, and the caller must be able to tell
    "not counted" from "counted, zero".

    Parsed once per version of the file (`filecache`); a dashboard snapshot
    asked 16 times. The result is shared: do not change it.
    """
    return _LOADED(path)


def _load(path: Path) -> Manifest | None:
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
                ids=tuple(str(x) for x in (row.get("ids") or [])),
                groups=int(row.get("groups", 0)),
                newest=str(row.get("newest", "")),
                latest=str(row.get("latest", "")),
            )
    return out


_LOADED = FileMemo(_load, size=8)


def _main() -> None:
    manifest = build()
    path = save(manifest)
    print(f"landing census -> {path}")
    for name, census in sorted(manifest.trees.items()):
        extra = f", {census.groups} groups" if census.groups else ""
        print(f"  {name:10s} {census.files:>7,} files{extra}")


if __name__ == "__main__":
    _main()
