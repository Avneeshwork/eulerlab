"""Reading bars out of both bhavcopy eras, and aggregating minute bars."""

from __future__ import annotations

import io
import zipfile
from datetime import date

from eulerlab.quality.sources import bars_from_bhavcopy, daily_bar_from_minutes

DAY = date(2020, 1, 1)

LEGACY = (
    "SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,LAST,PREVCLOSE,TOTTRDQTY,TOTTRDVAL,TIMESTAMP,TOTALTRADES,ISIN,\n"
    "ACME,EQ,100,110,95,105,105,99,5000,525000,01-JAN-2020,200,INE000A01001,\n"
    "BONDCO,N1,100,110,95,105,105,99,10,1050,01-JAN-2020,2,INE999A01001,\n"
)

UDIFF = (
    "TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,XpryDt,"
    "FininstrmActlXpryDt,StrkPric,OptnTp,FinInstrmNm,OpnPric,HghPric,LwPric,ClsPric,"
    "LastPric,PrvsClsgPric,UndrlygPric,SttlmPric,OpnIntrst,ChngInOpnIntrst,TtlTradgVol,"
    "TtlTrfVal,TtlNbOfTxsExctd,SsnId,NewBrdLotQty,Rmks,Rsvd1,Rsvd2,Rsvd3,Rsvd4\n"
    "2026-08-10,2026-08-10,CM,NSE,STK,1,INE000A01001,ACME,EQ,,,,,ACME,100,110,95,105,"
    "105,99,,105,,,5000,525000,200,F1,1,,,,,\n"
)


def _zipped(text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("bhav.csv", text)
    return buf.getvalue()


def test_the_legacy_era_parses_into_a_bar() -> None:
    bars = list(bars_from_bhavcopy(_zipped(LEGACY), DAY))
    assert len(bars) == 1
    bar = bars[0]
    assert (bar.symbol, bar.open, bar.high, bar.low, bar.close) == ("ACME", 100, 110, 95, 105)
    assert bar.prev_close == 99
    assert bar.turnover == 525000


def test_the_udiff_era_parses_identically() -> None:
    """Both eras must produce the same Bar, or every check would need to know
    which file it came from."""
    legacy = next(iter(bars_from_bhavcopy(_zipped(LEGACY), DAY)))
    udiff = next(iter(bars_from_bhavcopy(_zipped(UDIFF), DAY)))
    assert (legacy.open, legacy.high, legacy.low, legacy.close) == (
        udiff.open,
        udiff.high,
        udiff.low,
        udiff.close,
    )
    assert legacy.prev_close == udiff.prev_close


def test_non_equity_series_are_excluded() -> None:
    """Bonds share the file and would generate meaningless findings."""
    symbols = [b.symbol for b in bars_from_bhavcopy(_zipped(LEGACY), DAY)]
    assert "BONDCO" not in symbols


def test_a_row_missing_a_price_is_skipped_not_defaulted() -> None:
    """A defaulted zero would fail the OHLC invariant and be reported as
    corrupt data when the truth is the field was absent."""
    broken = (
        "SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,PREVCLOSE,TOTTRDQTY,TOTTRDVAL,ISIN,\n"
        "ACME,EQ,100,,95,105,99,5000,525000,INE000A01001,\n"
    )
    assert list(bars_from_bhavcopy(_zipped(broken), DAY)) == []


def test_an_archive_with_no_csv_yields_nothing() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("readme.txt", "nothing here")
    assert list(bars_from_bhavcopy(buf.getvalue(), DAY)) == []


# --- minute aggregation ---


def test_a_daily_bar_takes_first_open_and_last_close() -> None:
    """The easy mistake is min/max for open and close, which would make every
    cross-source comparison fail."""
    minutes = [
        (100.0, 102.0, 99.0, 101.0, 10.0),
        (101.0, 108.0, 100.0, 107.0, 20.0),
        (107.0, 107.5, 104.0, 105.0, 30.0),
    ]
    bar = daily_bar_from_minutes("ACME", DAY, minutes)
    assert bar is not None
    assert bar.open == 100.0  # first minute's open, not the lowest
    assert bar.close == 105.0  # last minute's close, not the highest
    assert bar.high == 108.0
    assert bar.low == 99.0
    assert bar.volume == 60.0


def test_no_minutes_produces_no_bar() -> None:
    assert daily_bar_from_minutes("ACME", DAY, []) is None
