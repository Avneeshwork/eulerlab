"""Holiday corroboration must degrade gracefully, never take down an ingest."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from eulerlab.ingest.holidays import extract, load_holidays, parse_nse_date, save_holidays

# Shape observed from NSE's endpoint on 2026-08-18.
SAMPLE = {
    "CM": [
        {"tradingDate": "15-Jan-2026", "weekDay": "Thursday", "description": "Election"},
        {"tradingDate": "26-Jan-2026", "weekDay": "Monday", "description": "Republic Day"},
    ],
    "FO": [{"tradingDate": "26-Jan-2026", "weekDay": "Monday", "description": "Republic Day"}],
}


def test_parses_nse_date_format() -> None:
    assert parse_nse_date("15-Jan-2026") == date(2026, 1, 15)


def test_unparseable_dates_return_none_rather_than_raising() -> None:
    for bad in ("", "nonsense", "32-Jan-2026", "15-Xxx-2026", "2026-01-15"):
        assert parse_nse_date(bad) is None


def test_extracts_the_requested_segment() -> None:
    assert extract(SAMPLE) == frozenset({date(2026, 1, 15), date(2026, 1, 26)})
    assert extract(SAMPLE, "FO") == frozenset({date(2026, 1, 26)})


def test_a_missing_segment_yields_nothing() -> None:
    assert extract(SAMPLE, "NOPE") == frozenset()


def test_malformed_rows_are_skipped_not_fatal() -> None:
    payload: dict[str, object] = {
        "CM": [{"tradingDate": "26-Jan-2026"}, {"tradingDate": 42}, "garbage", {}]
    }
    assert extract(payload) == frozenset({date(2026, 1, 26)})


def test_round_trips_through_the_cache(tmp_path: Path) -> None:
    save_holidays(tmp_path, json.dumps(SAMPLE).encode())
    assert load_holidays(tmp_path) == frozenset({date(2026, 1, 15), date(2026, 1, 26)})


def test_saving_records_when_it_was_fetched(tmp_path: Path) -> None:
    save_holidays(tmp_path, json.dumps(SAMPLE).encode())
    assert (tmp_path / "nse_holidays.fetched_at").read_text(encoding="utf-8")


def test_no_cache_means_no_holidays_not_a_crash(tmp_path: Path) -> None:
    # An ingest of 2,800 days must not die because reference data is absent.
    assert load_holidays(tmp_path / "missing") == frozenset()


def test_a_corrupt_cache_degrades_quietly(tmp_path: Path) -> None:
    (tmp_path / "nse_holidays.json").write_text("{not json", encoding="utf-8")
    assert load_holidays(tmp_path) == frozenset()
