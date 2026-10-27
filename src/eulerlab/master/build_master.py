"""`make build-master` — build and persist the security master from B2."""

from __future__ import annotations

import concurrent.futures as cf
import json
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from eulerlab.env import require
from eulerlab.master.build import BuildStats, observe_day
from eulerlab.master.registry import Registry
from eulerlab.master.store import MASTER_PATH, BuildStamp, save
from eulerlab.master.symbology import build_symbol_map
from eulerlab.master.symbology import save as save_symbols

MANIFEST = Path("data/landing/nse/manifest.jsonl")
RENAMES_PATH = Path("config/symbol_renames.json")


def _client() -> object:
    import boto3  # here, not at the top: it costs 0.16 s on every import of the panel

    return boto3.client(
        "s3",
        endpoint_url="https://s3.us-west-004.backblazeb2.com",
        aws_access_key_id=require("B2_KEY_ID"),
        aws_secret_access_key=require("B2_APP_KEY"),
    )


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="build-master")
    parser.add_argument(
        "--cadence",
        choices=("monthly", "daily"),
        default="monthly",
        help="monthly brackets a rename to the month and reads 140 files; "
        "daily is exact and reads 2,800",
    )
    parser.add_argument("--out", type=Path, default=MASTER_PATH)
    args = parser.parse_args(argv)

    rows = [
        json.loads(line)
        for line in MANIFEST.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    cash = sorted((r for r in rows if r["segment"] == "cm"), key=lambda r: r["trade_date"])
    if args.cadence == "monthly":
        picked, seen = [], set()
        for row in cash:
            key = row["trade_date"][:7]
            if key not in seen:
                seen.add(key)
                picked.append(row)
    else:
        picked = cash

    print(f"building from {len(picked)} files ({args.cadence}), streaming from B2")
    client = _client()

    def fetch(row: dict[str, str]) -> tuple[dict[str, str], bytes]:
        body = client.get_object(Bucket="eulerdata", Key=f"nse/{row['path']}")["Body"].read()  # type: ignore[attr-defined]
        return row, body

    registry, stats = Registry(), BuildStats()
    with cf.ThreadPoolExecutor(max_workers=8) as pool:
        for row, body in sorted(pool.map(fetch, picked), key=lambda t: t[0]["trade_date"]):
            observe_day(registry, date.fromisoformat(row["trade_date"]), body, stats)

    print(f"  {stats.summary()}")
    print(f"  instruments: {len(registry)}")

    first = date.fromisoformat(picked[0]["trade_date"])
    last = date.fromisoformat(picked[-1]["trade_date"])
    stamp = BuildStamp.now(source_files=len(picked), first_date=first, last_date=last)
    out = save(registry, stamp, args.out)
    print(f"  written: {out} ({out.stat().st_size / 1e6:.1f} MB)")

    symbol_map = build_symbol_map(registry, last)
    unresolved_log = Path("data/landing/kite_minute/unresolved.jsonl")
    if unresolved_log.exists():
        stuck = sorted(
            {
                json.loads(line)["symbol"]
                for line in unresolved_log.read_text(encoding="utf-8").splitlines()
                if line.strip() and "not in Kite" in line
            }
        )
        symbol_map.unresolved = [s for s in stuck if symbol_map.current_name(s) is None]
    save_symbols(symbol_map, RENAMES_PATH)
    print(f"  renames: {len(symbol_map.renames)} -> {RENAMES_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
