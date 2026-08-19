"""Persist the built registries so they are not rebuilt from B2 every time.

Rebuilding takes a couple of minutes and thousands of requests. Worse, it makes
the master a moving target: two callers building at different moments could see
different histories. Persisting it makes the master a *artefact* with a build
stamp, which is what downstream code should depend on.

Stored as **JSONL** — one instrument per line — under `data/`, and *not*
committed.

Two attempts got this wrong before landing here. Indented JSON was rejected by
the large-file hook at 1,360 KB against a 512 KB limit; switching to JSONL
saved only 8 KB, which proved the size was real content rather than
indentation. The stated reason for the format had been "diffable in git
review", and that rationale does not survive a 1.4 MB artefact — so the
artefact is treated as what it is: build output, rebuilt by
`make build-master`, living beside the landing zone it is derived from.

JSONL is still the right format: one instrument per line streams, appends and
diffs sensibly if it ever *is* reviewed, and the file is written sorted so two
builds of identical data are byte-identical.

The build stamp records *when* and *from what*, so a stale master is
identifiable rather than merely suspected.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from eulerlab.master.identity import InstrumentId
from eulerlab.master.registry import Instrument, Registry

MASTER_PATH = Path("data/master/instruments.jsonl")
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class BuildStamp:
    """Provenance for a built master."""

    built_at: str
    source_files: int
    first_date: str
    last_date: str
    schema_version: int = SCHEMA_VERSION

    @classmethod
    def now(cls, *, source_files: int, first_date: date, last_date: date) -> BuildStamp:
        return cls(
            built_at=datetime.now(UTC).isoformat(),
            source_files=source_files,
            first_date=first_date.isoformat(),
            last_date=last_date.isoformat(),
        )


def _dump_instrument(instrument: Instrument) -> dict[str, object]:
    return {
        "id": str(instrument.instrument_id),
        "first_seen": instrument.first_seen.isoformat() if instrument.first_seen else None,
        "last_seen": instrument.last_seen.isoformat() if instrument.last_seen else None,
        "tickers": [
            {
                "value": v.value,
                "from": v.valid_from.isoformat(),
                "to": v.valid_to.isoformat() if v.valid_to else None,
            }
            for v in instrument.tickers.versions()
        ],
        "isins": [
            {
                "value": v.value,
                "from": v.valid_from.isoformat(),
                "to": v.valid_to.isoformat() if v.valid_to else None,
            }
            for v in instrument.isins.versions()
        ],
        "lot_size": [
            {
                "value": v.value,
                "from": v.valid_from.isoformat(),
                "to": v.valid_to.isoformat() if v.valid_to else None,
            }
            for v in instrument.lot_size.versions()
        ],
    }


def save(registry: Registry, stamp: BuildStamp, path: Path = MASTER_PATH) -> Path:
    """Write the master as JSONL: a stamp line, then one instrument per line.

    Sorted, so two builds of identical data are byte-identical. Determinism is
    a project rule, and it also makes any diff meaningful.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps(
            {
                "_stamp": {
                    "built_at": stamp.built_at,
                    "source_files": stamp.source_files,
                    "first_date": stamp.first_date,
                    "last_date": stamp.last_date,
                    "schema_version": stamp.schema_version,
                }
            },
            sort_keys=True,
        )
    ]
    lines += [
        json.dumps(_dump_instrument(i), sort_keys=True)
        for i in sorted(registry, key=lambda i: str(i.instrument_id))
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def load(path: Path = MASTER_PATH) -> tuple[Registry, BuildStamp]:
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not lines:
        msg = f"{path} is empty"
        raise ValueError(msg)
    stamp_raw = json.loads(lines[0])["_stamp"]
    if stamp_raw.get("schema_version") != SCHEMA_VERSION:
        msg = (
            f"master schema is v{stamp_raw.get('schema_version')}, "
            f"this code expects v{SCHEMA_VERSION}; rebuild it"
        )
        raise ValueError(msg)

    registry = Registry()
    for line in lines[1:]:
        item = json.loads(line)
        instrument_id = InstrumentId(issuer=str(item["id"]))
        # Replay the versions as observations, in order, so the reconstructed
        # history is built by the same code path that built the original.
        events: list[tuple[date, str, str, int | None]] = []
        tickers = {v["from"]: v["value"] for v in item["tickers"]}
        isins = {v["from"]: v["value"] for v in item["isins"]}
        lots = {v["from"]: v["value"] for v in item.get("lot_size", [])}
        for when in sorted({*tickers, *isins, *lots}):
            events.append(
                (
                    date.fromisoformat(when),
                    tickers.get(when, ""),
                    isins.get(when, ""),
                    lots.get(when),
                )
            )
        last_ticker = last_isin = ""
        for when, ticker, isin, lot in events:
            last_ticker = ticker or last_ticker
            last_isin = isin or last_isin
            registry.observe(
                when,
                instrument_id=instrument_id,
                ticker=last_ticker,
                isin=last_isin,
                lot_size=lot,
            )
        instrument = registry.get(instrument_id)
        if instrument is not None:
            if item.get("first_seen"):
                instrument.first_seen = date.fromisoformat(str(item["first_seen"]))
            if item.get("last_seen"):
                instrument.last_seen = date.fromisoformat(str(item["last_seen"]))

    return registry, BuildStamp(**stamp_raw)
