"""Reading minute candles, from B2 with a local cache.

The minute bars are 13,501 Parquet files in B2 under `nse/kite_minute/SYMBOL/`,
chunked roughly two months at a time. They are **not** in the NSE manifest, so
`restore_local` cannot see them — it walks the manifest, and the manifest only
covers the bhavcopy trees. That gap is why the Tweezer strategy shipped without
ever meeting real data.

This reads them directly. B2 is the storage of record and downloads are cheap,
so the pattern here is fetch-on-demand with a local cache rather than a bulk
restore: ask for a symbol, get its candles, and keep the Parquet locally so the
second ask is free.

**Session boundaries are computed, not assumed.** A trading day is whatever
timestamps actually appear in the data for that date. Hardcoding 09:15-15:30
would silently mis-handle the muhurat sessions, the 2020 truncated days, and
any early close — and an intraday strategy that closes "at the session end"
would then close at the wrong minute.
"""

from __future__ import annotations

import os
from collections.abc import Iterator, Sequence
from datetime import date, datetime

from eulerlab.env import load_env, require
from eulerlab.intraday.tweezer import IST, Candle
from eulerlab.paths import data_path

BUCKET = "eulerdata"
PREFIX = "nse/kite_minute"
ENDPOINT = "https://s3.us-west-004.backblazeb2.com"
CACHE = data_path("landing/kite_minute")


def _client() -> object:
    import boto3

    load_env()
    return boto3.client(
        "s3",
        endpoint_url=ENDPOINT,
        aws_access_key_id=require("B2_KEY_ID"),
        aws_secret_access_key=require("B2_APP_KEY"),
    )


def available_symbols(client: object | None = None) -> list[str]:
    """Every symbol with minute data in B2."""
    client = client or _client()
    paginator = client.get_paginator("list_objects_v2")  # type: ignore[attr-defined]
    found: set[str] = set()
    for page in paginator.paginate(Bucket=BUCKET, Prefix=f"{PREFIX}/", Delimiter="/"):
        for item in page.get("CommonPrefixes", []):
            found.add(item["Prefix"].rstrip("/").split("/")[-1])
    return sorted(found)


def _keys_for(symbol: str, client: object) -> list[str]:
    paginator = client.get_paginator("list_objects_v2")  # type: ignore[attr-defined]
    keys: list[str] = []
    for page in paginator.paginate(Bucket=BUCKET, Prefix=f"{PREFIX}/{symbol}/"):
        keys.extend(
            obj["Key"] for obj in page.get("Contents", []) if obj["Key"].endswith(".parquet")
        )
    return sorted(keys)


def _overlaps(key: str, start: date | None, end: date | None) -> bool:
    """Chunk filenames are `START_END.parquet`, so a range can be skipped whole.

    Falls back to including the file when the name does not parse. Reading one
    chunk too many costs a download; skipping one that was needed produces a
    silent hole in the series, and a strategy cannot tell a hole from a quiet
    market.
    """
    stem = key.rsplit("/", 1)[-1].removesuffix(".parquet")
    try:
        first, last = stem.split("_")
        chunk_start = date.fromisoformat(first)
        chunk_end = date.fromisoformat(last)
    except ValueError:
        return True
    if start and chunk_end < start:
        return False
    return not (end and chunk_start > end)


