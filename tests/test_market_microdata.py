"""NSE daily reports, Kite index minutes, the depth recorder and verified pruning."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import pyarrow.parquet as pq

from eulerlab.ingest import kite_index_minute, nse_reports
from eulerlab.ingest.depth_recorder import (
    PartWriter,
    nearest_future,
    parse_constituents,
    tick_row,
)
from eulerlab.ingest.fetch import Fetcher, FetchPolicy
from eulerlab.ingest.kite_minute import Chunk, MinuteStore, parse_instruments
from eulerlab.ingest.landing import Landing
from eulerlab.ingest.nse_eod import IST
from eulerlab.ingest.verified_prune import prune_verified

BULK = (
    '﻿"Date ","Symbol ","Security Name ","Client Name ","Buy / Sell ",'
    '"Quantity Traded ","Trade Price / Wght. Avg. Price ","Remarks "\n'
    '"01-OCT-2025","AFFORDABLE","Afford Robo & Auto Ltd","HARSHARAN SINGH KHERA",'
    '"SELL","70,000","243.18","-"\n'
).encode()
BAN = b"Securities in Ban For Trade Date 29-OCT-2026:\n1,KAYNES\n2,SAIL\n"
SLBM = (
    b"ABB INDIA LIMITED             ,ABB       ,XD,01-DEC-2026,N,0000001.00,0000006.99,"
    b"0000006.99,0000006.99,0000006.99,    ,            95,            664.05,0000050.00,"
    b"0000000.05,29-OCT-2026,       1\n"
)
HTML = b"<!DOCTYPE html><html><body>Service Unavailable</body></html>"


def _zip(name: str, text: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(name, text)
    return buffer.getvalue()


def test_each_check_accepts_its_report_and_refuses_an_error_page() -> None:
    reports = nse_reports.REPORTS
    assert reports["bulk_deals"].check(BULK) == 1
    assert reports["fo_ban"].check(BAN) == 2
    assert reports["slbm"].check(SLBM) == 1
    assert reports["mtf"].check(_zip("mrg_trading_29102026.csv", "a,b\n1,2\n")) == 2
    assert reports["insider"].check(json.dumps({"data": [{}, {}]}).encode()) == 2
    assert reports["ipo_past"].check(b"[{}]") == 1
    for name, report in reports.items():
        assert report.check(HTML) is None, name


def test_urls_use_nse_date_formats() -> None:
    day = date(2026, 10, 29)
    reports = nse_reports.REPORTS
    assert reports["fo_ban"].url(day).endswith("fo_secban_29102026.csv")
    assert reports["mtf"].url(day).endswith("mrg_trading_291026.zip")
    assert "from=29-10-2026&to=29-10-2026&csv=true" in reports["block_deals"].url(day)
    assert "from_date=29-10-2026&to_date=29-10-2026" in reports["insider"].url(day)


def test_a_day_counts_only_once_it_is_over() -> None:
    reports = nse_reports.REPORTS
    afternoon = datetime(2026, 10, 30, 16, 0, tzinfo=IST)
    night = datetime(2026, 10, 30, 21, 5, tzinfo=IST)
    assert nse_reports.last_complete_day(reports["bulk_deals"], afternoon) == date(2026, 10, 29)
    assert nse_reports.last_complete_day(reports["bulk_deals"], night) == date(2026, 10, 30)
    assert nse_reports.last_complete_day(reports["insider"], night) == date(2026, 10, 29)
    assert nse_reports.days_for(reports["pledges"], date(2020, 1, 1), afternoon) == [
        date(2026, 10, 30)
    ]


class FakeTransport:
    def __init__(self, answers: dict[str, tuple[int, bytes]]) -> None:
        self.answers = answers
        self.asked: list[str] = []

    def get(self, url: str, *, timeout: float) -> tuple[int, bytes]:
        self.asked.append(url)
        return self.answers.get(url, (404, b""))


def test_fetch_lands_once_and_never_again_even_after_pruning(tmp_path: Path) -> None:
    report = nse_reports.REPORTS["fo_ban"]
    day = date(2026, 10, 29)
    transport = FakeTransport({report.url(day): (200, BAN)})
    fetcher = Fetcher(transport, FetchPolicy(min_interval_s=0), sleep=lambda _s: None)
    landing = Landing(tmp_path)

    assert nse_reports.fetch_one(fetcher, landing, report, day) == "downloaded"
    entry = landing.entries()[(day.isoformat(), "fo_ban")]
    assert (tmp_path / entry.path).read_bytes() == BAN
    assert entry.sha256 == hashlib.sha256(BAN).hexdigest()

    (tmp_path / entry.path).chmod(0o644)
    (tmp_path / entry.path).unlink()  # what a verified prune does
    assert nse_reports.fetch_one(fetcher, Landing(tmp_path), report, day) == "skipped"
    assert len(transport.asked) == 1


def test_an_error_page_or_a_holiday_lands_nothing(tmp_path: Path) -> None:
    report = nse_reports.REPORTS["slbm"]
    good, holiday = date(2026, 10, 29), date(2026, 10, 2)
    transport = FakeTransport({report.url(good): (200, HTML)})
    fetcher = Fetcher(transport, FetchPolicy(min_interval_s=0), sleep=lambda _s: None)
    landing = Landing(tmp_path)
    assert nse_reports.fetch_one(fetcher, landing, report, good) == "malformed"
    assert nse_reports.fetch_one(fetcher, landing, report, holiday) == "absent"
    assert landing.entries() == {}


def test_index_tokens_come_from_the_shared_parser() -> None:
    payload = (
        b"instrument_token,tradingsymbol,instrument_type,exchange,segment\n"
        b"256265,NIFTY 50,EQ,NSE,INDICES\n"
        b"264969,INDIA VIX,EQ,NSE,INDICES\n"
    )
    tokens = parse_instruments(payload)
    assert tokens["NIFTY 50"] == 256265
    assert tokens["INDIA VIX"] == 264969


def test_index_backfill_uses_space_free_folders_and_reports_a_missing_index(
    tmp_path: Path,
) -> None:
    class FakeClient:
        def instruments(self, exchange: str = "NSE") -> dict[str, int]:
            return {"NIFTY 50": 256265, "INDIA VIX": 264969}

        def candles(self, chunk: Chunk, interval: str = "minute") -> list[list[object]]:
            return [["2026-10-29T09:15:00+0530", 1.0, 2.0, 0.5, 1.5, 0]]

    totals = kite_index_minute.backfill(
        FakeClient(), MinuteStore(tmp_path), end=date(2026, 10, 29), years=1, sleep_s=0
    )
    assert totals["missing"] == 1  # NIFTY BANK was not in the fake list
    assert totals["failed"] == 0
    assert {p.name for p in tmp_path.iterdir() if p.is_dir()} == {"NIFTY50", "INDIAVIX"}


def test_constituent_list_is_checked_before_it_is_trusted() -> None:
    header = "Company Name,Industry,Symbol,Series,ISIN Code\n"
    rows = "".join(f"Co {i},X,SYM{i},EQ,INE{i}\n" for i in range(50))
    assert len(parse_constituents((header + rows).encode())) == 50
    try:
        parse_constituents((header + "Co,X,ONE,EQ,INE\n").encode())
    except ValueError:
        pass
    else:
        raise AssertionError("a one-row list must be refused")


def test_nearest_future_skips_expired_and_options() -> None:
    today = date(2026, 10, 30)
    rows = [
        {
            "name": "NIFTY",
            "instrument_type": "FUT",
            "expiry": date(2026, 10, 28),
            "tradingsymbol": "OLD",
        },
        {
            "name": "NIFTY",
            "instrument_type": "FUT",
            "expiry": date(2026, 12, 29),
            "tradingsymbol": "DEC",
        },
        {
            "name": "NIFTY",
            "instrument_type": "FUT",
            "expiry": date(2026, 11, 24),
            "tradingsymbol": "NOV",
        },
        {
            "name": "NIFTY",
            "instrument_type": "CE",
            "expiry": date(2026, 11, 3),
            "tradingsymbol": "OPT",
        },
    ]
    assert nearest_future(rows, today)["tradingsymbol"] == "NOV"


def test_tick_row_flattens_five_levels_and_stamps_both_times(tmp_path: Path) -> None:
    exchange = datetime(2026, 10, 30, 10, 0, 1, tzinfo=IST)
    tick = {
        "instrument_token": 738561,
        "last_price": 1400.5,
        "last_traded_quantity": 3,
        "exchange_timestamp": exchange,
        "depth": {
            "buy": [{"price": 1400.4, "quantity": 10, "orders": 2}] * 5,
            "sell": [{"price": 1400.6, "quantity": 7, "orders": 1}] * 3,
        },
    }
    row = tick_row(tick, {738561: "RELIANCE"}, datetime(2026, 10, 30, 10, 0, 2, tzinfo=IST))
    assert row["symbol"] == "RELIANCE"
    assert row["event_time"] == "2026-10-30T10:00:01+05:30"
    assert row["knowledge_time"].endswith("+00:00")
    assert row["bid5_qty"] == 10
    assert row["ask3_price"] == 1400.6
    assert row["ask4_price"] is None

    writer = PartWriter(tmp_path, clock=lambda: datetime(2026, 10, 30, 10, 1, tzinfo=IST))
    writer.add([row])
    part = writer.flush()
    assert part is not None and part.parent.name == "2026-10-30"
    assert pq.read_table(part).num_rows == 1
    manifest = json.loads((tmp_path / "manifest.jsonl").read_text())
    assert manifest["sha256"] == hashlib.sha256(part.read_bytes()).hexdigest()
    assert writer.flush() is None


@dataclass
class FakeStore:
    objects: dict[str, bytes] = field(default_factory=dict)
    shas: dict[str, str] = field(default_factory=dict)

    def list_sizes(self, prefix: str) -> dict[str, int]:
        return {k: len(v) for k, v in self.objects.items() if k.startswith(prefix)}

    def head_sha256(self, key: str) -> str | None:
        return self.shas.get(key)

    def put(self, key: str, payload: bytes, sha256: str) -> None:
        self.objects[key], self.shas[key] = payload, sha256


def test_verified_prune_deletes_only_exact_copies(tmp_path: Path) -> None:
    tree = tmp_path / "nse_reports" / "fo_ban"
    tree.mkdir(parents=True)
    exact, wrong_hash, missing = tree / "a.csv", tree / "b.csv", tree / "c.csv"
    for path in (exact, wrong_hash, missing):
        path.write_bytes(path.name.encode())
    (tmp_path / "nse_reports" / "manifest.jsonl").write_text("{}\n")
    store = FakeStore()
    for path in (exact, wrong_hash):
        key = f"nse/{path.relative_to(tmp_path).as_posix()}"
        store.put(key, path.read_bytes(), hashlib.sha256(path.read_bytes()).hexdigest())
    store.shas[f"nse/{wrong_hash.relative_to(tmp_path).as_posix()}"] = "0" * 64

    result = prune_verified(tmp_path, "nse_reports", store, prefix="nse/")

    assert result.deleted == [exact]
    assert {p for p, _ in result.kept} == {wrong_hash, missing}
    assert not exact.exists() and wrong_hash.exists() and missing.exists()
    assert (tmp_path / "nse_reports" / "manifest.jsonl").exists()


def test_an_early_empty_api_answer_is_retried_not_locked_in(tmp_path: Path) -> None:
    report = nse_reports.REPORTS["short_selling"]
    day = date(2026, 10, 30)
    empty = b'\xef\xbb\xbf"Date ","Symbol ","Security Name ","Quantity "\n'
    transport = FakeTransport({report.url(day): (200, empty)})
    fetcher = Fetcher(transport, FetchPolicy(min_interval_s=0), sleep=lambda _s: None)
    landing = Landing(tmp_path)

    assert nse_reports.fetch_one(fetcher, landing, report, day, date(2026, 10, 31)) == "not-yet"
    assert landing.entries() == {}
    # Old enough: an empty day is a real answer and lands.
    assert nse_reports.fetch_one(fetcher, landing, report, day, date(2026, 11, 5)) == "downloaded"


def test_an_empty_file_landed_early_is_fetched_again_beside_it(tmp_path: Path) -> None:
    report = nse_reports.REPORTS["short_selling"]
    day = date(2026, 10, 30)
    landing = Landing(tmp_path)
    landing.write(
        trade_date=day,
        segment="short_selling",
        file_format="raw",
        url=report.url(day),
        payload=b"x",
        rows=0,
        inner_name="x",
        suffix="csv",
    )
    assert not nse_reports.landed(landing, day, "short_selling")
    full = b'"Date ","Symbol ","Security Name ","Quantity "\n"30-OCT-2026","SBIN","SBI","5"\n'
    transport = FakeTransport({report.url(day): (200, full)})
    fetcher = Fetcher(transport, FetchPolicy(min_interval_s=0), sleep=lambda _s: None)
    assert (
        nse_reports.fetch_one(fetcher, Landing(tmp_path), report, day, date(2026, 10, 31))
        == "downloaded"
    )
    entry = Landing(tmp_path).entries()[(day.isoformat(), "short_selling")]
    assert entry.rows == 1 and entry.path.endswith("_recheck.csv")
    assert nse_reports.landed(Landing(tmp_path), day, "short_selling")
