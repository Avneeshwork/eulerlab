"""The data added in research 065: index closes, delivery, calendars, OHLC."""

from __future__ import annotations

import io
import json
import zipfile
from datetime import date
from pathlib import Path

import pytest

from eulerlab import market_history as mh
from eulerlab.features import rebuild_ohlc
from eulerlab.ingest import nse_daily_files as ndf

INDEX_2015 = (
    "Index Name,Index Date,Open Index Value,High Index Value,Low Index Value,Closing Index Value,"
    "Points Change,Change(%),Volume,Turnover (Rs. Cr.),P/E,P/B,Div Yield\n"
    "CNX Nifty,05-01-2015,8407.95,8445.6,8363.9,8378.4,-17.05,-.2,1,2,22.6,3.6,1.3\n"
    "CNX Bank,05-01-2015,1,2,1,1.5,0,0,1,2,-,-,-\n"
    "India VIX,05-01-2015,14.2,15.1,14.0,14.6,0,0,-,-,-,-,-\n"
)

MTO = (
    "Security Wise Delivery Position - Compulsory Rolling Settlement\n"
    "10,MTO,04012016,450374569,0001561\n"
    "Record Type,Sr No,Name of Security,Quantity Traded,Deliverable Quantity,% of Deliverable\n"
    "20,1,20MICRONS,EQ,258669,116118,44.89\n"
    "20,2,SOMEBOND,N1,100,100,100.00\n"
)


def test_index_files_from_before_the_2015_rename_are_accepted() -> None:
    assert ndf._index_rows(INDEX_2015.encode()) == 3
    assert ndf._index_rows(b"<html>not the report</html>") is None


INDEX_2012 = (
    "Index Name,Index Date,Open Index Value,High Index Value,Low Index Value,"
    "Closing Index Value,Points Change,Change(%),Volume,Turnover (Rs. Cr.),P/E,P/B,Div Yield\n"
    "S&P CNX Nifty,01-06-2012,4910.75,4948.55,4835.45,4841.65,-82.6,-1.68,1,1,16.9,2.9,1.5\n"
    "CNX Nifty Junior,01-06-2012,9800,9850,9700,9720,-80,-0.8,1,1,15,2,1\n"
    "CNX 100,01-06-2012,4800,4850,4700,4750,-50,-1,1,1,16,2,1\n"
)


def test_index_files_from_2012_with_the_s_and_p_name_are_accepted() -> None:
    """NSE's files before early 2013 name the Nifty 'S&P CNX Nifty' (ADR-186)."""
    assert ndf._index_rows(INDEX_2012.encode()) == 3
    rows = list(mh.index_rows(INDEX_2012.encode(), "2012-06-01"))
    assert [r["index"] for r in rows] == ["Nifty 50", "Nifty Next 50", "Nifty 100"]
    assert mh.canonical_index("S&P CNX 500") == "Nifty 500"


def test_old_index_names_become_todays() -> None:
    rows = list(mh.index_rows(INDEX_2015.encode(), "2015-01-05"))
    assert [r["index"] for r in rows] == ["Nifty 50", "Nifty Bank", "India VIX"]
    nifty = rows[0]
    assert (nifty["o"], nifty["c"], nifty["pe"]) == (8407.95, 8378.4, 22.6)
    assert rows[1]["pe"] is None
    assert nifty["event_time"].startswith("2015-01-05T15:30")
    assert nifty["knowledge_time"] > nifty["event_time"]


def test_the_midcap_and_smallcap_100_are_one_series_each_under_four_names() -> None:
    for name in (
        "CNX Midcap",
        "Nifty Midcap 100",
        "Nifty Free Float Midcap 100",
        "NIFTY Midcap 100",
    ):
        assert mh.canonical_index(name) == "Nifty Midcap 100"
    assert mh.canonical_index("Nifty Full Midcap 100") == "Nifty Full Midcap 100"
    assert mh.canonical_index("CNX PSU Bank") == "Nifty PSU Bank"


