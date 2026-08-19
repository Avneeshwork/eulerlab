"""The one piece of market data the dividend adjustment needs: the close the
day before an ex-date, per ISIN.

Both bhavcopy eras carry it as a column on the ex-date's own row — `PREVCLOSE`
(legacy) or `PrvsClsgPric` (UDiFF) — so this needs no separate lookback to the
prior day's file, just the same day's cash bhavcopy the corporate-actions feed
already points at.

Streams from B2 rather than requiring local files, the same pattern
`eulerlab.master.build_master` uses, because the landing zone is pruned after
upload (ADR-010) and the local copy of eleven years of bhavcopy will usually
not be present.
"""

from __future__ import annotations

import concurrent.futures as cf
import csv
import io
import json
import os
import zipfile
from collections.abc import Sequence
from datetime import date
from pathlib import Path

import boto3

from eulerlab.corp_actions.adjust import ClosePriceLookup
from eulerlab.ingest.landing import ManifestEntry

SYMBOL_FIELDS = ("TckrSymb", "SYMBOL")
ISIN_FIELDS = ("ISIN",)
PREV_CLOSE_FIELDS = ("PrvsClsgPric", "PREVCLOSE")


def _first(row: dict[str, str], names: tuple[str, ...]) -> str:
    for name in names:
        value = row.get(name)
        if value:
            return value.strip()
    return ""


def parse_prev_closes(payload: bytes) -> dict[str, float]:
    """One cash bhavcopy -> {isin: previous close}, either era."""
    out: dict[str, float] = {}
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = [n for n in archive.namelist() if n.lower().endswith(".csv")]
        if not names:
            return out
        with archive.open(names[0]) as handle:
            text = io.TextIOWrapper(handle, encoding="utf-8", errors="replace")
            for raw in csv.DictReader(text):
                row = {(k or "").strip(): (v or "").strip() for k, v in raw.items()}
                isin = _first(row, ISIN_FIELDS)
                prev = _first(row, PREV_CLOSE_FIELDS)
                if isin and prev:
                    try:
                        out[isin] = float(prev)
                    except ValueError:
                        continue
    return out


def build_close_index(
    entries: Sequence[ManifestEntry], *, bucket: str = "eulerdata", max_workers: int = 8
) -> dict[tuple[str, str], float]:
    """{(isin, trade_date_iso): previous_close} across every cash bhavcopy given.

    One request per file, threaded. For the full 2015-2026 cash history that
    is 2,869 requests - the same order of cost as `make build-master
    --cadence daily`, which this project has already run at this scale.
    """
    client = boto3.client(
        "s3",
        endpoint_url="https://s3.us-west-004.backblazeb2.com",
        aws_access_key_id=os.environ["B2_KEY_ID"],
        aws_secret_access_key=os.environ["B2_APP_KEY"],
    )

    def fetch(entry: ManifestEntry) -> tuple[str, bytes]:
        body = client.get_object(Bucket=bucket, Key=f"nse/{entry.path}")["Body"].read()
        return entry.trade_date, body

    index: dict[tuple[str, str], float] = {}
    with cf.ThreadPoolExecutor(max_workers=max_workers) as pool:
        for trade_date, body in pool.map(fetch, entries):
            for isin, prev_close in parse_prev_closes(body).items():
                index[(isin, trade_date)] = prev_close
    return index


def cash_entries(manifest_path: Path) -> list[ManifestEntry]:
    """Every `cm` segment row from the nse manifest, for `build_close_index`."""
    rows = [
        json.loads(line)
        for line in manifest_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return sorted(
        (ManifestEntry.from_json(r) for r in rows if r["segment"] == "cm"),
        key=lambda e: e.trade_date,
    )


def close_price_lookup(index: dict[tuple[str, str], float]) -> ClosePriceLookup:
    """Adapt the index to `adjust.ClosePriceLookup`'s isin/date signature."""

    def lookup(isin: str, trade_date: date) -> float | None:
        return index.get((isin, trade_date.isoformat()))

    return lookup
