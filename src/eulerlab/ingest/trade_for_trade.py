"""Which stocks traded trade-for-trade on each day, from the cash bhavcopies (research 174).

A stock in NSE's trade-for-trade segment (series BE or BZ) settles every trade
by delivery: it cannot be bought and sold, or shorted, within the day, so an
intraday (MIS) rule cannot trade it. The cash bhavcopy carries each row's
series, so the history is already landed (`nse/cm`, from 2015).

`make trade-for-trade` writes `data/derived/trade_for_trade.jsonl`, one line a
day: {"d": day, "t2t": [symbols in a non-EQ equity series]}. Resumable.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import csv
import io
import json
import zipfile
from datetime import date
from pathlib import Path

from eulerlab.paths import data_path

OUT = data_path("derived/trade_for_trade.jsonl")
MANIFEST = data_path("landing/nse/manifest.jsonl")
T2T_SERIES = frozenset({"BE", "BZ"})
SYMBOL_FIELDS = ("TckrSymb", "SYMBOL")
SERIES_FIELDS = ("SctySrs", "SERIES")


def t2t_symbols(payload: bytes) -> list[str]:
    """Symbols in a trade-for-trade series in one day's cash bhavcopy (either era)."""
    out: set[str] = set()
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = [n for n in archive.namelist() if n.lower().endswith(".csv")]
        if not names:
            return []
        with archive.open(names[0]) as handle:
            text = io.TextIOWrapper(handle, encoding="utf-8", errors="replace")
            for raw in csv.DictReader(text):
                row = {(k or "").strip(): (v or "").strip() for k, v in raw.items()}
                symbol = next((row[f] for f in SYMBOL_FIELDS if row.get(f)), "")
                series = next((row[f] for f in SERIES_FIELDS if row.get(f)), "")
                if symbol and series in T2T_SERIES:
                    out.add(symbol)
    return sorted(out)


def build(path: Path = OUT, workers: int = 8) -> int:
    """Read each missing day's cash bhavcopy once; returns the days that failed."""
    from eulerlab.ingest import landing_reader

    have: set[str] = set()
    if path.exists():
        have = {json.loads(x)["d"] for x in path.read_text(encoding="utf-8").splitlines() if x}
    entries = {}
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        entry = json.loads(line)
        if entry.get("segment") == "cm" and entry["trade_date"] not in have:
            entries[entry["trade_date"]] = entry["path"]

    def fetch(day: str) -> tuple[str, list[str] | None]:
        try:
            return day, t2t_symbols(landing_reader.read(f"nse/{entries[day]}", cache=False))
        except (FileNotFoundError, zipfile.BadZipFile, OSError):
            return day, None

    failed = 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with (
        cf.ThreadPoolExecutor(max_workers=workers) as pool,
        path.open("a", encoding="utf-8") as out,
    ):
        for day, found in pool.map(fetch, sorted(entries)):
            if found is None:
                failed += 1
                continue
            out.write(json.dumps({"d": day, "t2t": found}, separators=(",", ":")) + "\n")
    return failed


def load(path: Path = OUT) -> dict[date, frozenset[str]]:
    if not path.exists():
        return {}
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line:
            row = json.loads(line)
            out[date.fromisoformat(row["d"])] = frozenset(row["t2t"])
    return out


def main() -> int:
    parser = argparse.ArgumentParser(prog="trade-for-trade")
    parser.parse_args()
    failed = build()
    print(
        f"trade-for-trade: {len(load())} days in {OUT}; {failed} days failed (run again to retry)"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
