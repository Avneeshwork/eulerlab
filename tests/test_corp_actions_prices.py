"""Close-price lookup, and the ISIN-serial mismatch that silently lost 21.9%
of all price lookups on the first full build.
"""

from __future__ import annotations

import io
import json
import zipfile
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest

from eulerlab.corp_actions.prices import (
    TransactionCapExceeded,
    _stop_cleanly_on_cap,
    build_close_index,
    close_price_lookup,
    instrument_key,
    parse_prev_closes,
)
from eulerlab.ingest.landing import ManifestEntry


def _zipped(csv_text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("bhav.csv", csv_text)
    return buf.getvalue()


LEGACY = (
    "SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,LAST,PREVCLOSE,TOTTRDQTY,TOTTRDVAL,TIMESTAMP,TOTALTRADES,ISIN,\n"
    "AUROPHARMA,EQ,700,710,695,705,705,706.45,1000,700000,21-NOV-2017,50,INE406A01037,\n"
)

UDIFF = (
    "TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,XpryDt,"
    "FininstrmActlXpryDt,StrkPric,OptnTp,FinInstrmNm,OpnPric,HghPric,LwPric,ClsPric,"
    "LastPric,PrvsClsgPric,UndrlygPric,SttlmPric,OpnIntrst,ChngInOpnIntrst,TtlTradgVol,"
    "TtlTrfVal,TtlNbOfTxsExctd,SsnId,NewBrdLotQty,Rmks,Rsvd1,Rsvd2,Rsvd3,Rsvd4\n"
    "2026-08-10,2026-08-10,CM,NSE,STK,1,INE002A01018,RELIANCE,EQ,,,,,RELIANCE,100,101,99,"
    "100.5,100.5,99.75,,100.5,,,1000,100000,50,F1,1,,,,,\n"
)


# --- the internal join key ---


def test_company_equity_keys_on_the_issuer_prefix() -> None:
    """The trailing serial is reissued on a face-value change; the first ten
    characters are not."""
    assert instrument_key("INE406A01029") == instrument_key("INE406A01037")


def test_a_malformed_isin_has_no_key_rather_than_a_truncated_one() -> None:
    assert instrument_key("NOTANISIN") is None
    assert instrument_key("") is None


# --- parsing both bhavcopy eras ---


def test_the_legacy_era_prev_close_is_read() -> None:
    prices = parse_prev_closes(_zipped(LEGACY))
    assert prices[instrument_key("INE406A01037") or ""] == 706.45


def test_the_udiff_era_prev_close_is_read() -> None:
    prices = parse_prev_closes(_zipped(UDIFF))
    assert prices[instrument_key("INE002A01018") or ""] == 99.75


def test_an_empty_archive_yields_nothing_rather_than_failing() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("readme.txt", "no csv here")
    assert parse_prev_closes(buf.getvalue()) == {}


# --- the regression this file exists for ---


def test_a_reissued_isin_still_finds_its_price() -> None:
    """The defect: on 2017-11-21 the corporate-actions feed called Aurobindo
    Pharma INE406A01029 while that day's bhavcopy called it INE406A01037.

    Joining on the raw string found nothing and reported it as "no price
    available", which looked like sparse data rather than a broken join. It
    cost 21.9% of all lookups on the first full build.
    """
    index = {(k, "2017-11-21"): v for k, v in parse_prev_closes(_zipped(LEGACY)).items()}
    lookup = close_price_lookup(index)

    # the ISIN the feed gives, which is NOT the one in the bhavcopy
    assert lookup("INE406A01029", date(2017, 11, 21)) == 706.45


def test_a_different_issuer_does_not_collide() -> None:
    """The prefix rule must not be so loose that two companies share a price."""
    index = {(k, "2017-11-21"): v for k, v in parse_prev_closes(_zipped(LEGACY)).items()}
    lookup = close_price_lookup(index)
    assert lookup("INE999Z01011", date(2017, 11, 21)) is None


def test_a_price_on_a_different_date_is_not_returned() -> None:
    index = {(k, "2017-11-21"): v for k, v in parse_prev_closes(_zipped(LEGACY)).items()}
    lookup = close_price_lookup(index)
    assert lookup("INE406A01037", date(2017, 11, 22)) is None


# --- the cache: a cost control, not an optimisation ---


def test_a_cached_date_is_not_refetched(tmp_path: Path) -> None:
    """One full build is 2,121 downloads and the B2 free tier allows 2,500 a
    day. A rebuild that re-downloaded would exhaust the cap, which is exactly
    what happened before the cache existed."""
    cache = tmp_path / "close_index.jsonl"
    cache.write_text(
        json.dumps({"d": "2017-11-21", "k": "INE406A010", "p": 706.45})
        + "\n"
        + json.dumps({"d": "2017-11-21", "done": True})
        + "\n",
        encoding="utf-8",
    )
    entry = ManifestEntry(
        trade_date="2017-11-21",
        segment="cm",
        file_format="legacy",
        url="x",
        path="cm/2017/11/2017-11-21_legacy.zip",
        sha256="0" * 64,
        size_bytes=1,
        rows=1,
        inner_name="x.csv",
        knowledge_time="2026-08-19T00:00:00+00:00",
    )
    # No B2 credentials and no network here: if it tried to fetch, it would raise.
    index = build_close_index([entry], cache_path=cache)
    assert index[("INE406A010", "2017-11-21")] == 706.45


def test_an_empty_day_is_marked_so_it_is_not_refetched_forever(tmp_path: Path) -> None:
    """A date whose file held no price we needed still counts as processed."""
    cache = tmp_path / "close_index.jsonl"
    cache.write_text(json.dumps({"d": "2017-11-22", "done": True}) + "\n", encoding="utf-8")
    entry = ManifestEntry(
        trade_date="2017-11-22",
        segment="cm",
        file_format="legacy",
        url="x",
        path="cm/2017/11/2017-11-22_legacy.zip",
        sha256="0" * 64,
        size_bytes=1,
        rows=1,
        inner_name="x.csv",
        knowledge_time="2026-08-19T00:00:00+00:00",
    )
    assert build_close_index([entry], cache_path=cache) == {}


def test_no_cache_file_yet_is_not_an_error(tmp_path: Path) -> None:
    assert build_close_index([], cache_path=tmp_path / "absent.jsonl") == {}


# --- the daily cap is an expected condition, not a crash ---


class _CapExceeded(Exception):
    """Shaped like boto's error, which is identified by message text."""

    def __str__(self) -> str:
        return (
            "An error occurred (AccessDenied) when calling the GetObject operation: "
            "Cannot download file, download bandwidth or transaction (Class B) cap exceeded."
        )


def _results_then_cap(n_ok: int) -> Iterator[tuple[str, bytes]]:
    for i in range(n_ok):
        yield (f"2020-01-{i + 1:02d}", b"")
    raise _CapExceeded


def test_the_cap_becomes_a_clear_error_not_a_boto_traceback() -> None:
    with pytest.raises(TransactionCapExceeded, match="daily download cap"):
        list(_stop_cleanly_on_cap(_results_then_cap(0), 2121))


def test_the_message_says_how_much_was_saved() -> None:
    """The one fact that matters when this fires is that work was not lost."""
    with pytest.raises(TransactionCapExceeded, match=r"after 3 of 2,121 files"):
        list(_stop_cleanly_on_cap(_results_then_cap(3), 2121))


def test_results_before_the_cap_are_still_yielded() -> None:
    """They must reach the consumer, which is what writes them to the cache."""
    produced = []
    with pytest.raises(TransactionCapExceeded):
        for item in _stop_cleanly_on_cap(_results_then_cap(2), 10):
            produced.append(item)
    assert len(produced) == 2


def test_an_unrelated_error_is_not_swallowed() -> None:
    """Only the cap is special-cased; a real bug must still surface as itself."""

    def boom() -> Iterator[tuple[str, bytes]]:
        yield from ()  # a generator that produces nothing, then fails
        raise ValueError("something genuinely wrong")

    with pytest.raises(ValueError, match="genuinely wrong"):
        list(_stop_cleanly_on_cap(boom(), 10))
