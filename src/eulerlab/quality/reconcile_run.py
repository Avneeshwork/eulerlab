"""`make reconcile` — compare NSE's official close against Kite's minute bars.

The only check in this project that compares two vendors who never spoke to
each other. Every other check asks whether one source is internally
plausible; this one asks whether two independent accounts of the same
instrument-day agree, so a disagreement is evidence rather than a threshold.

Kite covers 420 symbols against bhavcopy's ~2,000, so the comparison is
restricted to the overlap and coverage is reported separately — see
`reconcile.py` for why absent symbols are not findings.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import io
import json
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from eulerlab.quality.findings import Report, Severity
from eulerlab.quality.reconcile import coverage_summary, reconcile_day
from eulerlab.quality.row_checks import Bar
from eulerlab.quality.sources import bars_from_bhavcopy, daily_bar_from_minutes

NSE_MANIFEST = Path("data/landing/nse/manifest.jsonl")
MINUTE_MANIFEST = Path("data/landing/kite_minute/manifest.jsonl")


def _client() -> object:
    import boto3

    from eulerlab.env import require

    return boto3.client(
        "s3",
        endpoint_url="https://s3.us-west-004.backblazeb2.com",
        aws_access_key_id=require("B2_KEY_ID"),
        aws_secret_access_key=require("B2_APP_KEY"),
    )


def _rows(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def minute_chunks_covering(day: date, *, limit: int) -> list[tuple[str, str]]:
    """(symbol, path) for minute chunks whose window contains `day`.

    One chunk spans weeks, so a single day needs one file per symbol rather
    than one per symbol-day — which is what makes this affordable at all.
    """
    out: list[tuple[str, str]] = []
    iso = day.isoformat()
    for row in _rows(MINUTE_MANIFEST):
        n_rows = row.get("rows", 0)
        if not isinstance(n_rows, int) or n_rows <= 0:
            # An empty chunk is legitimate (it predates the listing, S-008) but
            # has nothing to reconcile against.
            continue
        if str(row.get("start", "")) <= iso <= str(row.get("end", "")):
            out.append((str(row["symbol"]), str(row["path"])))
        if len(out) >= limit:
            break
    return out


def daily_bars_from_minute_chunk(payload: bytes, symbol: str, day: date) -> Bar | None:
    """Aggregate the minutes belonging to `day` out of a multi-week chunk."""
    import pyarrow.parquet as pq

    table = pq.read_table(io.BytesIO(payload))
    stamps = table.column("ts").to_pylist()
    opens = table.column("open").to_pylist()
    highs = table.column("high").to_pylist()
    lows = table.column("low").to_pylist()
    closes = table.column("close").to_pylist()
    volumes = table.column("volume").to_pylist()

    prefix = day.isoformat()
    minutes: list[tuple[float, float, float, float, float]] = []
    for i, stamp in enumerate(stamps):
        if not str(stamp).startswith(prefix):
            continue
        o, h, low, c, v = opens[i], highs[i], lows[i], closes[i], volumes[i]
        if o is None or h is None or low is None or c is None or v is None:
            # A null OHLC row cannot be aggregated and defaulting it to zero
            # would drag the day's low to zero and manufacture a finding.
            continue
        minutes.append((float(o), float(h), float(low), float(c), float(v)))
    return daily_bar_from_minutes(symbol, day, minutes)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="reconcile", description=__doc__)
    parser.add_argument("--days", type=int, default=2, help="recent trading days to compare")
    parser.add_argument("--symbols", type=int, default=120, help="cap on symbols per day")
    parser.add_argument("--limit", type=int, default=25)
    args = parser.parse_args(argv)

    cash = sorted(
        {
            str(r["trade_date"]): str(r["path"])
            for r in _rows(NSE_MANIFEST)
            if r.get("segment") == "cm"
        }.items(),
        reverse=True,
    )[: args.days]
    if not cash:
        print("no cash bhavcopy in the manifest")
        return 0

    client = _client()

    def get(key: str) -> bytes:
        body = client.get_object(Bucket="eulerdata", Key=f"nse/{key}")["Body"].read()  # type: ignore[attr-defined]
        return bytes(body)

    report = Report()
    for trade_date, path in cash:
        day = date.fromisoformat(trade_date)
        official = list(bars_from_bhavcopy(get(path), day))

        chunks = minute_chunks_covering(day, limit=args.symbols)
        print(
            f"{trade_date}: {len(official):,} bhavcopy bars, {len(chunks)} minute chunks to fetch"
        )

        others: list[Bar] = []
        with cf.ThreadPoolExecutor(max_workers=8) as pool:
            futures = {pool.submit(get, f"kite_minute/{p}"): symbol for symbol, p in chunks}
            for future in cf.as_completed(futures):
                symbol = futures[future]
                bar = daily_bars_from_minute_chunk(future.result(), symbol, day)
                if bar is not None:
                    others.append(bar)

        print(f"  {len(others)} symbols aggregated from minute data")
        report.add(coverage_summary(official, others))
        report.extend(reconcile_day(official, others))

    print(report.render(limit=args.limit))
    return 1 if report.count(Severity.ERROR) else 0


if __name__ == "__main__":
    raise SystemExit(main())
