"""Each company's sector and industry, from its newest screener.in snapshot (research 182).

screener.in tags every company with a breadcrumb of up to four levels: broad
sector ("Industrials"), sector ("Capital Goods", about 40 of them), industry
("Heavy Electrical Equipment") and basic industry. The snapshot parser stores
them as rows with `section == "sector"` and `row_label` `level_1` to `level_4`.

**The tag is today's, and a backtest applies it backwards** (research 182, red
flags; ASSUMPTIONS A-128): a company that changed business carries its current
tag into the past. Only companies fetched since 2026-08 have one, so a model
that filters on sector can only pick survivors, like every fundamental model
here (`annual.py`).

Joined on ISIN, never ticker: each snapshot's ticker is resolved to the ISIN the
price panel shows for it, as `annual.build` does.
"""

from __future__ import annotations

import io
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from functools import cache
from pathlib import Path
from typing import Any

from eulerlab.fundamentals import annual

OUT = Path("data/derived/sectors.json")


@dataclass(frozen=True)
class Tag:
    """One company's place in the hierarchy; empty strings where a level is missing."""

    symbol: str
    broad: str
    sector: str
    industry: str
    basic: str


def tag_from_records(symbol: str, records: Sequence[Mapping[str, Any]]) -> Tag | None:
    """The tag in one snapshot's rows, or None when it has no sector rows."""
    levels: dict[str, str] = {}
    for r in records:
        if r.get("section") != "sector":
            continue
        label, raw = str(r.get("row_label") or ""), str(r.get("raw") or "").strip()
        if label.startswith("level_") and raw:
            levels[label] = raw
    if not levels:
        return None
    return Tag(
        symbol=symbol,
        broad=levels.get("level_1", ""),
        sector=levels.get("level_2", ""),
        industry=levels.get("level_3", ""),
        basic=levels.get("level_4", ""),
    )


def build(
    isin_of: Mapping[str, str],
    *,
    read: Callable[[str], bytes] | None = None,
    manifest: Path | None = None,
    out: Path | None = None,
) -> dict[str, int]:
    """Write ISIN -> tag for every ticker whose newest snapshot carries one."""
    import pyarrow.parquet as pq

    if read is None:
        from eulerlab.ingest import landing_reader

        def read(rel: str) -> bytes:
            return landing_reader.read(f"fundamentals/{rel}")

    tags: dict[str, dict[str, str]] = {}
    missing = failed = untagged = 0
    for sym, entry in sorted(annual.latest_snapshots(manifest).items()):
        isin = isin_of.get(sym)
        if not isin:
            missing += 1
            continue
        try:
            records = pq.read_table(
                io.BytesIO(read(str(entry["path"]))), columns=["section", "row_label", "raw"]
            ).to_pylist()
        except (OSError, ValueError, KeyError):
            failed += 1
            continue
        tag = tag_from_records(sym, records)
        if tag is None:
            untagged += 1
            continue
        tags[isin] = asdict(tag)
    p = out or OUT
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".partial")
    tmp.write_text(json.dumps(tags, sort_keys=True, indent=0), encoding="utf-8")
    tmp.replace(p)
    load.cache_clear()
    return {"tagged": len(tags), "untagged": untagged, "no_isin": missing, "failed": failed}


@cache
def load(path: Path | None = None) -> dict[str, Tag]:
    """ISIN -> tag; empty when the table has not been built."""
    p = path or OUT
    if not p.exists():
        return {}
    raw = json.loads(p.read_text(encoding="utf-8"))
    return {isin: Tag(**v) for isin, v in raw.items()}
