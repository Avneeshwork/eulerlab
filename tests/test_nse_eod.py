"""Ingest orchestration: idempotency, resumability, and honest missing-day reporting."""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pytest

from eulerlab.ingest.fetch import Fetcher, FetchPolicy, TransportError
from eulerlab.ingest.landing import Landing
from eulerlab.ingest.nse_eod import (
    ClosureKind,
    DayOutcome,
    DayStatus,
    Summary,
    business_days,
    count_rows,
    fetch_day,
    ingest,
    render,
)
from eulerlab.ingest.nse_urls import Segment


def make_zip(rows: int = 3, name: str = "BhavCopy.csv") -> bytes:
    buffer = io.BytesIO()
    body = "TradDt,ClsPric\n" + "".join(f"2026-08-14,{i}\n" for i in range(rows))
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(name, body)
    return buffer.getvalue()


@dataclass
class RoutingTransport:
    """Serves whatever the routes dict says; 404 for anything else."""

    routes: dict[str, tuple[int, bytes]] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)
    raise_on: set[str] = field(default_factory=set)

    def get(self, url: str, *, timeout: float) -> tuple[int, bytes]:
        self.calls.append(url)
        if url in self.raise_on:
            raise TransportError("network down")
        return self.routes.get(url, (404, b""))


def _fetcher(transport: RoutingTransport) -> Fetcher:
    return Fetcher(
        transport,
        FetchPolicy(min_interval_s=0.0, max_attempts=2, backoff_base_s=0.0),
        sleep=lambda _: None,
    )


# --- calendar walking ---


def test_weekends_are_skipped_by_default() -> None:
    # 2026-08-14 is a Friday; 15th Sat, 16th Sun, 17th Mon.
    days = list(business_days(date(2026, 8, 14), date(2026, 8, 17)))
    assert days == [date(2026, 8, 14), date(2026, 8, 17)]


def test_weekends_can_be_swept_for_special_sessions() -> None:
    days = list(business_days(date(2026, 8, 14), date(2026, 8, 17), include_weekends=True))
    assert len(days) == 4


def test_a_single_day_range_yields_that_day() -> None:
    assert list(business_days(date(2026, 8, 14), date(2026, 8, 14))) == [date(2026, 8, 14)]


# --- reading the archive ---


def test_row_count_excludes_the_header() -> None:
    rows, name = count_rows(make_zip(rows=5))
    assert rows == 5
    assert name == "BhavCopy.csv"


def test_an_archive_without_a_csv_is_an_error() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("readme.txt", "nope")
    with pytest.raises(ValueError, match=r"no \.csv"):
        count_rows(buffer.getvalue())


# --- one day, one segment ---


def _url(day: date, segment: Segment) -> str:
    from eulerlab.ingest.nse_urls import FileFormat, url_for

    return url_for(day, segment, FileFormat.UDIFF)


def test_a_present_file_is_downloaded_and_landed(tmp_path: Path) -> None:
    day = date(2026, 8, 14)
    transport = RoutingTransport({_url(day, Segment.CM): (200, make_zip(7))})
    landing = Landing(tmp_path)

    outcome = fetch_day(_fetcher(transport), landing, day, Segment.CM)

    assert outcome.status is DayStatus.DOWNLOADED
    assert outcome.rows == 7
    assert landing.has(day, "cm")


def test_a_second_run_skips_without_any_request(tmp_path: Path) -> None:
    """The headline acceptance criterion: re-running downloads nothing."""
    day = date(2026, 8, 14)
    transport = RoutingTransport({_url(day, Segment.CM): (200, make_zip())})
    landing = Landing(tmp_path)

    fetch_day(_fetcher(transport), landing, day, Segment.CM)
    calls_after_first = len(transport.calls)
    outcome = fetch_day(_fetcher(transport), landing, day, Segment.CM)

    assert outcome.status is DayStatus.SKIPPED
    assert len(transport.calls) == calls_after_first


def test_a_missing_file_is_absent_not_failed(tmp_path: Path) -> None:
    outcome = fetch_day(
        _fetcher(RoutingTransport()), Landing(tmp_path), date(2026, 8, 14), Segment.CM
    )
    assert outcome.status is DayStatus.ABSENT


def test_a_network_failure_is_failed_not_absent(tmp_path: Path) -> None:
    # Conflating these two is how data loss gets recorded as a holiday.
    day = date(2026, 8, 14)
    transport = RoutingTransport(raise_on={_url(day, Segment.CM)})
    outcome = fetch_day(_fetcher(transport), Landing(tmp_path), day, Segment.CM)
    assert outcome.status is DayStatus.FAILED


