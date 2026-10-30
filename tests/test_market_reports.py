"""The Deals & filings summary: each parser on NSE's real shapes, and the build."""

from __future__ import annotations

import io
import json
import zipfile
from datetime import date
from pathlib import Path

from eulerlab import market_reports as mr
from eulerlab.ingest.landing import Landing, ManifestEntry

BULK = (
    '﻿"Date ","Symbol ","Security Name ","Client Name ","Buy / Sell ",'
    '"Quantity Traded ","Trade Price / Wght. Avg. Price ","Remarks "\n'
    '"30-OCT-2026","AAA","Aaa Ltd","FUND ONE","BUY","10,00,000","100.00","-"\n'
    '"30-OCT-2026","BBB","Bbb Ltd","FUND TWO","SELL","5,00,000","400.00","-"\n'
).encode()
BLOCK_EMPTY = (
    '﻿"Date ","Symbol ","Security Name ","Client Name ","Buy / Sell ",'
    '"Quantity Traded ","Trade Price / Wght. Avg. Price ","Remarks "'
).encode()
MTF_CSV = (
    "SEBI REPORT AS ON Reporting date 23-OCT-2026,,,\n,,,\nSr.No.,Particulars,Rs. In Lakhs ,\n"
    "1,Scripwise Total Outstanding on the beginning of the day,14643905.83,\n"
    "2,Fresh Exposure taken during the day,277213.20,\n"
    "3,Exposure liquidated during the day,543815.72,\n"
    "4,Net scripwise outstanding at the end of the day,14377303.30,\n,,,\n"
    "Symbol,Name,Qty Fin by all the members(No.of Shares),Amt Fin by all the members(Rs. In Lakhs)\n"
    "HDFCBANK,HDFC BANK LTD,1000,{amount}\n"
)
SLBM = (
    b"ABB INDIA LIMITED             ,ABB       ,XD,01-DEC-2026,N,0000002.51,0000000.05,"
    b"0000000.05,0000000.05,0000000.05,    ,             7,              0.35,0000050.00,"
    b"0000000.05,23-OCT-2026,       1\n"
    b"ABB INDIA LIMITED             ,ABB       ,X1,05-JAN-2027,N,0000002.51,0000000.80,"
    b"0000000.80,0000000.80,0000000.80,    ,             3,              2.40,0000050.00,"
    b"0000000.05,23-OCT-2026,       1\n"
)


def _zip(text: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("mrg_trading_23102026.csv", text)
    return buffer.getvalue()


def test_deal_values_are_quantity_times_price_in_crore() -> None:
    rows = mr.parse_deals(BULK, "bulk")
    assert [r["value_cr"] for r in rows] == [10.0, 20.0]
    assert rows[1]["side"] == "SELL"
    assert mr.parse_deals(BLOCK_EMPTY, "block") == []


def test_mtf_reads_the_totals_and_the_stock_table() -> None:
    parsed = mr.parse_mtf(_zip(MTF_CSV.format(amount="3000.00")))
    assert parsed["totals"]["closing"] == 14377303.30
    assert parsed["stocks"]["HDFCBANK"] == {"qty": 1000.0, "lakh": 3000.0}


def test_slbm_adds_series_and_keeps_the_highest_fee() -> None:
    assert mr.parse_slbm(SLBM) == {"ABB": {"qty": 10.0, "fee": 0.80}}


def test_pledges_use_the_promoter_fields_not_every_pledge() -> None:
    payload = json.dumps(
        {
            "data": [
                {
                    "comName": "Afcons",
                    "percPromoterShares": " 100.00",
                    "percTotShares": " 50.17",
                    "percPromoterHolding": " 50.17",
                    "percSharesPledged": "53.03",
                    "shp": "30-Sep-2026",
                },
                {
                    "comName": "Clean",
                    "percPromoterShares": "  0.00",
                    "percTotShares": "0",
                    "percPromoterHolding": "45",
                    "percSharesPledged": "4.57",
                    "shp": "30-Sep-2026",
                },
            ]
        }
    ).encode()
    rows = mr.parse_pledges(payload)
    assert [r["company"] for r in rows] == ["Afcons"]
    assert rows[0]["of_company_pct"] == 50.17


def _land(landing: Landing, name: str, day: str, payload: bytes, rows: int, suffix: str) -> None:
    landing.write(
        trade_date=date.fromisoformat(day),
        segment=name,
        file_format="raw",
        url=f"https://example/{name}",
        payload=payload,
        rows=rows,
        inner_name=name,
        suffix=suffix,
    )


def test_summary_builds_each_section_and_reports_what_is_missing(tmp_path: Path) -> None:
    landing = Landing(tmp_path)
    _land(landing, "bulk_deals", "2026-10-30", BULK, 2, "csv")
    _land(landing, "block_deals", "2026-10-30", BLOCK_EMPTY, 0, "csv")
    _land(
        landing,
        "fo_ban",
        "2026-10-29",
        b"Securities in Ban For Trade Date 29-OCT-2026:\n1,SAIL\n",
        1,
        "csv",
    )
    _land(
        landing,
        "fo_ban",
        "2026-10-30",
        b"Securities in Ban For Trade Date 30-OCT-2026:\n1,KAYNES\n",
        1,
        "csv",
    )
    _land(landing, "mtf", "2026-10-23", _zip(MTF_CSV.format(amount="10000.00")), 9, "zip")
    _land(landing, "mtf", "2026-10-30", _zip(MTF_CSV.format(amount="12000.00")), 9, "zip")

    read = mr.reader(tmp_path)
    summary = mr.summarise(landing, read)

    assert summary["deals"]["available"]
    assert summary["deals"]["buyers"][0]["client"] == "FUND ONE"
    assert summary["deals"]["sellers"][0]["net_cr"] == -20.0
    assert summary["ban"]["added"] == ["KAYNES"] and summary["ban"]["removed"] == ["SAIL"]
    assert summary["mtf"]["rising"][0] == {"symbol": "HDFCBANK", "cr": 120.0, "change": 0.2}
    assert not summary["pledges"]["available"]
    assert not summary["ipos"]["available"]


def test_the_reader_prefers_the_local_file(tmp_path: Path) -> None:
    landing = Landing(tmp_path)
    _land(landing, "fo_ban", "2026-10-30", b"x", 0, "csv")
    entry: ManifestEntry = next(iter(landing.entries().values()))
    assert mr.reader(tmp_path)(entry) == b"x"


def test_a_block_trade_repeated_in_the_bulk_list_counts_once() -> None:
    deal = {
        "date": "30-OCT-2026",
        "symbol": "SWIGGY",
        "client": "TENCENT",
        "side": "SELL",
        "qty": 54347662,
        "price": 180.65,
        "value_cr": 981.79,
    }
    other = {**deal, "client": "SOMEONE ELSE", "kind": "bulk"}
    rows = mr.drop_repeats([{**deal, "kind": "bulk"}, {**deal, "kind": "block"}, other])
    assert [(r["client"], r["kind"]) for r in rows] == [
        ("TENCENT", "block"),
        ("SOMEONE ELSE", "bulk"),
    ]