def test_delivery_keeps_eq_series_only() -> None:
    rows = list(mh.delivery_rows(MTO.encode(), "2016-01-04"))
    assert [(r["s"], r["traded"], r["deliverable"], r["pct"]) for r in rows] == [
        ("20MICRONS", 258669.0, 116118.0, 44.89)
    ]
    assert ndf._delivery_rows(MTO.encode()) == 2


def _fo_zip(text: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("fo.csv", text)
    return buffer.getvalue()


def test_expiries_are_read_from_either_bhavcopy_format() -> None:
    legacy = "INSTRUMENT,SYMBOL,EXPIRY_DT\nFUTIDX,NIFTY,28-Jan-2016\nOPTIDX,NIFTY,07-Jan-2016\nFUTIDX,BANKNIFTY,28-Jan-2016\n"
    udiff = "FinInstrmTp,TckrSymb,XpryDt\nIDF,NIFTY,2024-01-25\nIDO,NIFTY,2024-01-04\n"
    assert mh._fo_expiries(_fo_zip(legacy)) == {"2016-01-28"}
    assert mh._fo_expiries(_fo_zip(udiff)) == {"2024-01-25"}


def test_a_moved_expiry_is_replaced_by_the_day_it_really_expired() -> None:
    from datetime import date

    days = [date(2023, 6, d) for d in (26, 27, 28, 30)] + [
        date(2025, 9, d) for d in (24, 25, 26, 29, 30)
    ]
    files = {
        # The Bakri Id holiday moved to the 29th, and expiry to the 28th.
        date(2023, 6, 28): {"2023-06-28", "2023-07-27"},
        # Tuesday expiry: the September contract became the 30th.
        date(2025, 9, 25): {"2025-09-30"},
        date(2025, 9, 30): {"2025-09-30", "2025-10-28"},
    }
    scheduled = ["2023-06-29", "2025-09-25", "2025-09-30", "2026-01-27"]
    assert mh.confirm_expiries(scheduled, days, lambda d: files.get(d, set())) == [
        "2023-06-28",
        "2025-09-30",
        "2026-01-27",
    ]


def test_the_swap_refuses_when_closes_differ(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    panel, rebuilt = tmp_path / "panel.jsonl", tmp_path / "rebuilt.jsonl"
    panel.write_text(json.dumps({"d": "2016-01-04", "s": "A", "c": 10.0}) + "\n", encoding="utf-8")
    rebuilt.write_text(
        json.dumps({"d": "2016-01-04", "s": "A", "c": 10.5, "o": 10, "h": 11, "l": 9}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(rebuild_ohlc, "PANEL_PATH", panel)
    monkeypatch.setattr(rebuild_ohlc, "REBUILD_PATH", rebuilt)
    assert rebuild_ohlc.check() == ["2016-01-04: 0 symbols missing, 1 closes differ"]
    rebuilt.write_text(
        json.dumps({"d": "2016-01-04", "s": "A", "c": 10.0, "o": 10, "h": 11, "l": 9}) + "\n",
        encoding="utf-8",
    )
    assert rebuild_ohlc.check() == []


def test_daily_tables_add_only_new_days_and_drop_a_cut_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = tmp_path / "delivery.jsonl"
    entries = [{"trade_date": "2016-01-04"}, {"trade_date": "2016-01-05"}]
    reads: list[str] = []

    def read(entry: dict[str, str]) -> bytes:
        reads.append(entry["trade_date"])
        return MTO.encode()

    monkeypatch.setattr(mh, "DELIVERY", store)
    monkeypatch.setattr(mh, "_entries", lambda segment: entries)
    monkeypatch.setattr(mh, "_read", read)

    assert mh.build_delivery() == (2, 2)
    assert mh.build_delivery() == (0, 2)
    assert reads == ["2016-01-04", "2016-01-05"]

    # An interrupted run leaves half a line; that day is read again.
    lines = store.read_text(encoding="utf-8").splitlines()
    store.write_text(lines[0] + "\n" + lines[1][:30], encoding="utf-8")
    assert mh.build_delivery() == (1, 2)
    assert reads[-1] == "2016-01-05"

    day = json.loads(store.read_text(encoding="utf-8").splitlines()[0])
    assert day["stocks"] == {"20MICRONS": [258669.0, 116118.0, 44.89]}
    assert day["knowledge_time"] > day["event_time"]
    assert [d.isoformat() for d, _ in mh.delivery_series("20MICRONS")] == [
        "2016-01-04",
        "2016-01-05",
    ]


def test_an_index_is_one_series_across_the_rename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = tmp_path / "index.jsonl"
    new = INDEX_2015.replace("CNX Nifty,05-01-2015", "Nifty 50,06-01-2015")
    payloads = {"2015-01-05": INDEX_2015.encode(), "2015-01-06": new.encode()}
    monkeypatch.setattr(mh, "INDEX_HISTORY", store)
    monkeypatch.setattr(
        mh, "_entries", lambda segment: [{"trade_date": d} for d in sorted(payloads)]
    )
    monkeypatch.setattr(mh, "_read", lambda entry: payloads[entry["trade_date"]])
    assert mh.build_indices() == (2, 2)
    assert [d.isoformat() for d, _ in mh.index_series("Nifty 50")] == ["2015-01-05", "2015-01-06"]
    assert mh.index_series("India VIX")[0][1] == 14.6


def test_futures_are_read_from_either_bhavcopy_format() -> None:
    legacy = (
        "INSTRUMENT,SYMBOL,EXPIRY_DT,OPEN,HIGH,LOW,CLOSE,SETTLE_PR,CONTRACTS,OPEN_INT\n"
        "FUTIDX,NIFTY,31-Mar-2016,7051.25,7240.5,7046.15,7229.05,7229.05,236798,18579675\n"
        "FUTSTK,NIFTY,31-Mar-2016,1,1,1,1,1,1,1\n"
    )
    udiff = (
        "FinInstrmTp,TckrSymb,XpryDt,OpnPric,HghPric,LwPric,ClsPric,SttlmPric,OpnIntrst,TtlTradgVol\n"
        "IDF,NIFTY,2024-09-26,25412.05,25420,25295.15,25340.45,25340.45,14944100,204112\n"
        "IDO,NIFTY,2024-09-26,1,1,1,1,1,1,1\n"
    )
    old = mh.fo_futures(_fo_zip(legacy))
    assert old == {
        "2016-03-31": {
            "o": 7051.25,
            "h": 7240.5,
            "l": 7046.15,
            "c": 7229.05,
            "settle": 7229.05,
            "oi": 18579675.0,
            "volume": 236798.0,
        }
    }
    assert mh.fo_futures(_fo_zip(udiff))["2024-09-26"]["c"] == 25340.45


def test_index_levels_become_panel_rows_no_action_can_adjust(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = tmp_path / "index.jsonl"
    monkeypatch.setattr(mh, "INDEX_HISTORY", store)
    monkeypatch.setattr(mh, "_entries", lambda segment: [{"trade_date": "2015-01-05"}])
    monkeypatch.setattr(mh, "_read", lambda entry: INDEX_2015.encode())
    mh.build_indices()
    rows = mh.index_panel_rows(["Nifty Bank", "Nifty 50"])
    assert [(r.symbol, r.close, r.isin) for r in rows] == [
        ("Nifty 50", 8378.4, "IDX:Nifty 50"),
        ("Nifty Bank", 1.5, "IDX:Nifty Bank"),
    ]
    assert rows[0].turnover == 2e7
    assert mh.index_panel_rows(["Nifty 50"], since=date(2015, 1, 6)) == []