def test_it_falls_back_to_the_other_format(tmp_path: Path) -> None:
    from eulerlab.ingest.nse_urls import FileFormat, url_for

    # A 2024 date near the cutover: UDiFF tried first, legacy actually present.
    day = date(2024, 3, 1)
    legacy = url_for(day, Segment.CM, FileFormat.LEGACY)
    transport = RoutingTransport({legacy: (200, make_zip(4))})

    outcome = fetch_day(_fetcher(transport), Landing(tmp_path), day, Segment.CM)

    assert outcome.status is DayStatus.DOWNLOADED
    assert outcome.file_format is FileFormat.LEGACY


# --- the missing-day report ---


def _summary(*outcomes: DayOutcome) -> Summary:
    return Summary(outcomes=list(outcomes))


def test_both_segments_absent_is_a_likely_holiday() -> None:
    day = date(2026, 1, 26)
    summary = _summary(
        DayOutcome(day, Segment.CM, DayStatus.ABSENT),
        DayOutcome(day, Segment.FO, DayStatus.ABSENT),
    )
    assert summary.classify_closures(frozenset()) == {day: ClosureKind.HOLIDAY_LIKELY}


def test_a_known_holiday_is_confirmed() -> None:
    day = date(2026, 1, 26)
    summary = _summary(
        DayOutcome(day, Segment.CM, DayStatus.ABSENT),
        DayOutcome(day, Segment.FO, DayStatus.ABSENT),
    )
    assert summary.classify_closures(frozenset({day})) == {day: ClosureKind.HOLIDAY_CONFIRMED}


def test_one_segment_missing_is_an_anomaly_not_a_holiday() -> None:
    """The silent-gap shape. A holiday shuts both markets, never just one."""
    day = date(2026, 8, 14)
    summary = _summary(
        DayOutcome(day, Segment.CM, DayStatus.DOWNLOADED, rows=10),
        DayOutcome(day, Segment.FO, DayStatus.ABSENT),
    )
    assert summary.classify_closures(frozenset()) == {day: ClosureKind.ANOMALY}


def test_a_failure_outranks_everything_else() -> None:
    day = date(2026, 8, 14)
    summary = _summary(
        DayOutcome(day, Segment.CM, DayStatus.FAILED),
        DayOutcome(day, Segment.FO, DayStatus.ABSENT),
    )
    assert summary.classify_closures(frozenset({day})) == {day: ClosureKind.DOWNLOAD_FAILED}


def test_a_fully_landed_day_is_not_reported_as_missing() -> None:
    day = date(2026, 8, 14)
    summary = _summary(
        DayOutcome(day, Segment.CM, DayStatus.DOWNLOADED, rows=1),
        DayOutcome(day, Segment.FO, DayStatus.DOWNLOADED, rows=2),
    )
    assert summary.classify_closures(frozenset()) == {}


# --- end to end, and the report ---


def test_full_run_then_rerun_downloads_nothing(tmp_path: Path) -> None:
    day = date(2026, 8, 14)
    transport = RoutingTransport(
        {
            _url(day, Segment.CM): (200, make_zip(3)),
            _url(day, Segment.FO): (200, make_zip(9)),
        }
    )
    landing = Landing(tmp_path)

    first = ingest(start=day, end=day, landing=landing, fetcher=_fetcher(transport))
    requests_made = len(transport.calls)
    second = ingest(start=day, end=day, landing=Landing(tmp_path), fetcher=_fetcher(transport))

    assert first.count(DayStatus.DOWNLOADED) == 2
    assert first.rows == 12
    assert second.count(DayStatus.DOWNLOADED) == 0
    assert second.count(DayStatus.SKIPPED) == 2
    assert len(transport.calls) == requests_made


def test_report_flags_failures_and_says_needs_attention() -> None:
    day = date(2026, 8, 14)
    summary = _summary(DayOutcome(day, Segment.CM, DayStatus.FAILED))
    text = render(summary, frozenset(), day, day)
    assert "NEEDS ATTENTION" in text
    assert "2026-08-14" in text


def test_report_is_clean_when_everything_landed() -> None:
    day = date(2026, 8, 14)
    summary = _summary(
        DayOutcome(day, Segment.CM, DayStatus.DOWNLOADED, rows=1),
        DayOutcome(day, Segment.FO, DayStatus.DOWNLOADED, rows=1),
    )
    text = render(summary, frozenset(), day, day)
    assert "CLEAN" in text


def test_report_admits_when_it_has_no_holiday_list() -> None:
    day = date(2026, 8, 14)
    summary = _summary(DayOutcome(day, Segment.CM, DayStatus.ABSENT))
    assert "no NSE holiday list was available" in render(summary, frozenset(), day, day)
