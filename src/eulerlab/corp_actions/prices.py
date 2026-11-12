"""The one piece of market data the dividend and rights adjustments need: the
close on the last cum date, per instrument.

Both bhavcopy eras carry it as a column on the ex-date's own row — `PREVCLOSE`
(legacy) or `PrvsClsgPric` (UDiFF) — so this needs no separate lookback to the
prior day's file, just the same day's cash bhavcopy the corporate-actions feed
already points at.

**The join is on `InstrumentId`, never on the raw ISIN string.** This is not
stylistic. The corporate-actions feed and the bhavcopy disagree about ISINs
for the same company on the same day: on 2017-11-21 the feed called Aurobindo
Pharma `INE406A01029` while the bhavcopy called it `INE406A01037`. Both are
correct — the trailing serial is reissued on a face-value change, and the two
sources refresh at different times. Joining on the full string silently lost
**21.9% of all price lookups**, which showed up as a suspiciously low coverage
number rather than as an error. `InstrumentId` keys company equity on the
issuer prefix, which is stable across the reissue (ADR-012), and that is
exactly the case it was built for.

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
import zipfile
from collections.abc import Callable, Iterator, Sequence
from datetime import date
from pathlib import Path

from eulerlab.corp_actions.adjust import ClosePriceLookup
from eulerlab.env import require
from eulerlab.ingest.landing import ManifestEntry
from eulerlab.master.identity import InstrumentId, NotAnIsin
from eulerlab.paths import data_path

SYMBOL_FIELDS = ("TckrSymb", "SYMBOL")
ISIN_FIELDS = ("ISIN",)
PREV_CLOSE_FIELDS = ("PrvsClsgPric", "PREVCLOSE")
CLOSE_FIELDS = ("ClsPric", "CLOSE")


def _first(row: dict[str, str], names: tuple[str, ...]) -> str:
    for name in names:
        value = row.get(name)
        if value:
            return value.strip()
    return ""


def instrument_key(isin: str) -> str | None:
    """The internal join key for an ISIN, or None if it is not a valid one.

    Wraps `InstrumentId` so every join in this module goes through the one
    rule, rather than each call site deciding for itself how much of the ISIN
    to compare.
    """
    try:
        return str(InstrumentId.from_isin(isin))
    except NotAnIsin:
        return None


def parse_prev_closes(payload: bytes) -> dict[str, float]:
    """One cash bhavcopy -> {instrument_key: previous close}, either era."""
    out: dict[str, float] = {}
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = [n for n in archive.namelist() if n.lower().endswith(".csv")]
        if not names:
            return out
        with archive.open(names[0]) as handle:
            text = io.TextIOWrapper(handle, encoding="utf-8", errors="replace")
            for raw in csv.DictReader(text):
                row = {(k or "").strip(): (v or "").strip() for k, v in raw.items()}
                key = instrument_key(_first(row, ISIN_FIELDS))
                prev = _first(row, PREV_CLOSE_FIELDS)
                if key and prev:
                    try:
                        out[key] = float(prev)
                    except ValueError:
                        continue
    return out


def parse_closes(payload: bytes) -> dict[str, tuple[float, float]]:
    """One cash bhavcopy -> {instrument_key: (previous_close, close)}.

    Both closes, unlike `parse_prev_closes`, because validating a corporate
    action against real prices needs the cum-date close *and* the ex-date
    close to see the drop the adjustment is supposed to remove.
    """
    out: dict[str, tuple[float, float]] = {}
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = [n for n in archive.namelist() if n.lower().endswith(".csv")]
        if not names:
            return out
        with archive.open(names[0]) as handle:
            text = io.TextIOWrapper(handle, encoding="utf-8", errors="replace")
            for raw in csv.DictReader(text):
                row = {(k or "").strip(): (v or "").strip() for k, v in raw.items()}
                key = instrument_key(_first(row, ISIN_FIELDS))
                prev = _first(row, PREV_CLOSE_FIELDS)
                close = _first(row, CLOSE_FIELDS)
                if not (key and prev and close):
                    continue
                try:
                    out[key] = (float(prev), float(close))
                except ValueError:
                    continue
    return out


CACHE_PATH = data_path("derived/close_index.jsonl")


class TransactionCapExceeded(RuntimeError):
    """B2's daily download allowance is spent.

    A distinct type because this is an expected, self-healing condition, not a
    defect: the operator has done nothing wrong and there is nothing to debug.
    A twenty-line boto traceback implies otherwise and buries the one fact
    that matters, which is that the work already done was saved.
    """


def _is_cap_error(exc: BaseException) -> bool:
    return "cap exceeded" in str(exc).lower()


def _stop_cleanly_on_cap(
    results: Iterator[tuple[str, bytes]], total: int
) -> Iterator[tuple[str, bytes]]:
    """Yield fetch results, converting the cap error into a clear message.

    Once the cap is hit every remaining request fails the same way, so
    stopping is correct — there is nothing to retry until tomorrow.

    The count is exact rather than approximate: the consumer writes each day
    to the cache and flushes before asking for the next, so when this raises
    on item N+1 exactly N days are durably cached.
    """
    yielded = 0
    try:
        for item in results:
            yield item
            yielded += 1
    except Exception as exc:
        if not _is_cap_error(exc):
            raise
        msg = (
            f"B2 daily download cap reached after {yielded:,} of {total:,} files.\n"
            f"Everything fetched so far is saved in {CACHE_PATH}; re-running "
            f"tomorrow resumes from there and re-downloads nothing.\n"
            f"See docs/RUNBOOKS/b2-transaction-cap.md."
        )
        raise TransactionCapExceeded(msg) from exc


def _read_cache(path: Path) -> tuple[dict[tuple[str, str], float], set[str]]:
    """Returns (prices, dates already processed)."""
    index: dict[tuple[str, str], float] = {}
    done: set[str] = set()
    if not path.exists():
        return index, done
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            row = json.loads(line)
            done.add(row["d"])
            if "k" in row:
                index[(row["k"], row["d"])] = row["p"]
    return index, done


def build_close_index(
    entries: Sequence[ManifestEntry],
    *,
    needed: set[tuple[str, str]] | None = None,
    bucket: str = "eulerdata",
    max_workers: int = 8,
    progress: Callable[[int, int], None] | None = None,
    cache_path: Path | None = CACHE_PATH,
) -> dict[tuple[str, str], float]:
    """{(instrument_key, trade_date_iso): previous_close} for the given files.

    `needed` restricts what is *kept*, and it matters enormously. The full
    2015-2026 cash history is roughly 5.7M (instrument, date) pairs, but the
    adjustment engine only ever asks about instruments on their own ex-dates —
    about 15,300 pairs, three orders of magnitude fewer. Without the filter
    this would hold a gigabyte of prices that nothing reads.

    Filter the `entries` list itself to cut the *download* as well; keeping
    only the ex-dates takes it from 2,870 files to 2,121.

    **The cache is not an optimisation, it is a cost control.** Backblaze's
    free tier allows 2,500 Class B (download) transactions per day, and one
    full build is 2,121 of them — 85% of a day's allowance in a single run.
    The second run of this build in one session exhausted the cap outright and
    failed with AccessDenied. So every parsed day is appended to `cache_path`
    as it completes: the expensive pull happens once, an interrupted or capped
    run resumes where it stopped rather than starting over, and every
    subsequent rebuild costs nothing. See
    `docs/RUNBOOKS/b2-transaction-cap.md`.

    Dates that yielded no needed price still get a marker row, so a legitimately
    empty day is not re-downloaded forever.
    """
    index: dict[tuple[str, str], float] = {}
    already: set[str] = set()
    if cache_path is not None:
        index, already = _read_cache(cache_path)

    remaining = [e for e in entries if e.trade_date not in already]
    if not remaining:
        return index

    import boto3  # here, not at the top: it costs 0.16 s on every import of the panel

    client = boto3.client(
        "s3",
        endpoint_url="https://s3.us-west-004.backblazeb2.com",
        aws_access_key_id=require("B2_KEY_ID"),
        aws_secret_access_key=require("B2_APP_KEY"),
    )

    def fetch(entry: ManifestEntry) -> tuple[str, bytes]:
        body = client.get_object(Bucket=bucket, Key=f"nse/{entry.path}")["Body"].read()
        return entry.trade_date, body

    handle = None
    if cache_path is not None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        handle = cache_path.open("a", encoding="utf-8")

    done = 0
    try:
        with cf.ThreadPoolExecutor(max_workers=max_workers) as pool:
            results = pool.map(fetch, remaining)
            for trade_date, body in _stop_cleanly_on_cap(results, len(remaining)):
                for key_isin, prev_close in parse_prev_closes(body).items():
                    key = (key_isin, trade_date)
                    if needed is None or key in needed:
                        index[key] = prev_close
                        if handle is not None:
                            handle.write(
                                json.dumps(
                                    {"d": trade_date, "k": key_isin, "p": prev_close},
                                    sort_keys=True,
                                )
                                + "\n"
                            )
                if handle is not None:
                    # Marker: this day is processed even if it held nothing we
                    # wanted, so it is never re-downloaded.
                    handle.write(json.dumps({"d": trade_date, "done": True}) + "\n")
                    handle.flush()
                done += 1
                if progress is not None:
                    progress(done, len(remaining))
    finally:
        if handle is not None:
            handle.close()
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
    """Adapt the index to `adjust.ClosePriceLookup`'s isin/date signature.

    Callers pass whatever ISIN their source gave them; the normalisation to
    `InstrumentId` happens here, so a caller cannot forget it.
    """

    def lookup(isin: str, trade_date: date) -> float | None:
        key = instrument_key(isin)
        return index.get((key, trade_date.isoformat())) if key else None

    return lookup
