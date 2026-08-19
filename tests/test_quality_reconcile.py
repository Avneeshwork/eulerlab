"""Cross-source reconciliation: two vendors, one instrument-day."""

from __future__ import annotations

from datetime import date

from eulerlab.quality.reconcile import coverage_summary, reconcile_day
from eulerlab.quality.row_checks import Bar

DAY = date(2020, 1, 1)


def _bar(symbol: str, close: float, high: float = 0, low: float = 0, volume: float = 0) -> Bar:
    return Bar(
        symbol=symbol,
        day=DAY,
        open=close,
        high=high or close,
        low=low or close,
        close=close,
        volume=volume,
    )


def test_agreeing_sources_produce_nothing() -> None:
    assert reconcile_day([_bar("ACME", 100.0)], [_bar("ACME", 100.0)]) == []


def test_a_small_difference_is_within_tolerance() -> None:
    """NSE's close is a 30-minute VWAP, not the last trade, so the two
    legitimately differ slightly. Flagging that would report every day."""
    assert reconcile_day([_bar("ACME", 100.0)], [_bar("ACME", 100.5)]) == []


def test_a_large_close_disagreement_is_flagged() -> None:
    findings = reconcile_day([_bar("ACME", 100.0)], [_bar("ACME", 150.0)])
    assert findings
    assert "close" in findings[0].detail


def test_an_unadjusted_split_shows_up_as_a_close_disagreement() -> None:
    """The realistic case: one vendor applied a corporate action and the other
    did not, so the two disagree by exactly the ratio."""
    findings = reconcile_day([_bar("ACME", 100.0)], [_bar("ACME", 50.0)])
    assert any("50" in f.detail for f in findings)


def test_a_high_disagreement_is_flagged_separately() -> None:
    findings = reconcile_day([_bar("ACME", 100.0, high=120.0)], [_bar("ACME", 100.0, high=200.0)])
    assert any(f.detail.startswith("high") for f in findings)


def test_a_symbol_missing_from_the_second_source_is_not_a_finding() -> None:
    """Kite covers 420 symbols against bhavcopy's ~2,000. Reporting the
    difference would bury every real finding."""
    assert reconcile_day([_bar("ACME", 100.0), _bar("OTHER", 50.0)], [_bar("ACME", 100.0)]) == []


def test_a_different_day_is_not_compared() -> None:
    other = Bar(symbol="ACME", day=date(2020, 6, 1), open=1, high=1, low=1, close=1)
    assert reconcile_day([_bar("ACME", 100.0)], [other]) == []


def test_volume_within_an_order_of_magnitude_passes() -> None:
    findings = reconcile_day([_bar("ACME", 100.0, volume=1000)], [_bar("ACME", 100.0, volume=3000)])
    assert not [f for f in findings if f.check == "cross-source-volume"]


def test_a_volume_units_error_is_flagged() -> None:
    findings = reconcile_day(
        [_bar("ACME", 100.0, volume=1000)], [_bar("ACME", 100.0, volume=1_000_000)]
    )
    assert any(f.check == "cross-source-volume" for f in findings)


def test_coverage_is_reported_as_a_single_number() -> None:
    finding = coverage_summary(
        [_bar("A", 1), _bar("B", 1), _bar("C", 1), _bar("D", 1)], [_bar("A", 1), _bar("B", 1)]
    )
    assert "50.0%" in finding.detail


def test_coverage_of_an_empty_universe_does_not_divide_by_zero() -> None:
    assert "0.0%" in coverage_summary([], []).detail
