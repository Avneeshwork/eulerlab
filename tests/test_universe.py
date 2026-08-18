"""Universe selection must be point-in-time, or refuse.

The bug this file exists to prevent actually happened on 2026-08-18: ranking
"the 60 most recent files" while the backfill was still at 2023 mixed five days
of 2026 with fifty-five of 2023 and produced a top-250 containing HDFC, which
had merged out of existence years earlier. The ranking looked completely
plausible. Only a company that should not exist gave it away.
"""

from __future__ import annotations

import io
import zipfile
from datetime import date, timedelta
from pathlib import Path

import pytest

from eulerlab.ingest.landing import Landing
from eulerlab.record.universe import (
    DiscontiguousWindow,
    Ranked,
    rank_by_liquidity,
    read_turnover,
    write_universe,
)


def bhavcopy(rows: list[tuple[str, str, float]], *, udiff: bool = True) -> bytes:
    header = "TradDt,TckrSymb,SctySrs,TtlTrfVal" if udiff else "SYMBOL,SERIES,TOTTRDVAL,TIMESTAMP"
    lines = [header]
    for symbol, series, value in rows:
        lines.append(
            f"2026-08-14,{symbol},{series},{value}" if udiff else f"{symbol},{series},{value},x"
        )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("bhav.csv", "\n".join(lines) + "\n")
    return buffer.getvalue()


def _land(landing: Landing, day: date, rows: list[tuple[str, str, float]]) -> None:
    landing.write(
        trade_date=day,
        segment="cm",
        file_format="udiff",
        url="https://example.invalid/f.zip",
        payload=bhavcopy(rows),
        rows=len(rows),
        inner_name="bhav.csv",
    )


def _contiguous(landing: Landing, start: date, days: int) -> None:
    for offset in range(days):
        _land(
            landing,
            start + timedelta(days=offset),
            [("BIG", "EQ", 1e9), ("MID", "EQ", 1e7), ("TINY", "EQ", 1e3), ("ETF", "GB", 1e10)],
        )


# --- parsing both formats ---


def test_reads_udiff_turnover() -> None:
    assert read_turnover(bhavcopy([("RELIANCE", "EQ", 1234.5)])) == {"RELIANCE": 1234.5}


def test_reads_legacy_turnover() -> None:
    payload = bhavcopy([("RELIANCE", "EQ", 1234.5)], udiff=False)
    assert read_turnover(payload) == {"RELIANCE": 1234.5}


def test_non_equity_series_is_excluded() -> None:
    # ETFs and debt series would otherwise crowd out actual stocks.
    turnover = read_turnover(bhavcopy([("STOCK", "EQ", 100.0), ("SOMEETF", "GB", 1e12)]))
    assert turnover == {"STOCK": 100.0}


def test_unparseable_values_are_skipped_not_fatal() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("b.csv", "TckrSymb,SctySrs,TtlTrfVal\nA,EQ,oops\nB,EQ,5\n")
    assert read_turnover(buffer.getvalue()) == {"B": 5.0}


# --- the contiguity guard ---


def test_a_hole_in_the_window_is_refused(tmp_path: Path) -> None:
    landing = Landing(tmp_path)
    _contiguous(landing, date(2023, 3, 1), 5)
    _land(landing, date(2026, 8, 14), [("BIG", "EQ", 1e9)])  # three years later

    with pytest.raises(DiscontiguousWindow, match="gap of"):
        rank_by_liquidity(landing, as_of=date(2026, 8, 14), lookback_days=60, min_days=1)


def test_a_contiguous_window_is_accepted(tmp_path: Path) -> None:
    landing = Landing(tmp_path)
    _contiguous(landing, date(2026, 6, 1), 30)

    ranked = rank_by_liquidity(landing, as_of=date(2026, 6, 30), lookback_days=30, min_days=5)

    assert [r.symbol for r in ranked] == ["BIG", "MID", "TINY"]


def test_weekends_and_holidays_do_not_trip_the_guard(tmp_path: Path) -> None:
    landing = Landing(tmp_path)
    for offset in (0, 1, 2, 3, 4, 7, 8, 9, 10, 11):  # two working weeks
        _land(landing, date(2026, 6, 1) + timedelta(days=offset), [("BIG", "EQ", 1e9)])

    ranked = rank_by_liquidity(landing, as_of=date(2026, 6, 12), lookback_days=20, min_days=1)

    assert ranked[0].symbol == "BIG"


def test_an_empty_landing_zone_is_refused(tmp_path: Path) -> None:
    with pytest.raises(DiscontiguousWindow, match="no cash-market files"):
        rank_by_liquidity(Landing(tmp_path), as_of=date(2026, 8, 14))


# --- ranking behaviour ---


def test_thinly_traded_names_are_dropped(tmp_path: Path) -> None:
    landing = Landing(tmp_path)
    _contiguous(landing, date(2026, 6, 1), 30)
    _land(landing, date(2026, 6, 30), [("ONEDAY", "EQ", 1e12)])  # huge, but once

    ranked = rank_by_liquidity(landing, as_of=date(2026, 6, 30), lookback_days=40, min_days=10)

    assert "ONEDAY" not in [r.symbol for r in ranked]


def test_ranking_uses_median_so_one_block_deal_cannot_promote(tmp_path: Path) -> None:
    landing = Landing(tmp_path)
    for offset in range(20):
        spike = 1e12 if offset == 0 else 1.0
        _land(
            landing,
            date(2026, 6, 1) + timedelta(days=offset),
            [("STEADY", "EQ", 100.0), ("SPIKY", "EQ", spike)],
        )

    ranked = rank_by_liquidity(landing, as_of=date(2026, 6, 20), lookback_days=20, min_days=5)

    assert ranked[0].symbol == "STEADY"


# --- persisting it ---


def test_a_written_universe_records_its_as_of_date(tmp_path: Path) -> None:
    path = tmp_path / "u.txt"
    write_universe(path, ["A", "B"], as_of=date(2026, 8, 14), note="test")
    text = path.read_text(encoding="utf-8")
    # Without the as-of date, a universe file is a bias waiting to be reused.
    assert "as_of: 2026-08-14" in text
    assert text.strip().endswith("B")


def test_ranked_is_comparable() -> None:
    assert Ranked("A", 1.0, 5) == Ranked("A", 1.0, 5)
