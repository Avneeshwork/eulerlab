"""`make nifty-options` — one compact file of every Nifty option and future, daily.

The F&O bhavcopy for each day (2015 onward, in B2) holds every derivative on
the exchange: about 0.4-1 MB zipped, of which Nifty is ~2,000 rows. The two
options strategies of research 070 need only those rows, across every day, so
reading 2,900 archives per backtest would be absurd. This reads each archive
once and keeps Nifty.

`data/derived/nifty_options.jsonl`, one line per trading day:

    {"d": "2025-03-03",
     "fut": [[expiry, close, settle, volume, oi, lot], ...],
     "opt": [[expiry, strike, "CE"|"PE", close, settle, volume, oi, lot], ...]}

`close` is the last traded price (null when the contract did not trade);
`settle` is the exchange's settlement price, populated for every listed
contract. A strategy that trades must use `close` where the contract traded;
`settle` is a mark, not a fill. `lot` is null before the UDiFF format (2024).

Resumable and idempotent: days already in the file are skipped, and each day is
appended as one line once its archive has been read. Archives are read from B2
directly, not cached into the landing zone, so a full run does not fill the disk.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import csv
import io
import json
import zipfile
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

from eulerlab.master.derivatives import ContractType, parse_legacy_row, parse_udiff_row
from eulerlab.options.chain import (
    CLOSE_FIELDS,
    LOT_FIELDS,
    OI_FIELDS,
    SETTLE_FIELDS,
    VOLUME_FIELDS,
    _number,
)

OUT = Path("data/derived/nifty_options.jsonl")
UNDERLYING = "NIFTY"


def _rows(payload: bytes) -> Iterator[dict[str, str]]:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = [n for n in archive.namelist() if n.lower().endswith(".csv")]
        if not names:
            return
        with archive.open(names[0]) as handle:
            text = io.TextIOWrapper(handle, encoding="utf-8", errors="replace")
            for raw in csv.DictReader(text):
                yield {(k or "").strip(): (v or "").strip() for k, v in raw.items()}


def extract(payload: bytes, day: str) -> dict[str, Any]:
    """The Nifty futures and options in one day's archive."""
    futures: list[list[Any]] = []
    options: list[list[Any]] = []
    for row in _rows(payload):
        contract = parse_udiff_row(row) or parse_legacy_row(row)
        if contract is None or contract.underlying != UNDERLYING:
            continue
        close = _number(row, CLOSE_FIELDS)
        volume = _number(row, VOLUME_FIELDS) or 0.0
        traded = close if close and volume > 0 else None
        settle = _number(row, SETTLE_FIELDS)
        oi = _number(row, OI_FIELDS) or 0.0
        lot = _number(row, LOT_FIELDS)
        expiry = contract.expiry.isoformat()
        if contract.contract_type is ContractType.FUTURE:
            futures.append([expiry, traded, settle, volume, oi, lot])
        elif contract.contract_type is ContractType.OPTION and contract.strike is not None:
            right = contract.right.value if contract.right else ""
            options.append([expiry, float(contract.strike), right, traded, settle, volume, oi, lot])
    futures.sort()
    options.sort()
    return {"d": day, "fut": futures, "opt": options}


def done_days(path: Path = OUT) -> set[str]:
    if not path.exists():
        return set()
    out = set()
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                out.add(json.loads(line[: line.index(",")] + "}")["d"])
    return out


def load(path: Path = OUT) -> list[dict[str, Any]]:
    """Every stored day, oldest first."""
    days: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                days.append(json.loads(line))
    return sorted(days, key=lambda d: d["d"])


def main(argv: Sequence[str] | None = None) -> int:
    import boto3

    from eulerlab.env import require
    from eulerlab.ingest import landing_reader

    parser = argparse.ArgumentParser(prog="nifty-options")
    parser.add_argument("--from", dest="start", default="2015-01-01")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args(argv)

    found = landing_reader.available("fo", "**/*.zip", allow_cloud=True)
    by_day = {p.rsplit("/", 1)[-1].split("_")[0]: p for p in found}
    have = done_days()
    todo = sorted(d for d in by_day if d >= args.start and d not in have)
    print(f"{len(by_day)} archives, {len(have)} days stored, {len(todo)} to read", flush=True)

    client = boto3.client(
        "s3",
        endpoint_url="https://s3.us-west-004.backblazeb2.com",
        aws_access_key_id=require("B2_KEY_ID"),
        aws_secret_access_key=require("B2_APP_KEY"),
    )

    def fetch(day: str) -> tuple[str, bytes | None, str]:
        path = by_day[day]
        local = landing_reader.LANDING_ROOT / path
        try:
            if local.exists():
                return day, local.read_bytes(), ""
            body = client.get_object(Bucket="eulerdata", Key=f"nse/{path}")["Body"].read()
            return day, body, ""
        except Exception as exc:  # one bad day must not stop the run
            return day, None, f"{type(exc).__name__}: {exc}"[:160]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    failed = 0
    with cf.ThreadPoolExecutor(max_workers=args.workers) as pool, OUT.open("a") as out:
        for i, (day, payload, problem) in enumerate(pool.map(fetch, todo), 1):
            if payload is None:
                failed += 1
                print(f"  {day}: {problem}", flush=True)
                continue
            out.write(json.dumps(extract(payload, day), separators=(",", ":")) + "\n")
            out.flush()
            if i % 100 == 0:
                print(f"  {i}/{len(todo)} {day}", flush=True)
    print(f"done: {len(todo) - failed} days added, {failed} failed (re-run to retry)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