def fetch(symbol: str, *, start: date | None = None, end: date | None = None) -> list[Candle]:
    """All minute candles for `symbol`, downloading what is not cached.

    **One bar per timestamp**, which is not what concatenating the chunks
    gives. The archive's 60-day windows overlap: `NIFTYBEES` on 2026-06-02 is
    covered by three separate files (04-21→06-19, 04-23→06-21, 05-25→07-23),
    so a naive read returned every minute of that day three times — 1,125 rows
    for a 375-minute session.

    That is not a cosmetic duplicate. Every indicator here counts bars, so a
    60-period mean covered twenty real minutes instead of sixty, ATR and the
    volume z-score were computed over a third of their intended window, and
    session volume was tripled. Any NSE intraday result produced before this
    was measuring a signal with its lookbacks silently divided by three.

    Where two chunks disagree about a bar the **later** one wins. Keys sort by
    start date, so the last chunk containing a timestamp is the most recently
    fetched, and a re-fetch is more likely to be a correction than a
    regression.
    """
    import pyarrow.parquet as pq

    client = _client()
    out: list[Candle] = []
    for key in _keys_for(symbol, client):
        if not _overlaps(key, start, end):
            continue
        local = CACHE / key.removeprefix(f"{PREFIX}/")
        if not local.exists():
            local.parent.mkdir(parents=True, exist_ok=True)
            body = client.get_object(Bucket=BUCKET, Key=key)["Body"].read()  # type: ignore[attr-defined]
            local.write_bytes(body)

        table = pq.read_table(local)
        columns = {name: table.column(name).to_pylist() for name in table.column_names}
        for index in range(table.num_rows):
            row: dict[str, object] = {n: columns[n][index] for n in table.column_names}
            prices = [row.get(n) for n in ("open", "high", "low", "close")]
            if any(p is None for p in prices):
                # A null OHLC field is a hole in the vendor's data, not a quiet
                # zero. Dropping the bar is right; substituting 0.0 would create
                # an enormous fake range and manufacture patterns.
                continue
            stamp = _parse(row["ts"])
            if start and stamp.date() < start:
                continue
            if end and stamp.date() > end:
                continue
            out.append(
                Candle(
                    ts=stamp,
                    open=float(prices[0]),  # type: ignore[arg-type]
                    high=float(prices[1]),  # type: ignore[arg-type]
                    low=float(prices[2]),  # type: ignore[arg-type]
                    close=float(prices[3]),  # type: ignore[arg-type]
                    volume=float(row.get("volume") or 0.0),  # type: ignore[arg-type]
                )
            )
    # Deduplicated before sorting, keeping the last occurrence: `_keys_for`
    # yields chunks in start-date order, so "last" is the newest file that
    # covers the bar.
    by_stamp: dict[datetime, Candle] = {}
    for candle in out:
        by_stamp[candle.ts] = candle
    out = list(by_stamp.values())
    out.sort(key=lambda c: c.ts)
    return out


def _parse(raw: object) -> datetime:
    """Kite timestamps carry an offset. Normalised to IST, never left naive."""
    stamp = raw if isinstance(raw, datetime) else datetime.fromisoformat(str(raw))
    if stamp.tzinfo is None:
        return stamp.replace(tzinfo=IST)
    return stamp.astimezone(IST)


def by_session(candles: Sequence[Candle]) -> Iterator[tuple[date, list[Candle]]]:
    """Group into trading days, in order.

    The session's own candles define its boundaries. Nothing here assumes
    09:15-15:30, because muhurat sessions and early closes are real and an
    intraday strategy that closes "at the end" must close at the actual end.
    """
    current: list[Candle] = []
    day: date | None = None
    for candle in candles:
        stamp_day = candle.ts.date()
        if day is not None and stamp_day != day:
            yield day, current
            current = []
        day = stamp_day
        current.append(candle)
    if day is not None and current:
        yield day, current


def resample(candles: Sequence[Candle], minutes: int) -> list[Candle]:
    """Minute candles rolled up into `minutes`-minute candles, per session.

    Buckets start at each session's first candle — 09:15 on a normal NSE day —
    so a 60-minute chart reads 09:15, 10:15, ... 14:15 and a short last bar
    15:15-15:29, as Kite draws it. Anchoring to the clock hour instead would
    give a 45-minute first bar. A bucket's timestamp is its start; open is its
    first open, close its last close, high and low the extremes, volume the sum.
    """
    if minutes <= 1:
        return list(candles)
    out: list[Candle] = []
    for _day, session in by_session(candles):
        anchor = session[0].ts
        bucket: list[Candle] = []
        bucket_index = -1
        for candle in session:
            index = int((candle.ts - anchor).total_seconds() // 60) // minutes
            if index != bucket_index and bucket:
                out.append(_roll(bucket, anchor, bucket_index, minutes))
                bucket = []
            bucket_index = index
            bucket.append(candle)
        if bucket:
            out.append(_roll(bucket, anchor, bucket_index, minutes))
    return out


def _roll(bucket: list[Candle], anchor: datetime, index: int, minutes: int) -> Candle:
    from datetime import timedelta

    return Candle(
        ts=anchor + timedelta(minutes=index * minutes),
        open=bucket[0].open,
        high=max(c.high for c in bucket),
        low=min(c.low for c in bucket),
        close=bucket[-1].close,
        volume=sum(c.volume for c in bucket),
    )


def cached_size() -> tuple[int, float]:
    """Files and gigabytes currently on disk, for reporting before a prune."""
    if not CACHE.exists():
        return (0, 0.0)
    files = list(CACHE.rglob("*.parquet"))
    return (len(files), sum(f.stat().st_size for f in files) / 1e9)


def prune() -> tuple[int, float]:
    """Delete the local cache. B2 keeps the originals.

    The operator does not want market data accumulating on their laptop, and
    every file here can be fetched again freely.
    """
    files, gigabytes = cached_size()
    for path in CACHE.rglob("*.parquet"):
        os.remove(path)
    return (files, gigabytes)
