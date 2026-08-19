"""Every check, fed deliberately corrupt data, must go red.

A quality engine that reports "clean" is indistinguishable from one that is
broken, so each check here is shown failing on a planted defect *and* staying
silent on good data. The second half matters as much as the first: a check
that fires on everything gets switched off within a week.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

from eulerlab.quality.findings import KNOWN, Finding, Report, Severity, Suppression
from eulerlab.quality.manifest_checks import (
    check_calendar_gaps,
    check_duplicate_keys,
    check_manifest_present,
    check_segment_coverage,
    check_staleness,
    check_zero_row_files,
)
from eulerlab.quality.row_checks import (
    Bar,
    check_extreme_moves,
    check_ohlc_invariants,
    check_return_spikes,
    check_staleness_runs,
    check_turnover_consistency,
)

UTC_NOW = datetime.fromisoformat("2026-08-19T00:00:00+00:00")


def _manifest(tmp_path: Path, rows: list[dict[str, object]]) -> Path:
    path = tmp_path / "manifest.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return path


def _bar(day: str, o: float, h: float, low: float, c: float, **kw: object) -> Bar:
    return Bar(symbol="ACME", day=date.fromisoformat(day), open=o, high=h, low=low, close=c, **kw)  # type: ignore[arg-type]


# --- OHLC invariants: absolute, so ERROR ---


def test_a_high_below_a_low_is_an_error() -> None:
    findings = check_ohlc_invariants([_bar("2020-01-01", 10, 5, 8, 9)])
    assert any(f.severity is Severity.ERROR for f in findings)
    assert any("below low" in f.detail for f in findings)


def test_a_close_outside_the_days_range_is_an_error() -> None:
    findings = check_ohlc_invariants([_bar("2020-01-01", 10, 12, 9, 20)])
    assert any("close 20" in f.detail for f in findings)


def test_a_negative_price_is_an_error() -> None:
    findings = check_ohlc_invariants([_bar("2020-01-01", -1, 12, -5, 10)])
    assert any("non-positive" in f.detail for f in findings)


def test_a_negative_volume_is_an_error() -> None:
    findings = check_ohlc_invariants([_bar("2020-01-01", 10, 12, 9, 11, volume=-5)])
    assert any("negative volume" in f.detail for f in findings)


def test_a_normal_bar_produces_nothing() -> None:
    assert check_ohlc_invariants([_bar("2020-01-01", 10, 12, 9, 11, volume=100)]) == []


# --- turnover consistency ---


def test_a_turnover_off_by_a_factor_of_ten_is_caught() -> None:
    """What a units error looks like."""
    bar = _bar("2020-01-01", 100, 105, 95, 100, volume=1000, turnover=1_000_000)
    assert check_turnover_consistency([bar])


def test_a_plausible_turnover_passes() -> None:
    bar = _bar("2020-01-01", 100, 105, 95, 100, volume=1000, turnover=100_000)
    assert check_turnover_consistency([bar]) == []


def test_zero_volume_is_skipped_rather_than_divided_by() -> None:
    bar = _bar("2020-01-01", 100, 105, 95, 100, volume=0, turnover=0)
    assert check_turnover_consistency([bar]) == []


# --- extreme moves ---


def test_an_unadjusted_bonus_looks_like_a_crash_and_is_flagged() -> None:
    """The case this check exists for: a 1:1 bonus halves the raw price."""
    bar = _bar("2020-06-01", 100, 105, 95, 100, prev_close=200)
    findings = check_extreme_moves([bar])
    assert findings
    assert "corporate action" in findings[0].detail


def test_an_ordinary_move_is_not_flagged() -> None:
    bar = _bar("2020-06-01", 100, 105, 95, 104, prev_close=100)
    assert check_extreme_moves([bar]) == []


# --- spikes, relative to the instrument's own history ---


def test_a_spike_is_found_against_a_quiet_series() -> None:
    bars = [
        _bar(f"2020-01-{d:02d}", 100, 101, 99, 100 + (d % 3), prev_close=100) for d in range(1, 20)
    ]
    bars.append(_bar("2020-01-20", 100, 190, 99, 185, prev_close=100))
    findings = check_return_spikes(bars)
    assert any(f.day == date(2020, 1, 20) for f in findings)


def test_a_uniformly_volatile_series_produces_no_spikes() -> None:
    """A small cap that always moves 8% must not be flagged every day."""
    bars = [
        _bar(f"2020-01-{d:02d}", 100, 110, 90, 100 + (8 if d % 2 else -8), prev_close=100)
        for d in range(1, 20)
    ]
    assert check_return_spikes(bars) == []


# --- stale prices ---


def test_a_long_flat_run_is_flagged() -> None:
    bars = [_bar(f"2020-01-{d:02d}", 50, 50, 50, 50) for d in range(1, 16)]
    findings = check_staleness_runs(bars)
    assert findings
    assert "15 consecutive" in findings[0].detail


def test_a_short_flat_run_is_not_flagged() -> None:
    bars = [_bar(f"2020-01-{d:02d}", 50, 50, 50, 50) for d in range(1, 4)]
    assert check_staleness_runs(bars) == []


# --- manifest checks ---


def test_a_missing_manifest_is_an_error(tmp_path: Path) -> None:
    findings = check_manifest_present(tmp_path / "absent.jsonl", "nse")
    assert findings[0].severity is Severity.ERROR


def test_an_empty_manifest_is_an_error_not_silence(tmp_path: Path) -> None:
    """'Nothing to report' and 'nothing to read' look the same in a summary
    and mean opposite things."""
    path = tmp_path / "manifest.jsonl"
    path.write_text("", encoding="utf-8")
    assert check_manifest_present(path, "nse")[0].severity is Severity.ERROR


def test_the_same_key_with_different_content_is_an_error(tmp_path: Path) -> None:
    """The landing zone claims raw data is immutable. Two hashes for one key
    means that claim just broke."""
    path = _manifest(
        tmp_path,
        [
            {"trade_date": "2020-01-01", "segment": "cm", "sha256": "aaa"},
            {"trade_date": "2020-01-01", "segment": "cm", "sha256": "bbb"},
        ],
    )
    findings = check_duplicate_keys(path, "nse")
    assert findings[0].severity is Severity.ERROR
    assert findings[0].check == "content-changed"


def test_the_same_key_with_identical_content_is_only_info(tmp_path: Path) -> None:
    """Re-landing the same bytes is harmless and happens after a prune."""
    path = _manifest(
        tmp_path,
        [
            {"trade_date": "2020-01-01", "segment": "cm", "sha256": "aaa"},
            {"trade_date": "2020-01-01", "segment": "cm", "sha256": "aaa"},
        ],
    )
    findings = check_duplicate_keys(path, "nse")
    assert findings[0].severity is Severity.INFO


def test_a_date_with_cash_but_no_derivatives_is_flagged(tmp_path: Path) -> None:
    path = _manifest(tmp_path, [{"trade_date": "2020-01-01", "segment": "cm", "sha256": "a"}])
    findings = check_segment_coverage(path)
    assert findings
    assert "fo" in findings[0].detail


def test_a_complete_day_is_not_flagged(tmp_path: Path) -> None:
    path = _manifest(
        tmp_path,
        [
            {"trade_date": "2020-01-01", "segment": "cm", "sha256": "a"},
            {"trade_date": "2020-01-01", "segment": "fo", "sha256": "b"},
        ],
    )
    assert check_segment_coverage(path) == []


def test_a_long_calendar_gap_is_flagged(tmp_path: Path) -> None:
    path = _manifest(
        tmp_path,
        [
            {"trade_date": "2020-01-01", "segment": "cm", "sha256": "a"},
            {"trade_date": "2020-03-01", "segment": "cm", "sha256": "b"},
        ],
    )
    findings = check_calendar_gaps(path)
    assert findings
    assert "60 days" in findings[0].detail


def test_a_weekend_is_not_a_gap(tmp_path: Path) -> None:
    path = _manifest(
        tmp_path,
        [
            {"trade_date": "2020-01-03", "segment": "cm", "sha256": "a"},
            {"trade_date": "2020-01-06", "segment": "cm", "sha256": "b"},
        ],
    )
    assert check_calendar_gaps(path) == []


def test_a_dataset_that_stopped_updating_is_flagged(tmp_path: Path) -> None:
    path = _manifest(
        tmp_path, [{"knowledge_time": "2026-01-01T00:00:00+00:00", "trade_date": "2026-01-01"}]
    )
    findings = check_staleness(path, "nse", now=UTC_NOW)
    assert findings
    assert "nothing fetched" in findings[0].detail


def test_a_current_dataset_is_not_flagged(tmp_path: Path) -> None:
    recent = (UTC_NOW - timedelta(days=1)).isoformat()
    path = _manifest(tmp_path, [{"knowledge_time": recent, "trade_date": "2026-08-18"}])
    assert check_staleness(path, "nse", now=UTC_NOW) == []


# --- the pre-listing split, which a blanket suppression would have hidden ---


def test_an_empty_window_before_first_data_is_only_info(tmp_path: Path) -> None:
    path = _manifest(
        tmp_path,
        [
            {"symbol": "NEWCO", "start": "2021-01-01", "rows": 0, "path": "a"},
            {"symbol": "NEWCO", "start": "2021-03-01", "rows": 500, "path": "b"},
        ],
    )
    findings = check_zero_row_files(path, "kite_minute")
    assert findings[0].check == "empty-chunk-pre-listing"
    assert findings[0].severity is Severity.INFO


def test_an_empty_window_after_data_started_is_a_warning(tmp_path: Path) -> None:
    """The real gap. Blanket-suppressing the pre-listing case would have
    silenced this too, which is the bug that split the check in two."""
    path = _manifest(
        tmp_path,
        [
            {"symbol": "ACME", "start": "2021-01-01", "rows": 500, "path": "a"},
            {"symbol": "ACME", "start": "2021-03-01", "rows": 0, "path": "b"},
        ],
    )
    findings = check_zero_row_files(path, "kite_minute")
    assert findings[0].check == "empty-chunk"
    assert findings[0].severity is Severity.WARN


# --- suppression must be precise, never broad ---


def test_a_known_finding_is_suppressed() -> None:
    report = Report()
    report.add(
        Finding(
            check="segment-coverage",
            severity=Severity.WARN,
            dataset="nse",
            day=date(2021, 3, 30),
            detail="x",
        )
    )
    assert report.findings == []
    assert len(report.suppressed) == 1


def test_the_same_check_on_another_day_is_not_suppressed() -> None:
    """The suppression is pinned to one date. A new gap must still report."""
    report = Report()
    report.add(
        Finding(
            check="segment-coverage",
            severity=Severity.WARN,
            dataset="nse",
            day=date(2022, 5, 5),
            detail="x",
        )
    )
    assert len(report.findings) == 1


def test_a_new_mid_history_gap_in_a_known_symbol_still_reports() -> None:
    """BCG has two suppressed windows. A third must not inherit them."""
    report = Report()
    report.add(
        Finding(
            check="empty-chunk",
            severity=Severity.WARN,
            dataset="kite_minute",
            symbol="BCG",
            day=date(2026, 1, 1),
            detail="x",
        )
    )
    assert len(report.findings) == 1


def test_every_suppression_cites_a_stub_id() -> None:
    """A suppression with no STUBS.md entry is how a real defect gets buried."""
    for known in KNOWN:
        assert known.stub.startswith("S-")
        assert known.reason


def test_a_suppression_matching_nothing_is_still_valid() -> None:
    report = Report()
    report.add(Finding(check="unrelated", severity=Severity.WARN, detail="x"))
    assert len(report.findings) == 1


# --- the report itself ---


def test_errors_make_the_report_fail() -> None:
    report = Report()
    report.add(Finding(check="ohlc-bounds", severity=Severity.ERROR, detail="x"))
    assert report.errors == 1
    assert "FAILED" in report.render()


def test_warnings_alone_do_not_fail_the_report() -> None:
    report = Report()
    report.add(Finding(check="return-spike", severity=Severity.WARN, detail="x"))
    assert report.errors == 0
    assert "OK" in report.render()


def test_findings_are_rendered_worst_first() -> None:
    report = Report()
    report.add(Finding(check="b-warn", severity=Severity.WARN, detail="x"))
    report.add(Finding(check="a-error", severity=Severity.ERROR, detail="y"))
    rendered = report.render()
    assert rendered.index("a-error") < rendered.index("b-warn")


def test_an_unused_suppression_is_visible_in_the_type() -> None:
    """Suppressions carry their reason so a reader can judge them without
    hunting through STUBS.md."""
    assert all(isinstance(k, Suppression) and k.reason for k in KNOWN)
